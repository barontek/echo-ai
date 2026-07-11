"""
Database unlock endpoint — POST password, GET status.

IMPORTANT: This is a single process-wide unlock, NOT per-session or per-user
authentication.  Once any client unlocks the database, all clients (multiple
browser tabs, curl, WebSockets, etc.) sharing the same web_api.py process are
unlocked.  There is no logout mechanism — the unlock persists until the server
restarts.

If this instance is ever exposed beyond localhost to more than one person, this
design is NOT appropriate — it provides no isolation between users.  Currently
the assumption is a single trusted user per running instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from ..config import DEFAULT_SESSION_DIR, load_config
from ..db_crypto import derive_key, generate_salt, get_or_create_salt, is_first_run, _write_user_version
from ..rate_limit import global_unlock_failures, increment_unlock_failures, reset_unlock_failures
from ..session import EncryptedJSON, SessionManager, db_write_lock
from ..web_models import UNLOCK_TOKEN_HEADER, generate_token, get_state, require_unlocked

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Unlock"])

UNLOCK_LIMIT = 5
UNLOCK_WINDOW = 60
GLOBAL_UNLOCK_LIMIT = 20
GLOBAL_UNLOCK_WINDOW = 60
_BACKOFF_THRESHOLD = 10  # consecutive global failures before exponential backoff begins


class UnlockRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    password: str
    confirm: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm: str


def _session_dir() -> Path:
    config = load_config()
    raw = os.environ.get("ECHO_SESSION_DIR") or config.get("agent", {}).get("session_dir", DEFAULT_SESSION_DIR)
    return Path(raw)


def _db_path(session_dir: Path) -> Path:
    return session_dir / "agent_sessions.db"


@router.post("/api/setup")
async def setup_database(request: Request, body: SetupRequest):
    """Create the database password on a fresh install.

    Only succeeds when neither the salt file nor the database file exists
    (i.e. :func:`is_first_run` returns ``True``).  Once the salt or DB
    exists this endpoint returns 409 — re-running setup would silently
    encrypt with a new key alongside old data.
    """
    from .. import web_api as _web_api

    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)

    if not is_first_run(salt_path, db_path):
        raise HTTPException(status_code=409, detail="Database already initialized")

    if body.password != body.confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if len(body.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long",
        )

    session_dir.mkdir(parents=True, exist_ok=True)
    salt = get_or_create_salt(salt_path)
    key = derive_key(body.password, salt)
    fernet = Fernet(key)

    old_fernet = EncryptedJSON._engine_fernet
    EncryptedJSON._engine_fernet = fernet
    test_sm: SessionManager | None = None
    try:
        test_sm = SessionManager(str(session_dir))
        test_sm.list_sessions(limit=1)
    except Exception as exc:
        EncryptedJSON._engine_fernet = old_fernet
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")
    finally:
        if test_sm is not None:
            test_sm.close()

    state = get_state()
    state.fernet = fernet
    state.fernet_key = key

    prefs = _web_api._load_preferences()
    model = prefs.get("model", "")
    provider = prefs.get("provider", "ollama")
    if not model:
        model = "llama3.2:latest"
    try:
        state.agent = _web_api._create_runtime_agent(
            provider=provider, model=model, fernet=fernet,
        )
    except Exception as exc:
        logger.warning("Could not create runtime agent on setup: %s", exc)

    # Generate an unlock token for the caller
    token = generate_token()
    state.active_tokens.add(token)

    return {"status": "setup_ok", "token": token}


@router.post("/api/unlock")
async def unlock_database(request: Request, body: UnlockRequest):
    """Derive Fernet from password and unlock the database.

    Rate-limited to 5 attempts per minute per IP, plus a global
    limit of 20 attempts per minute across all IPs.  After 10
    consecutive global failures exponential backoff kicks in,
    doubling the lockout for each subsequent batch of 10 failures.
    """
    from .. import web_api as _web_api

    client_ip = request.client.host if request.client else "unknown"

    # Global rate limit (all IPs combined)
    global_allowed, _ = await _web_api._rate_limiter.check(
        "unlock:global", GLOBAL_UNLOCK_LIMIT, GLOBAL_UNLOCK_WINDOW,
    )
    if not global_allowed:
        # Exponential backoff: after _BACKOFF_THRESHOLD consecutive failures,
        # multiply the lockout window by 2^((failures - threshold) // threshold)
        failures = global_unlock_failures()
        if failures >= _BACKOFF_THRESHOLD:
            multiplier = 2 ** ((failures - _BACKOFF_THRESHOLD) // _BACKOFF_THRESHOLD + 1)
            backoff_window = GLOBAL_UNLOCK_WINDOW * multiplier
            raise HTTPException(
                status_code=429,
                detail=f"Too many unlock attempts. Please wait {backoff_window} seconds.",
            )
        raise HTTPException(status_code=429, detail="Too many unlock attempts. Please wait.")

    # Per-IP rate limit
    ip_allowed, _ = await _web_api._rate_limiter.check(
        f"unlock:{client_ip}", UNLOCK_LIMIT, UNLOCK_WINDOW,
    )
    if not ip_allowed:
        raise HTTPException(status_code=429, detail="Too many unlock attempts. Please wait.")

    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)

    if is_first_run(salt_path, db_path):
        raise HTTPException(
            status_code=409,
            detail="Database not initialized. Call POST /api/setup first.",
        )

    if not salt_path.exists():
        raise HTTPException(
            status_code=500,
            detail="No encryption salt found. Run the CLI once to initialise the database.",
        )

    salt = salt_path.read_bytes()
    key = derive_key(body.password, salt)
    fernet = Fernet(key)

    # Test the password by setting the Fernet and trying a read
    old_fernet = EncryptedJSON._engine_fernet
    EncryptedJSON._engine_fernet = fernet
    test_sm: SessionManager | None = None
    try:
        test_sm = SessionManager(str(session_dir))
        test_sm.list_sessions(limit=1)
    except (ValueError, Exception) as exc:
        EncryptedJSON._engine_fernet = old_fernet
        if isinstance(exc, InvalidToken) or "Incorrect database password" in str(exc):
            increment_unlock_failures()
            raise HTTPException(status_code=401, detail="Incorrect password")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")
    finally:
        if test_sm is not None:
            test_sm.close()

    # Success — reset global failure counter and store on app state
    reset_unlock_failures()
    state = get_state()
    state.fernet = fernet
    state.fernet_key = key

    # Build a default agent from preferences / config so REST endpoints work
    prefs = _web_api._load_preferences()
    model = prefs.get("model", "")
    provider = prefs.get("provider", "ollama")
    if not model:
        model = "llama3.2:latest"
    try:
        state.agent = _web_api._create_runtime_agent(
            provider=provider, model=model, fernet=fernet,
        )
    except Exception as exc:
        logger.warning("Could not create runtime agent on unlock: %s", exc)

    # Generate an unlock token for the caller
    token = generate_token()
    state.active_tokens.add(token)

    return {"status": "unlocked", "token": token}


@router.post("/api/change-password")
async def change_password(body: ChangePasswordRequest, _=Depends(require_unlocked)):
    """Re-encrypt all stored sessions under a new password.

    Gated by :func:`require_unlocked` — the caller must already hold a valid
    unlocked session.  The endpoint independently re-verifies
    *current_password* before doing any work, then re-encrypts every row inside
    a single transaction.  The salt file and in-memory Fernet are only updated
    *after* the transaction commits successfully.
    """
    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)

    # -----------------------------------------------------------------
    # 1. Validate inputs
    # -----------------------------------------------------------------
    if body.new_password != body.confirm:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long",
        )

    # -----------------------------------------------------------------
    # 2. Verify current_password independently by deriving a Fernet
    #    from it and confirming it matches what is already in memory.
    # -----------------------------------------------------------------
    current_salt = salt_path.read_bytes()
    current_key = derive_key(body.current_password, current_salt)
    current_fernet = Fernet(current_key)

    state = get_state()
    if state.fernet_key is None:
        raise HTTPException(status_code=500, detail="No Fernet configured")

    # Confirm current_password produces the same Fernet key as the one
    # that is currently in memory — protects against e.g. an already-open
    # browser tab being used to silently change the password.
    if not secrets.compare_digest(current_key, state.fernet_key):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # -----------------------------------------------------------------
    # 3. Generate new salt + new Fernet (but do NOT persist yet)
    # -----------------------------------------------------------------
    new_salt = generate_salt()
    new_key = derive_key(body.new_password, new_salt)
    new_fernet = Fernet(new_key)

    # -----------------------------------------------------------------
    # 4. Write-ahead the new salt before touching the DB.
    #
    #    Write salt.new via temp-file + fsync + atomic rename so that
    #    the new salt is never left partially-written on disk.  At this
    #    point salt.new is inert — nobody reads it — it's just a
    #    crash-recovery marker that will be promoted only after the
    #    re-encryption transaction commits.
    # -----------------------------------------------------------------
    new_salt_path = salt_path.with_name("salt.new")
    _write_salt_atomically(new_salt_path, new_salt)

    # -----------------------------------------------------------------
    # 5. Re-encrypt every row inside a single DB transaction.
    #
    #    The entire critical section — from reading rows through to
    #    committing re-encrypted data and the PRAGMA user_version
    #    marker — is serialised under db_write_lock so that no
    #    concurrent chat write can interleave.
    #
    #    PRAGMA user_version is bumped to 1 in the SAME COMMIT as the
    #    re-encrypted data.  Because they share one atomic SQLite
    #    transaction, the marker and the data always agree — there is
    #    no window where one exists without the other after a crash.
    #
    #    The lock is acquired via asyncio.to_thread because the
    #    underlying Lock is a threading.Lock (not asyncio-compatible)
    #    and the same lock is held by SessionManager's synchronous
    #    write methods.
    # -----------------------------------------------------------------
    await asyncio.to_thread(db_write_lock.acquire)
    try:
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=DELETE"))
                conn.execute(text("PRAGMA synchronous=FULL"))

                rows = conn.execute(
                    text("SELECT id, title, messages, session_metadata, events FROM agent_sessions")
                ).fetchall()

                for row in rows:
                    row_id = row._mapping["id"]
                    title_raw = row._mapping["title"]
                    msg_raw = row._mapping["messages"]
                    meta_raw = row._mapping["session_metadata"]
                    evt_raw = row._mapping["events"]

                    decrypted_messages = json.loads(current_fernet.decrypt(msg_raw).decode("utf-8"))
                    decrypted_metadata: dict = {}
                    if meta_raw is not None:
                        decrypted_metadata = json.loads(current_fernet.decrypt(meta_raw).decode("utf-8"))
                    decrypted_events: list = []
                    if evt_raw is not None:
                        decrypted_events = json.loads(current_fernet.decrypt(evt_raw).decode("utf-8"))
                    decrypted_title: str | None = None
                    if title_raw is not None:
                        decrypted_title = json.loads(current_fernet.decrypt(title_raw).decode("utf-8"))

                    new_msg_raw = new_fernet.encrypt(
                        json.dumps(decrypted_messages, default=str).encode("utf-8")
                    )
                    new_meta_raw = (
                        new_fernet.encrypt(json.dumps(decrypted_metadata, default=str).encode("utf-8"))
                        if meta_raw is not None
                        else None
                    )
                    new_evt_raw = (
                        new_fernet.encrypt(json.dumps(decrypted_events, default=str).encode("utf-8"))
                        if evt_raw is not None
                        else None
                    )
                    new_title_raw = (
                        new_fernet.encrypt(json.dumps(decrypted_title).encode("utf-8"))
                        if title_raw is not None
                        else None
                    )

                    conn.execute(
                        text(
                            "UPDATE agent_sessions "
                            "SET title = :title, messages = :msg, "
                            "session_metadata = :meta, events = :evt "
                            "WHERE id = :id"
                        ),
                        {
                            "title": new_title_raw,
                            "msg": new_msg_raw,
                            "meta": new_meta_raw,
                            "evt": new_evt_raw,
                            "id": row_id,
                        },
                    )

                # Atomic marker: same COMMIT as the data above
                conn.execute(text("PRAGMA user_version = 1"))
                conn.commit()
        except Exception as exc:
            conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Re-encryption failed — database unchanged: {exc}",
            )
        finally:
            engine.dispose()

        # -----------------------------------------------------------------
        # 6. Promote the write-ahead salt (atomic rename on POSIX).
        #
        #    If the process crashes here, recovery sees uv=1 + salt.new
        #    exists and completes the rename.  If crash occurs after the
        #    rename but before step 7, recovery sees uv=1 + no salt.new
        #    and just resets uv to 0.
        # -----------------------------------------------------------------
        new_salt_path.rename(salt_path)
        salt_path.chmod(0o600)
        _write_user_version(db_path, 0)

        # -----------------------------------------------------------------
        # 7. Update in-memory state (not durable — rebuilt on restart)
        # -----------------------------------------------------------------
        state.fernet = new_fernet
        state.fernet_key = new_key
        EncryptedJSON._engine_fernet = new_fernet
    finally:
        db_write_lock.release()

    logger.info("Database password changed — all sessions re-encrypted with new key")

    return {"status": "password_changed"}


@router.post("/api/logout")
async def logout(request: Request):
    """Invalidate the caller's unlock token.

    If no active tokens remain, the agent is destroyed and the database
    is effectively re-locked until a new token is issued via
    ``POST /api/unlock``.
    """
    state = get_state()
    if state.agent is None:
        raise HTTPException(status_code=423, detail="Database is not unlocked")

    token = request.headers.get(UNLOCK_TOKEN_HEADER, "")
    if token:
        state.active_tokens.discard(token)

    if not state.active_tokens:
        # No more active tokens — destroy agent to re-lock
        if state.agent:
            try:
                if state.agent.session_manager:
                    state.agent.session_manager.close()
                state.agent.close()
            except Exception as exc:
                logger.debug("Error closing agent on logout: %s", exc)
        state.agent = None
        state.fernet = None
        state.fernet_key = None
        state.current_session_id = None
        state.message_history.clear()
        logger.info("Database re-locked — no active tokens remaining")
    else:
        logger.info("Client logged out (%d token(s) still active)", len(state.active_tokens))

    return {"status": "logged_out"}


def _write_salt_atomically(path: Path, data: bytes) -> None:
    """Write *data* to *path* using temp-file + fsync + atomic rename.

    Ensures the target file is never partially written on disk even
    if the process is killed mid-write.
    """
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.rename(path)


@router.get("/api/status")
async def status():
    state = get_state()
    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)
    needs_setup = is_first_run(salt_path, db_path)
    return {"locked": state.agent is None, "needs_setup": needs_setup}

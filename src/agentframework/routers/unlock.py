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

import os
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import base64
import json
import sqlite3

from ..config import DEFAULT_SESSION_DIR, load_config
from ..db_crypto import create_password, derive_key, generate_salt, is_first_run
from ..session import SessionManager, set_fernet
from ..web_models import get_state, require_unlocked

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Unlock"])

UNLOCK_LIMIT = 5
UNLOCK_WINDOW = 60


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
    fernet = create_password(body.password, salt_path)

    set_fernet(fernet)
    test_sm: SessionManager | None = None
    try:
        test_sm = SessionManager(str(session_dir))
        test_sm.list_sessions(limit=1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")
    finally:
        if test_sm is not None:
            test_sm.close()

    state = get_state()
    state.fernet = fernet

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

    return {"status": "setup_ok"}


@router.post("/api/unlock")
async def unlock_database(request: Request, body: UnlockRequest):
    """Derive Fernet from password and unlock the database.

    Rate-limited to 5 attempts per minute per IP.
    """
    from .. import web_api as _web_api

    # Rate-limit this endpoint with a separate key namespace
    client_ip = request.client.host if request.client else "unknown"
    allowed, _ = await _web_api._rate_limiter.check(
        f"unlock:{client_ip}", UNLOCK_LIMIT, UNLOCK_WINDOW,
    )
    if not allowed:
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

    # Test the password by setting the module-level Fernet and trying a read
    set_fernet(fernet)
    test_sm: SessionManager | None = None
    try:
        test_sm = SessionManager(str(session_dir))
        test_sm.list_sessions(limit=1)
    except (ValueError, Exception) as exc:
        if isinstance(exc, InvalidToken) or "Incorrect database password" in str(exc):
            raise HTTPException(status_code=401, detail="Incorrect password")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")
    finally:
        if test_sm is not None:
            test_sm.close()

    # Success — store on app state
    state = get_state()
    state.fernet = fernet

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

    return {"status": "unlocked"}


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
    if state.fernet is None:
        raise HTTPException(status_code=500, detail="No Fernet configured")

    # Confirm current_password produces the same Fernet key as the one
    # that is currently in memory — protects against e.g. an already-open
    # browser tab being used to silently change the password.
    # derive_key returns base64-urlsafe-encoded bytes; compare decoded raw keys.
    stored_raw_key = state.fernet._signing_key + state.fernet._encryption_key
    if base64.urlsafe_b64decode(current_key) != stored_raw_key:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # -----------------------------------------------------------------
    # 3. Generate new salt + new Fernet (but do NOT persist yet)
    # -----------------------------------------------------------------
    new_salt = generate_salt()
    new_key = derive_key(body.new_password, new_salt)
    new_fernet = Fernet(new_key)

    # -----------------------------------------------------------------
    # 4. Re-encrypt every row inside a single DB transaction
    # -----------------------------------------------------------------
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "SELECT id, messages, session_metadata, events FROM agent_sessions"
        )
        rows: list[tuple[str, bytes, bytes | None, bytes | None]] = list(cursor.fetchall())

        update_stmt = (
            "UPDATE agent_sessions SET messages = ?, session_metadata = ?, events = ? WHERE id = ?"
        )

        for row_id, msg_raw, meta_raw, evt_raw in rows:
            decrypted_messages = json.loads(current_fernet.decrypt(msg_raw).decode("utf-8"))
            decrypted_metadata: dict = {}
            if meta_raw is not None:
                decrypted_metadata = json.loads(current_fernet.decrypt(meta_raw).decode("utf-8"))
            decrypted_events: list = []
            if evt_raw is not None:
                decrypted_events = json.loads(current_fernet.decrypt(evt_raw).decode("utf-8"))

            new_msg_raw = new_fernet.encrypt(json.dumps(decrypted_messages, default=str).encode("utf-8"))
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

            conn.execute(update_stmt, (new_msg_raw, new_meta_raw, new_evt_raw, row_id))

        conn.commit()
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Re-encryption failed — database unchanged: {exc}",
        )
    finally:
        if conn is not None:
            conn.close()

    # -----------------------------------------------------------------
    # 5. Persist the new salt and update in-memory state
    # -----------------------------------------------------------------
    salt_path.write_bytes(new_salt)
    salt_path.chmod(0o600)
    state.fernet = new_fernet
    set_fernet(new_fernet)

    logger.info("Database password changed — all sessions re-encrypted with new key")

    return {"status": "password_changed"}


@router.get("/api/status")
async def status():
    state = get_state()
    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)
    needs_setup = is_first_run(salt_path, db_path)
    return {"locked": state.agent is None, "needs_setup": needs_setup}

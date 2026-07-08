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
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import DEFAULT_SESSION_DIR, load_config
from ..db_crypto import create_password, derive_key, is_first_run
from ..session import SessionManager, set_fernet
from ..web_models import get_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Unlock"])

UNLOCK_LIMIT = 5
UNLOCK_WINDOW = 60


class UnlockRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    password: str
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


@router.get("/api/status")
async def status():
    state = get_state()
    session_dir = _session_dir()
    salt_path = session_dir / ".db_salt"
    db_path = _db_path(session_dir)
    needs_setup = is_first_run(salt_path, db_path)
    return {"locked": state.agent is None, "needs_setup": needs_setup}

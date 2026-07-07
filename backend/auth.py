"""
Simple password-based authentication. No Google Cloud setup required.
First login sets the password. All subsequent logins verify against it.
"""

import os
import hashlib
import secrets
from pathlib import Path
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

# Store credentials in a simple local file
_AUTH_FILE = Path(__file__).parent / "data" / ".auth"
_active_tokens: dict[str, str] = {}  # token → username


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _load_stored_hash() -> str | None:
    if _AUTH_FILE.exists():
        return _AUTH_FILE.read_text().strip()
    return None


def _save_hash(pw_hash: str):
    _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTH_FILE.write_text(pw_hash)


def is_password_set() -> bool:
    return _load_stored_hash() is not None


def setup_password(password: str) -> str:
    """Set the app password for the first time. Returns a session token."""
    if is_password_set():
        raise HTTPException(status_code=400, detail="Password is already set.")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    _save_hash(_hash_password(password))
    token = secrets.token_urlsafe(32)
    _active_tokens[token] = "user"
    return token


def login(password: str) -> str:
    """Verify password and return a session token."""
    stored = _load_stored_hash()
    if not stored:
        raise HTTPException(status_code=400, detail="No password set. Please set one first.")
    if _hash_password(password) != stored:
        raise HTTPException(status_code=401, detail="Wrong password.")
    token = secrets.token_urlsafe(32)
    _active_tokens[token] = "user"
    return token


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """FastAPI dependency — verifies Bearer token from the Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )
    token = credentials.credentials
    user = _active_tokens.get(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    return user

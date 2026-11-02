"""Argon2 password hashing and opaque cookie sessions (DEC-09)."""
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import new_token, token_hash
from app.models import User, UserSession

SESSION_COOKIE = "etms_session"
_ph = PasswordHasher()


# PUBLIC_INTERFACE
def hash_password(password: str) -> str:
    """Return an Argon2 hash for the password."""
    return _ph.hash(password)


# PUBLIC_INTERFACE
def verify_password(password_hash: str, password: str) -> bool:
    """Return True when the password matches the stored hash."""
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# PUBLIC_INTERFACE
def create_session(db: Session, user: User) -> str:
    """Persist a new session for the user and return the raw cookie token (only its hash is stored)."""
    token = new_token()
    ttl = timedelta(hours=get_settings().SESSION_TTL_HOURS)
    db.add(UserSession(id=token_hash(token), user_id=user.id, expires_at=datetime.now(timezone.utc) + ttl))
    return token

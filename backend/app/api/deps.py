"""Request dependencies for database sessions, staff authorization, and scanner devices."""
from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import token_hash
from app.db import get_db
from app.errors import ApiError
from app.models import Device, User, UserSession
from app.permissions import has_permission
from app.security import SESSION_COOKIE


# PUBLIC_INTERFACE
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve an active user from the HttpOnly session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(401, "not_authenticated", "Login required")

    session = db.get(UserSession, token_hash(token))
    if not session or session.expires_at <= datetime.now(timezone.utc):
        raise ApiError(401, "session_expired", "Session expired; please log in again")

    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise ApiError(401, "not_authenticated", "Login required")
    return user


# PUBLIC_INTERFACE
def require_roles(*roles: str):
    """Create a dependency that requires one of the specified staff roles."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        """Validate the authenticated user's role."""
        if user.role not in roles:
            raise ApiError(403, "forbidden", "Insufficient role for this action")
        return user

    return dependency


ALL_STAFF = ("admin", "supervisor", "hr")


# PUBLIC_INTERFACE
def require_permission(permission: str):
    """Create a dependency that enforces one permission of the configurable matrix on the server."""

    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        """Validate that the authenticated user's role currently holds the permission."""
        if not has_permission(db, user.role, permission):
            raise ApiError(403, "forbidden", "You do not have permission for this action")
        return user

    return dependency


# PUBLIC_INTERFACE
def get_device(
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    db: Session = Depends(get_db),
) -> Device:
    """Resolve an active scanner device from its one-time device token."""
    if not x_device_token:
        raise ApiError(401, "device_token_required", "X-Device-Token header required")

    device = db.scalar(
        select(Device).where(Device.token_hash == token_hash(x_device_token))
    )
    if not device or not device.is_active:
        raise ApiError(401, "invalid_device", "Unknown or inactive device")
    return device

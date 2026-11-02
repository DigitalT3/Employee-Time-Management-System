"""Staff login/logout with HttpOnly session cookie and login throttle (DEC-09, DEC-10)."""
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.config import get_settings
from app.crypto import new_token, token_hash
from app.errors import ApiError
from app.models import LoginAttempt, User, UserSession
from app.permissions import effective_permissions
from app.schemas import LoginIn, MeOut
from app.security import SESSION_COOKIE, create_session, hash_password, verify_password
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified for unknown users so the response time does not reveal whether a username exists.
_DUMMY_HASH = hash_password(new_token())


def _me(db: Session, user: User) -> MeOut:
    return MeOut(id=user.id, username=user.username, role=user.role,
                 permissions=effective_permissions(db, user.role))


def _check_lock(db: Session, username: str) -> None:
    """Raise 429 login_locked when too many failures happened since the last success."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=s.LOGIN_LOCK_MINUTES)
    last_success = db.scalar(select(func.max(LoginAttempt.attempted_at)).where(
        LoginAttempt.username == username, LoginAttempt.succeeded.is_(True)))
    start = max(now - window, last_success) if last_success else now - window
    failures = list(db.scalars(select(LoginAttempt.attempted_at).where(
        LoginAttempt.username == username, LoginAttempt.succeeded.is_(False),
        LoginAttempt.attempted_at > start).order_by(LoginAttempt.attempted_at)))
    if len(failures) >= s.LOGIN_MAX_FAILURES:
        # The lock lifts when the oldest counted failure leaves the window.
        retry = max(1, math.ceil((failures[-s.LOGIN_MAX_FAILURES] + window - now).total_seconds()))
        raise ApiError(429, "login_locked", "Too many failed logins; try again later",
                       headers={"Retry-After": str(retry)}, retry_after_seconds=retry)


# PUBLIC_INTERFACE
@router.post("/login", response_model=MeOut, summary="Log in",
             description="Verifies credentials and sets an HttpOnly, SameSite=Lax session cookie. "
                         "Repeated failures lock the username temporarily (429 login_locked with Retry-After).")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate a staff user and start a session."""
    username = body.username.strip()[:64]
    _check_lock(db, username)
    user = db.scalar(select(User).where(User.username == username))
    password_ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    ok = bool(user and user.is_active and password_ok)
    db.add(LoginAttempt(username=username, succeeded=ok, attempted_at=datetime.now(timezone.utc),
                        ip_address=request.client.host if request.client else None))
    if not ok:
        db.commit()
        raise ApiError(401, "invalid_credentials", "Invalid username or password")
    token = create_session(db, user)
    audit.record(db, user.id, "auth.login", "user", user.id)
    db.commit()
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=bool(s.COOKIE_SECURE),
                        max_age=s.SESSION_TTL_HOURS * 3600, path="/")
    return _me(db, user)


# PUBLIC_INTERFACE
@router.post("/logout", status_code=204, summary="Log out")
def logout(request: Request, db: Session = Depends(get_db)):
    """Delete the current session (idempotent) and clear the cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(UserSession).filter(UserSession.id == token_hash(token)).delete()
        db.commit()
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# PUBLIC_INTERFACE
@router.get("/me", response_model=MeOut, summary="Current user",
            description="Returns the user and the permission keys granted to the role.")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the logged-in user with permissions."""
    return _me(db, user)

"""Append-only supervisor corrections with optimistic version checks and site-zone input (DEC-07)."""
import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import clock
from app.errors import ApiError
from app.models import AttendanceCorrection, AttendanceSession, Employee, Site, User
from app.schemas import CorrectionIn
from app.services import audit
from app.timeutil import day_bounds, local_iso, parse_local_value


# PUBLIC_INTERFACE
def apply_correction(
    db: Session,
    session_id,
    body: CorrectionIn,
    actor: User,
) -> AttendanceSession:
    """Append an audited correction while preserving original attendance events.

    A naive ``new_value`` is a wall-clock time at the session's site; an offset-aware value
    is used as given. Daylight-saving gaps and overlaps return explicit 422 errors.
    """
    session = db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.id == session_id)
        .with_for_update()
    )
    if not session:
        raise ApiError(404, "session_not_found", "Session not found")
    if session.version != body.expected_version:
        raise ApiError(
            409,
            "version_conflict",
            "Session was changed by someone else; reload and retry",
        )

    site_tz = ZoneInfo(db.get(Site, session.site_id).timezone)
    new_value = parse_local_value(body.new_value, site_tz)
    if new_value > clock.now():
        raise ApiError(422, "future_time", "Corrected time cannot be in the future")

    effective_in = new_value if body.field == "in" else session.effective_in
    effective_out = new_value if body.field == "out" else session.effective_out
    if effective_out is not None and effective_out <= effective_in:
        raise ApiError(422, "invalid_order", "OUT must be after IN")

    overlap_query = select(AttendanceSession.id).where(
        AttendanceSession.employee_id == session.employee_id,
        AttendanceSession.site_id == session.site_id,
        AttendanceSession.id != session.id,
        or_(
            AttendanceSession.effective_out.is_(None),
            AttendanceSession.effective_out > effective_in,
        ),
    )
    if effective_out is not None:
        overlap_query = overlap_query.where(AttendanceSession.effective_in < effective_out)
    if db.scalar(overlap_query.limit(1)):
        raise ApiError(422, "overlap", "Corrected session would overlap another session")

    old_value = session.effective_in if body.field == "in" else session.effective_out
    db.add(
        AttendanceCorrection(
            session_id=session.id,
            field=body.field,
            old_value=old_value,
            new_value=new_value,
            reason=body.reason,
            actor_user_id=actor.id,
        )
    )
    session.effective_in = effective_in
    session.effective_out = effective_out
    if body.field == "in":
        session.shift_date = effective_in.astimezone(site_tz).date()
    session.version += 1

    audit.record(
        db,
        actor.id,
        "session.correct",
        "attendance_session",
        session.id,
        {
            "field": body.field,
            "old": old_value.isoformat() if old_value else None,
            "new": new_value.isoformat(),
            "reason": body.reason,
            "version": session.version,
        },
    )
    db.commit()
    db.refresh(session)
    return session


def _dict(correction: AttendanceCorrection, username: str, employee: Employee | None = None,
          site: Site | None = None) -> dict:
    tz = ZoneInfo(site.timezone) if site else None
    data = {
        "id": str(correction.id),
        "session_id": str(correction.session_id),
        "field": correction.field,
        "old_value": correction.old_value.isoformat() if correction.old_value else None,
        "new_value": correction.new_value.isoformat(),
        "reason": correction.reason,
        "actor": username,
        "created_at": correction.created_at.isoformat(),
    }
    if tz:
        data.update({
            "site_timezone": tz.key,
            "old_value_local": local_iso(correction.old_value, tz),
            "new_value_local": local_iso(correction.new_value, tz),
            "created_at_local": local_iso(correction.created_at, tz),
        })
    if employee:
        data.update({
            "employee_id": str(employee.id),
            "employee_number": employee.employee_number,
            "employee_name": f"{employee.first_name} {employee.last_name}",
        })
    if site:
        data.update({"site_id": str(site.id), "site_code": site.code})
    return data


def _query():
    return (
        select(AttendanceCorrection, User.username, Employee, Site)
        .join(User, User.id == AttendanceCorrection.actor_user_id)
        .join(AttendanceSession, AttendanceSession.id == AttendanceCorrection.session_id)
        .join(Employee, Employee.id == AttendanceSession.employee_id)
        .join(Site, Site.id == AttendanceSession.site_id)
    )


# PUBLIC_INTERFACE
def list_corrections(db: Session, session_id) -> list[dict]:
    """Return correction history of one session in chronological order."""
    rows = db.execute(
        _query()
        .where(AttendanceCorrection.session_id == session_id)
        .order_by(AttendanceCorrection.created_at, AttendanceCorrection.id)
    ).all()
    return [_dict(c, username, employee, site) for c, username, employee, site in rows]


# PUBLIC_INTERFACE
def list_all_corrections(
    db: Session,
    *,
    employee_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return the global correction audit (newest first) with original value, actor and time."""
    query = _query()
    if employee_id:
        query = query.where(AttendanceSession.employee_id == employee_id)
    if site_id:
        query = query.where(AttendanceSession.site_id == site_id)
    if session_id:
        query = query.where(AttendanceCorrection.session_id == session_id)
    if date_from:
        query = query.where(AttendanceCorrection.created_at >= day_bounds(date_from, ZoneInfo("UTC"))[0])
    if date_to:
        query = query.where(AttendanceCorrection.created_at < day_bounds(date_to, ZoneInfo("UTC"))[1])
    total = db.scalar(select(func.count()).select_from(query.with_only_columns(AttendanceCorrection.id).subquery()))
    rows = db.execute(
        query.order_by(AttendanceCorrection.created_at.desc(), AttendanceCorrection.id).limit(limit).offset(offset)
    ).all()
    return {"total": total, "limit": limit, "offset": offset,
            "items": [_dict(c, username, employee, site) for c, username, employee, site in rows]}


# PUBLIC_INTERFACE
def get_correction(db: Session, correction_id: uuid.UUID) -> dict:
    """Return one correction or raise 404."""
    row = db.execute(_query().where(AttendanceCorrection.id == correction_id)).first()
    if not row:
        raise ApiError(404, "correction_not_found", "Correction not found")
    correction, username, employee, site = row
    return _dict(correction, username, employee, site)

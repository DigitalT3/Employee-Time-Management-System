"""Attendance session read models: on-site, daily, exceptions, history and dashboard (DEC-07, DEC-08, DEC-12)."""
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.models import (
    AttendanceEvent, AttendanceSession, Device, Employee, EmployeeSite, Gate, Site, SiteSettings,
)
from app.services import monitoring
from app.timeutil import day_bounds, local_iso

DEFAULT_CUTOFF = time(6, 0)
SESSION_STATUSES = ("open", "missing_out", "complete", "corrected")


class Policy:
    """Lazy cache of site rows, time zones and missing-OUT cutoff times."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[uuid.UUID, tuple[Site | None, ZoneInfo, time]] = {}

    def _entry(self, site_id: uuid.UUID) -> tuple[Site | None, ZoneInfo, time]:
        if site_id not in self._cache:
            site = self.db.get(Site, site_id)
            settings = self.db.get(SiteSettings, site_id)
            self._cache[site_id] = (
                site,
                ZoneInfo(site.timezone if site else get_settings().APP_TIMEZONE),
                settings.missing_out_cutoff_time if settings else DEFAULT_CUTOFF,
            )
        return self._cache[site_id]

    def get(self, site_id: uuid.UUID) -> tuple[ZoneInfo, time]:
        """Return timezone and cutoff configuration for a site."""
        _, tz, cutoff = self._entry(site_id)
        return tz, cutoff

    def site(self, site_id: uuid.UUID) -> Site | None:
        """Return the site row (cached)."""
        return self._entry(site_id)[0]


def _cutoff_at(session: AttendanceSession, policy: Policy) -> datetime:
    timezone, cutoff = policy.get(session.site_id)
    return datetime.combine(session.shift_date + timedelta(days=1), cutoff, tzinfo=timezone)


# PUBLIC_INTERFACE
def is_missing_out(session: AttendanceSession, policy: Policy, now: datetime) -> bool:
    """Return whether an open session has passed the local next-day cutoff."""
    if session.effective_out is not None:
        return False
    return now >= _cutoff_at(session, policy)


# PUBLIC_INTERFACE
def hours(session: AttendanceSession) -> float | None:
    """Return rounded attendance duration in hours for a closed session (not paid time)."""
    if session.effective_out is None:
        return None
    return round((session.effective_out - session.effective_in).total_seconds() / 3600, 2)


# PUBLIC_INTERFACE
def duration_minutes(session: AttendanceSession) -> int | None:
    """Return the attendance duration in whole minutes for a closed session."""
    if session.effective_out is None:
        return None
    return round((session.effective_out - session.effective_in).total_seconds() / 60)


# PUBLIC_INTERFACE
def session_status(session: AttendanceSession, policy: Policy, now: datetime) -> str:
    """Return open, missing_out or complete (computed at read time; no second source of truth)."""
    if session.effective_out is not None:
        return "complete"
    return "missing_out" if is_missing_out(session, policy, now) else "open"


# PUBLIC_INTERFACE
def session_flags(session: AttendanceSession, policy: Policy, now: datetime,
                  capture_modes: dict[uuid.UUID, str] | None = None) -> list[str]:
    """Return derived flags: missing_out, corrected, offline_capture, out_after_cutoff."""
    flags: list[str] = []
    if is_missing_out(session, policy, now):
        flags.append("missing_out")
    if session.version > 1:
        flags.append("corrected")
    modes = capture_modes or {}
    if modes.get(session.in_event_id) == "offline" or (
        session.out_event_id and modes.get(session.out_event_id) == "offline"
    ):
        flags.append("offline_capture")
    if session.effective_out is not None and session.effective_out >= _cutoff_at(session, policy):
        flags.append("out_after_cutoff")
    return flags


# PUBLIC_INTERFACE
def load_capture_modes(db: Session, sessions: list[AttendanceSession]) -> dict[uuid.UUID, str]:
    """Bulk-load the capture mode of every in/out event referenced by the sessions."""
    ids = {s.in_event_id for s in sessions} | {s.out_event_id for s in sessions if s.out_event_id}
    if not ids:
        return {}
    return {row.id: row.capture_mode for row in db.execute(
        select(AttendanceEvent.id, AttendanceEvent.capture_mode).where(AttendanceEvent.id.in_(ids)))}


# PUBLIC_INTERFACE
def session_dict(
    session: AttendanceSession,
    employee: Employee,
    policy: Policy,
    now: datetime,
    capture_modes: dict[uuid.UUID, str] | None = None,
) -> dict:
    """Serialize a session with site-local times, duration, status and flags."""
    tz, _ = policy.get(session.site_id)
    site = policy.site(session.site_id)
    missing = is_missing_out(session, policy, now)
    return {
        "id": str(session.id),
        "employee_id": str(employee.id),
        "employee_number": employee.employee_number,
        "employee_name": f"{employee.first_name} {employee.last_name}",
        "site_id": str(session.site_id),
        "site_code": site.code if site else None,
        "site_name": site.name if site else None,
        "site_timezone": tz.key,
        "in_event_id": str(session.in_event_id),
        "out_event_id": str(session.out_event_id) if session.out_event_id else None,
        "effective_in": session.effective_in.isoformat(),
        "effective_out": session.effective_out.isoformat() if session.effective_out else None,
        "local_in": local_iso(session.effective_in, tz),
        "local_out": local_iso(session.effective_out, tz),
        "shift_date": session.shift_date.isoformat(),
        "version": session.version,
        "corrected": session.version > 1,
        "hours": hours(session),
        "duration_minutes": duration_minutes(session),
        "missing_out": missing,
        "status": session_status(session, policy, now),
        "flags": session_flags(session, policy, now, capture_modes),
    }


def _sessions(site_id: uuid.UUID | None):
    """Build the common session/employee query."""
    query = select(AttendanceSession, Employee).join(
        Employee, Employee.id == AttendanceSession.employee_id
    )
    if site_id:
        query = query.where(AttendanceSession.site_id == site_id)
    return query


def _serialize(db: Session, rows, policy: Policy, now: datetime) -> list[dict]:
    modes = load_capture_modes(db, [s for s, _ in rows])
    return [session_dict(s, e, policy, now, modes) for s, e in rows]


# PUBLIC_INTERFACE
def on_site(db: Session, site_id: uuid.UUID | None) -> list[dict]:
    """Return employees currently recorded as IN, including sessions that are missing an OUT.

    A session past the cut-off is still the employee's latest recorded direction (IN), so it
    stays listed with ``status: missing_out`` instead of silently disappearing (DEC-08).
    """
    now = clock.now()
    policy = Policy(db)
    rows = db.execute(
        _sessions(site_id)
        .where(AttendanceSession.effective_out.is_(None))
        .order_by(AttendanceSession.effective_in)
    ).all()
    items = _serialize(db, rows, policy, now)
    for item in items:
        item["latest_direction"] = "IN"
        item["latest_in"] = item["effective_in"]
    return items


# PUBLIC_INTERFACE
def local_today(db: Session, site_id: uuid.UUID | None) -> date:
    """Return today's date in the selected site's local timezone."""
    timezone = Policy(db).get(site_id)[0] if site_id else ZoneInfo(get_settings().APP_TIMEZONE)
    return clock.now().astimezone(timezone).date()


# PUBLIC_INTERFACE
def daily(db: Session, site_id: uuid.UUID | None, day: date) -> dict:
    """Return daily totals and sessions grouped per employee."""
    now = clock.now()
    policy = Policy(db)
    rows = db.execute(
        _sessions(site_id)
        .where(AttendanceSession.shift_date == day)
        .order_by(Employee.employee_number, AttendanceSession.effective_in)
    ).all()
    modes = load_capture_modes(db, [s for s, _ in rows])

    employees: dict[uuid.UUID, dict] = {}
    for session, employee in rows:
        result = employees.setdefault(
            employee.id,
            {
                "employee_id": str(employee.id),
                "employee_number": employee.employee_number,
                "employee_name": f"{employee.first_name} {employee.last_name}",
                "total_hours": 0.0,
                "open": False,
                "missing_out": False,
                "sessions": [],
            },
        )
        serialized = session_dict(session, employee, policy, now, modes)
        result["sessions"].append(serialized)
        if serialized["hours"] is None:
            result["open"] = True
        else:
            result["total_hours"] = round(result["total_hours"] + serialized["hours"], 2)
        result["missing_out"] = result["missing_out"] or serialized["missing_out"]

    return {
        "date": day.isoformat(),
        "site_id": str(site_id) if site_id else None,
        "employees": list(employees.values()),
    }


# PUBLIC_INTERFACE
def exceptions(
    db: Session,
    site_id: uuid.UUID | None,
    day: date | None,
) -> list[dict]:
    """Return missing-OUT sessions, optionally limited to a shift date."""
    now = clock.now()
    policy = Policy(db)
    query = _sessions(site_id).where(AttendanceSession.effective_out.is_(None))
    if day:
        query = query.where(AttendanceSession.shift_date == day)
    rows = db.execute(query.order_by(AttendanceSession.effective_in)).all()
    rows = [(s, e) for s, e in rows if is_missing_out(s, policy, now)]
    return [{**item, "type": "missing_out"} for item in _serialize(db, rows, policy, now)]


# PUBLIC_INTERFACE
def history(
    db: Session,
    *,
    employee_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a filtered, paginated page of sessions (newest first) with derived status and flags.

    Status filters: ``complete``, ``corrected`` (version above 1), ``open`` and ``missing_out``.
    """
    now = clock.now()
    policy = Policy(db)
    base = _sessions(site_id)
    if employee_id:
        base = base.where(AttendanceSession.employee_id == employee_id)
    if date_from:
        base = base.where(AttendanceSession.shift_date >= date_from)
    if date_to:
        base = base.where(AttendanceSession.shift_date <= date_to)
    order = (AttendanceSession.shift_date.desc(), AttendanceSession.effective_in.desc())

    if status in ("open", "missing_out"):
        # The cut-off is per site, so these two states are derived in Python from open sessions.
        rows = [
            (s, e) for s, e in db.execute(
                base.where(AttendanceSession.effective_out.is_(None)).order_by(*order)).all()
            if session_status(s, policy, now) == status
        ]
        total = len(rows)
        rows = rows[offset:offset + limit]
    else:
        if status == "complete":
            base = base.where(AttendanceSession.effective_out.is_not(None))
        elif status == "corrected":
            base = base.where(AttendanceSession.version > 1)
        total = db.scalar(select(func.count()).select_from(base.subquery()))
        rows = db.execute(base.order_by(*order).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": _serialize(db, rows, policy, now)}


# PUBLIC_INTERFACE
def recent_activity(db: Session, site_id: uuid.UUID | None, day: date | None, limit: int = 20) -> list[dict]:
    """Return the latest attendance events with names and site-local times (staff only)."""
    policy = Policy(db)
    query = (
        select(AttendanceEvent, Employee, Gate, Device)
        .join(Employee, Employee.id == AttendanceEvent.employee_id)
        .join(Gate, Gate.id == AttendanceEvent.gate_id)
        .join(Device, Device.id == AttendanceEvent.device_id)
        .order_by(AttendanceEvent.occurred_at.desc())
        .limit(limit)
    )
    if site_id:
        query = query.where(AttendanceEvent.site_id == site_id)
    if day:
        start, end = day_bounds(day, policy.get(site_id)[0] if site_id else ZoneInfo(get_settings().APP_TIMEZONE))
        query = query.where(AttendanceEvent.occurred_at >= start, AttendanceEvent.occurred_at < end)
    items = []
    for event, employee, gate, device in db.execute(query).all():
        tz, _ = policy.get(event.site_id)
        items.append({
            "id": str(event.id),
            "employee_id": str(employee.id),
            "employee_number": employee.employee_number,
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "site_id": str(event.site_id),
            "gate_name": gate.name,
            "device_name": device.name,
            "direction": event.direction,
            "capture_mode": event.capture_mode,
            "occurred_at": event.occurred_at.isoformat(),
            "local_time": local_iso(event.occurred_at, tz),
            "site_timezone": tz.key,
        })
    return items


# PUBLIC_INTERFACE
def dashboard(db: Session, site_id: uuid.UUID | None, day: date | None, include_scan_log: bool) -> dict:
    """Return everything the supervisor dashboard needs in one request (DEC-08).

    The on-site list is always current; ``day`` scopes recent activity, exceptions and the
    incomplete count. All values are recorded attendance status, not verified presence.
    """
    now = clock.now()
    on = on_site(db, site_id)
    exc = exceptions(db, site_id, day)
    eligible = select(Employee.id).where(Employee.is_active.is_(True))
    if site_id:
        eligible = eligible.where(
            Employee.id.in_(select(EmployeeSite.employee_id).where(EmployeeSite.site_id == site_id)))
    on_ids = {uuid.UUID(item["employee_id"]) for item in on}
    off_site = len(set(db.scalars(eligible)) - on_ids)
    return {
        "as_of": now.isoformat(),
        "site_id": str(site_id) if site_id else None,
        "date": day.isoformat() if day else None,
        "label": "recorded_attendance_status",
        "counts": {"on_site": len(on), "off_site": off_site, "incomplete": len(exc)},
        "on_site": on,
        "recent_activity": recent_activity(db, site_id, day),
        "exceptions": exc,
        "scan_problems": monitoring.scan_log(db, site_id, None, 10, 0, since=now - timedelta(hours=24))["items"]
        if include_scan_log else [],
        "device_sync": monitoring.sync_status(db, site_id) if include_scan_log else [],
    }

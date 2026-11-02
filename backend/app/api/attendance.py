"""Dashboard, history, exceptions, sessions, events, sync status and corrections (FR-05, FR-09 to FR-11)."""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.api.deps import get_db, require_permission
from app.errors import ApiError
from app.models import AttendanceEvent, AttendanceSession, Device, Employee, Gate, User
from app.permissions import has_permission
from app.schemas import CorrectionCreate, CorrectionIn
from app.services import monitoring
from app.services import sessions as svc
from app.services.corrections import apply_correction, get_correction, list_all_corrections, list_corrections
from app.timeutil import local_iso

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _event(ev: AttendanceEvent | None) -> dict | None:
    if not ev:
        return None
    return {"id": str(ev.id), "employee_id": str(ev.employee_id), "site_id": str(ev.site_id),
            "gate_id": str(ev.gate_id), "device_id": str(ev.device_id), "direction": ev.direction,
            "occurred_at": ev.occurred_at.isoformat(), "received_at": ev.received_at.isoformat(),
            "capture_mode": ev.capture_mode, "client_uuid": str(ev.client_uuid)}


# PUBLIC_INTERFACE
@router.get("/dashboard", summary="Supervisor dashboard in one request",
            description="Counts, on-site list, recent activity, exceptions, scan problems and device sync. "
                        "All values are recorded attendance status, not verified presence. The on-site list is "
                        "always current; `date` scopes recent activity, exceptions and the incomplete count.")
def dashboard(site_id: uuid.UUID | None = None, day: date | None = Query(None, alias="date"),
              db: Session = Depends(get_db), user: User = Depends(require_permission("dashboard.view"))):
    """Return the dashboard read model."""
    return svc.dashboard(db, site_id, day, include_scan_log=has_permission(db, user.role, "scanlog.view"))


# PUBLIC_INTERFACE
@router.get("/on-site", summary="Live on-site employees")
@router.get("/current", summary="Currently recorded on-site employees (specification route)")
def on_site(site_id: uuid.UUID | None = None, db: Session = Depends(get_db),
            _: User = Depends(require_permission("attendance.view"))):
    """Employees whose latest recorded direction is IN; sessions past the cut-off show status missing_out."""
    items = svc.on_site(db, site_id)
    return {"as_of": clock.now().isoformat(), "count": len(items), "items": items}


# PUBLIC_INTERFACE
@router.get("/daily", summary="Daily attendance duration",
            description="Sessions are attributed to the local date of IN (default attribution; to be confirmed by Renewi). "
                        "Durations are attendance durations, not paid time.")
def daily(site_id: uuid.UUID | None = None, day: date | None = Query(None, alias="date"),
          db: Session = Depends(get_db), _: User = Depends(require_permission("attendance.view"))):
    """Per-employee attendance duration for a shift date (default: today in the site time zone)."""
    return svc.daily(db, site_id, day or svc.local_today(db, site_id))


# PUBLIC_INTERFACE
@router.get("/history", summary="Attendance history",
            description="Filtered, paginated sessions (newest first). status: open, missing_out, complete, corrected.")
def history(employee_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
            date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
            status: str | None = Query(None, pattern="^(open|missing_out|complete|corrected)$"),
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db), _: User = Depends(require_permission("attendance.view"))):
    """Return a page of attendance sessions."""
    if date_from and date_to and date_to < date_from:
        raise ApiError(422, "invalid_range", "'to' must not be before 'from'")
    return svc.history(db, employee_id=employee_id, site_id=site_id, date_from=date_from, date_to=date_to,
                       status=status, limit=limit, offset=offset)


# PUBLIC_INTERFACE
@router.get("/exceptions", summary="Missing-OUT exceptions")
def exceptions(site_id: uuid.UUID | None = None, day: date | None = Query(None, alias="date"),
               db: Session = Depends(get_db), _: User = Depends(require_permission("attendance.view"))):
    """Open sessions past the configured cutoff."""
    return {"items": svc.exceptions(db, site_id, day)}


# PUBLIC_INTERFACE
@router.get("/scan-log", summary="Scan log (staff only)",
            description="Rejected, duplicate, conflict and error submissions. Never contains the raw credential.")
def scan_log(site_id: uuid.UUID | None = None,
             outcome: str | None = Query(None, pattern="^(rejected|duplicate|conflict|error)$"),
             limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
             db: Session = Depends(get_db), _: User = Depends(require_permission("scanlog.view"))):
    """Return the operational scan log, newest first."""
    return monitoring.scan_log(db, site_id, outcome, limit, offset)


# PUBLIC_INTERFACE
@router.get("/sync/status", summary="Per-device synchronisation status",
            description="Connectivity and the pending/failed scan counts last reported by each tablet.")
def sync_status(site_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                _: User = Depends(require_permission("scanlog.view"))):
    """Return tablet heartbeat information."""
    return {"as_of": clock.now().isoformat(), "items": monitoring.sync_status(db, site_id)}


# PUBLIC_INTERFACE
@router.get("/events", summary="Raw attendance events",
            description="Immutable valid scan events, newest first, with employee, gate and site-local time.")
def events(employee_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
           from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
           limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db),
           _: User = Depends(require_permission("attendance.view"))):
    """List immutable scan events, newest first."""
    q = (select(AttendanceEvent, Employee, Gate, Device)
         .join(Employee, Employee.id == AttendanceEvent.employee_id)
         .join(Gate, Gate.id == AttendanceEvent.gate_id)
         .join(Device, Device.id == AttendanceEvent.device_id)
         .order_by(AttendanceEvent.occurred_at.desc()).limit(limit))
    if employee_id:
        q = q.where(AttendanceEvent.employee_id == employee_id)
    if site_id:
        q = q.where(AttendanceEvent.site_id == site_id)
    if from_:
        q = q.where(AttendanceEvent.occurred_at >= from_)
    if to:
        q = q.where(AttendanceEvent.occurred_at <= to)
    policy = svc.Policy(db)
    items = []
    for ev, emp, gate, dev in db.execute(q).all():
        tz = policy.get(ev.site_id)[0]
        items.append({**_event(ev), "employee_number": emp.employee_number,
                      "employee_name": f"{emp.first_name} {emp.last_name}", "gate_name": gate.name,
                      "device_name": dev.name, "local_time": local_iso(ev.occurred_at, tz),
                      "site_timezone": tz.key})
    return {"items": items}


def _session_detail(db: Session, s: AttendanceSession) -> dict:
    e = db.get(Employee, s.employee_id)
    policy = svc.Policy(db)
    data = svc.session_dict(s, e, policy, clock.now(), svc.load_capture_modes(db, [s]))
    data["in_event"] = _event(db.get(AttendanceEvent, s.in_event_id))
    data["out_event"] = _event(db.get(AttendanceEvent, s.out_event_id)) if s.out_event_id else None
    data["corrections"] = list_corrections(db, s.id)
    return data


# PUBLIC_INTERFACE
@router.get("/sessions/{session_id}", summary="Session detail",
            description="Effective times plus original events and correction history.")
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require_permission("attendance.view"))):
    """Return a session with its original events and corrections."""
    s = db.get(AttendanceSession, session_id)
    if not s:
        raise ApiError(404, "session_not_found", "Session not found")
    return _session_detail(db, s)


# PUBLIC_INTERFACE
@router.post("/sessions/{session_id}/corrections", status_code=201, summary="Correct a session",
             description="Requires attendance.correct; reason required; expected_version enforces optimistic locking. "
                         "A naive new_value is a wall-clock time at the site; DST gaps/overlaps return 422.")
def correct(session_id: uuid.UUID, body: CorrectionIn, db: Session = Depends(get_db),
            user: User = Depends(require_permission("attendance.correct"))):
    """Apply an audited correction and return the updated session."""
    s = apply_correction(db, session_id, body, user)
    return _session_detail(db, s)


# PUBLIC_INTERFACE
@router.get("/sessions/{session_id}/corrections", summary="Correction history")
def corrections(session_id: uuid.UUID, db: Session = Depends(get_db),
                _: User = Depends(require_permission("corrections.view"))):
    """List corrections for a session."""
    if not db.get(AttendanceSession, session_id):
        raise ApiError(404, "session_not_found", "Session not found")
    return {"items": list_corrections(db, session_id)}


# PUBLIC_INTERFACE
@router.post("/corrections", status_code=201, summary="Correct a session (global route)",
             description="Same rules as the per-session route; the session id is part of the body.")
def create_correction(body: CorrectionCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("attendance.correct"))):
    """Apply an audited correction identified by the body's session id."""
    s = apply_correction(db, body.session_id, body, user)
    detail = _session_detail(db, s)
    detail["correction"] = detail["corrections"][-1] if detail["corrections"] else None
    return detail


# PUBLIC_INTERFACE
@router.get("/corrections", summary="Global correction audit",
            description="Corrections newest first with original value, new value, reason, actor and time.")
def all_corrections(employee_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                    session_id: uuid.UUID | None = None,
                    date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db), _: User = Depends(require_permission("corrections.view"))):
    """Return the global correction history page."""
    return list_all_corrections(db, employee_id=employee_id, site_id=site_id, session_id=session_id,
                                date_from=date_from, date_to=date_to, limit=limit, offset=offset)


# PUBLIC_INTERFACE
@router.get("/corrections/{correction_id}", summary="One correction")
def one_correction(correction_id: uuid.UUID, db: Session = Depends(get_db),
                   _: User = Depends(require_permission("corrections.view"))):
    """Return a single correction record."""
    return get_correction(db, correction_id)

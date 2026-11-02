"""Operational read models: staff-only scan log and per-device synchronisation status (DEC-03)."""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.models import AuditLog, Device, Employee, ScanRequest, Site
from app.timeutil import local_iso

PROBLEM_OUTCOMES = ("rejected", "duplicate", "conflict", "error")
# Conflict and error submissions cannot live in scan_requests (keyed by client UUID),
# so they are recorded as audit entries named scan.conflict / scan.error.
_AUDIT_ACTIONS = {"scan.conflict": "conflict", "scan.error": "error"}
# A tablet that has not pinged or reported within this window is shown as offline.
ONLINE_WINDOW_SECONDS = 120


def _tz(db: Session, site_id: uuid.UUID, cache: dict) -> ZoneInfo:
    if site_id not in cache:
        site = db.get(Site, site_id)
        cache[site_id] = ZoneInfo(site.timezone if site else get_settings().APP_TIMEZONE)
    return cache[site_id]


# PUBLIC_INTERFACE
def scan_log(db: Session, site_id: uuid.UUID | None, outcome: str | None, limit: int, offset: int,
             since: datetime | None = None) -> dict:
    """Return rejected, duplicate, conflict and error submissions, newest first (staff only).

    Items carry the employee for staff when known, a reason and capture details; they never
    contain the raw credential.
    """
    wanted = [outcome] if outcome else list(PROBLEM_OUTCOMES)
    window = offset + limit
    tz_cache: dict = {}
    devices = {d.id: d for d in db.scalars(select(Device))}
    items: list[dict] = []
    total = 0

    req_outcomes = [o for o in wanted if o in ("rejected", "duplicate")]
    if req_outcomes:
        q = (select(ScanRequest, Employee)
             .join(Device, Device.id == ScanRequest.device_id)
             .outerjoin(Employee, Employee.id == ScanRequest.employee_id)
             .where(ScanRequest.outcome.in_(req_outcomes)))
        if site_id:
            q = q.where(Device.site_id == site_id)
        if since:
            q = q.where(ScanRequest.received_at >= since)
        total += db.scalar(select(func.count()).select_from(q.with_only_columns(ScanRequest.client_uuid).subquery()))
        for req, employee in db.execute(q.order_by(ScanRequest.received_at.desc()).limit(window)).all():
            device = devices[req.device_id]
            tz = _tz(db, device.site_id, tz_cache)
            items.append({
                "id": str(req.client_uuid), "outcome": req.outcome, "reason": req.reason,
                "device_id": str(device.id), "device_name": device.name, "site_id": str(device.site_id),
                "capture_mode": req.capture_mode, "device_sequence": req.device_sequence,
                "received_at": req.received_at.isoformat(), "local_time": local_iso(req.received_at, tz),
                "site_timezone": tz.key,
                "employee": {"employee_number": employee.employee_number,
                             "name": f"{employee.first_name} {employee.last_name}"} if employee else None,
                "_sort": req.received_at,
            })

    actions = [a for a, o in _AUDIT_ACTIONS.items() if o in wanted]
    if actions:
        q = select(AuditLog).where(AuditLog.action.in_(actions))
        if since:
            q = q.where(AuditLog.created_at >= since)
        rows = list(db.scalars(q.order_by(AuditLog.created_at.desc())))
        for row in rows:
            device = devices.get(uuid.UUID(row.entity_id)) if row.entity_id else None
            if device is None or (site_id and device.site_id != site_id):
                continue
            total += 1
            if len(items) >= window * 2:
                continue
            tz = _tz(db, device.site_id, tz_cache)
            items.append({
                "id": str(row.id), "outcome": _AUDIT_ACTIONS[row.action], "reason": row.details.get("reason"),
                "device_id": str(device.id), "device_name": device.name, "site_id": str(device.site_id),
                "capture_mode": row.details.get("capture_mode"),
                "device_sequence": row.details.get("device_sequence"),
                "received_at": row.created_at.isoformat(), "local_time": local_iso(row.created_at, tz),
                "site_timezone": tz.key, "employee": None, "_sort": row.created_at,
            })

    items.sort(key=lambda i: i["_sort"], reverse=True)
    page = items[offset:offset + limit]
    for item in page:
        item.pop("_sort", None)
    return {"total": total, "limit": limit, "offset": offset, "items": page}


# PUBLIC_INTERFACE
def sync_status(db: Session, site_id: uuid.UUID | None) -> list[dict]:
    """Return each tablet's connectivity and its last reported pending/failed scan counts."""
    now = clock.now()
    q = select(Device, Site).join(Site, Site.id == Device.site_id).order_by(Device.name)
    if site_id:
        q = q.where(Device.site_id == site_id)
    result = []
    for device, site in db.execute(q).all():
        tz = ZoneInfo(site.timezone)
        seen = device.last_seen_at
        if seen is None:
            connection = "never_seen"
        elif (now - seen) <= timedelta(seconds=ONLINE_WINDOW_SECONDS):
            connection = "online"
        else:
            connection = "offline"
        if device.reported_failed > 0:
            state = "failed"
        elif device.reported_pending > 0:
            state = "pending"
        else:
            state = "synced"
        result.append({
            "device_id": str(device.id), "device_name": device.name, "site_id": str(device.site_id),
            "is_active": device.is_active, "connection": connection, "state": state,
            "last_seen_at": seen.isoformat() if seen else None, "last_seen_local": local_iso(seen, tz),
            "pending": device.reported_pending, "failed": device.reported_failed,
            "oldest_pending_at": device.reported_oldest_pending_at.isoformat()
            if device.reported_oldest_pending_at else None,
            "last_sequence": device.last_sequence,
        })
    return result

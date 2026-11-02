"""Attendance scan processing shared by online scanning and offline synchronization.

Implements DEC-03 (disclosure minimisation), DEC-04 (offline protocol) and DEC-05
(timestamp trust). The backend alone decides IN or OUT.
"""
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.crypto import token_hash
from app.models import (
    AttendanceEvent,
    AttendanceSession,
    Device,
    Employee,
    EmployeeSite,
    QrCredential,
    ScanRequest,
    Site,
    SiteSettings,
)
from app.schemas import ScanIn
from app.services import audit
from app.services.credentials import normalize_payload
from app.timeutil import local_iso

DEFAULT_WINDOW = 120
log = logging.getLogger("etms.scan")


@dataclass
class _Evaluation:
    """Outcome of evaluating one new scan inside the open transaction."""

    status: int
    response: dict
    event_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    occurred_at: datetime | None = None


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a timestamp to an aware UTC-compatible value."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _fingerprint(device: Device, item: ScanIn) -> str:
    """Create a stable payload fingerprint for idempotency validation."""
    captured_at = _aware(item.captured_at)
    value = "|".join(
        [
            str(device.id),
            str(item.device_sequence),
            token_hash(normalize_payload(item.token)),
            captured_at.isoformat() if captured_at else "",
            item.capture_mode,
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()


def credential_ref(token: str) -> str:
    """Return a short keyed reference safe for logs (never the credential itself)."""
    return token_hash(normalize_payload(token))[:8]


def _response(item: ScanIn, outcome: str, status: int, tz: ZoneInfo | None = None, *,
              reason: str | None = None, direction: str | None = None, employee: Employee | None = None,
              event_id: uuid.UUID | None = None, occurred_at: datetime | None = None,
              duration_minutes: int | None = None, last_sequence: int | None = None,
              mismatch: bool = False, retryable: bool = False) -> dict:
    """Build the token-safe scan result shared by /scan and /sync.

    The employee name is only given for accepted and duplicate outcomes; rejected,
    conflict and error results never disclose an identity.
    """
    return {
        "client_uuid": str(item.client_uuid),
        "device_sequence": item.device_sequence,
        "status": status,
        "outcome": outcome,
        "retryable": retryable,
        "reason": reason,
        "direction": direction,
        "employee": {"name": f"{employee.first_name} {employee.last_name}"} if employee is not None else None,
        "event_id": str(event_id) if event_id else None,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "local_time": local_iso(occurred_at, tz) if tz and occurred_at else None,
        "site_timezone": tz.key if tz else None,
        "duration_minutes": duration_minutes,
        "last_sequence": last_sequence,
        "direction_mismatch": mismatch,
    }


def _replay(existing: ScanRequest, device: Device, fingerprint: str, item: ScanIn) -> tuple[int, dict]:
    """Return an exact stored result or conflict when a UUID was reused differently."""
    if existing.device_id != device.id or existing.payload_fingerprint != fingerprint:
        return 409, _response(item, "conflict", 409, reason="client_uuid_reused")
    return 200, {
        **existing.response,
        "status": 200,
        "outcome": "replay",
        "original_outcome": existing.response.get("outcome"),
    }


def _resolve_time(item: ScanIn, captured_at: datetime | None, now: datetime) -> tuple[datetime, str | None]:
    """Apply the DEC-05 timestamp rules and return (occurred_at, rejection reason or None)."""
    settings = get_settings()
    if item.capture_mode == "online":
        if captured_at and abs((captured_at - now).total_seconds()) <= settings.ONLINE_SKEW_SECONDS:
            return captured_at, None
        return now, None
    if captured_at is None:
        return now, None
    if captured_at < now - timedelta(hours=settings.OFFLINE_MAX_AGE_HOURS):
        return now, "captured_too_old"
    if captured_at > now + timedelta(seconds=settings.FUTURE_TOLERANCE_SECONDS):
        return now, "captured_in_future"
    return min(captured_at, now), None


def _evaluate(db: Session, device: Device, item: ScanIn) -> _Evaluation:
    """Evaluate a new scan while the surrounding transaction remains open."""
    now = clock.now()
    site = db.get(Site, device.site_id)
    tz = ZoneInfo(site.timezone)
    occurred_at, time_reason = _resolve_time(item, _aware(item.captured_at), now)

    def reject(reason: str, employee_id: uuid.UUID | None = None) -> _Evaluation:
        return _Evaluation(
            200, _response(item, "rejected", 200, tz, reason=reason, occurred_at=occurred_at),
            employee_id=employee_id, occurred_at=occurred_at,
        )

    credential = db.scalar(
        select(QrCredential).where(
            QrCredential.token_hash == token_hash(normalize_payload(item.token))
        )
    )
    if not credential:
        return reject("unknown_credential")

    employee = db.scalar(
        select(Employee).where(Employee.id == credential.employee_id).with_for_update()
    )
    if credential.status == "revoked":
        return reject("revoked", employee.id)
    if credential.status != "active":
        return reject("blocked", employee.id)
    if not employee.is_active:
        return reject("inactive_employee", employee.id)
    if not db.get(EmployeeSite, (employee.id, device.site_id)):
        return reject("wrong_site", employee.id)
    if time_reason:
        return reject(time_reason, employee.id)

    settings = db.get(SiteSettings, device.site_id)
    duplicate_window = settings.duplicate_window_seconds if settings else DEFAULT_WINDOW
    previous = db.scalar(
        select(AttendanceEvent)
        .where(
            AttendanceEvent.employee_id == employee.id,
            AttendanceEvent.site_id == device.site_id,
        )
        .order_by(AttendanceEvent.occurred_at.desc())
        .limit(1)
    )
    if previous and abs((occurred_at - previous.occurred_at).total_seconds()) < duplicate_window:
        return _Evaluation(
            200,
            _response(
                item, "duplicate", 200, tz, reason="within_duplicate_window",
                direction=previous.direction, employee=employee, event_id=previous.id,
                occurred_at=previous.occurred_at,
            ),
            employee_id=employee.id, occurred_at=previous.occurred_at,
        )
    if previous and occurred_at < previous.occurred_at:
        return reject("out_of_order", employee.id)

    session = db.scalar(
        select(AttendanceSession)
        .where(
            AttendanceSession.employee_id == employee.id,
            AttendanceSession.site_id == device.site_id,
            AttendanceSession.effective_out.is_(None),
        )
        .with_for_update()
    )
    if session and occurred_at <= session.effective_in:
        return reject("out_of_order", employee.id)

    direction = "OUT" if session else "IN"
    event = AttendanceEvent(
        id=uuid.uuid4(),
        employee_id=employee.id,
        site_id=device.site_id,
        gate_id=device.gate_id,
        device_id=device.id,
        direction=direction,
        occurred_at=occurred_at,
        capture_mode=item.capture_mode,
        client_uuid=item.client_uuid,
    )
    db.add(event)
    db.flush()

    duration_minutes = None
    if direction == "IN":
        shift_date = occurred_at.astimezone(tz).date()
        db.add(
            AttendanceSession(
                employee_id=employee.id,
                site_id=device.site_id,
                in_event_id=event.id,
                effective_in=occurred_at,
                shift_date=shift_date,
            )
        )
    else:
        session.out_event_id = event.id
        session.effective_out = occurred_at
        duration_minutes = round((occurred_at - session.effective_in).total_seconds() / 60)

    mismatch = item.tentative_direction is not None and item.tentative_direction != direction
    return _Evaluation(
        201,
        _response(
            item, "accepted", 201, tz, direction=direction, employee=employee, event_id=event.id,
            occurred_at=occurred_at, duration_minutes=duration_minutes, mismatch=mismatch,
        ),
        event_id=event.id, employee_id=employee.id, occurred_at=occurred_at,
    )


def _record_failure(db: Session, device: Device, item: ScanIn, outcome: str, reason: str) -> None:
    """Best-effort audit entry for conflict and error submissions (shown in the scan log).

    ``scan_requests`` is keyed by client UUID, so these outcomes cannot be stored there.
    """
    try:
        audit.record(
            db, None, f"scan.{outcome}", "device", device.id,
            {"reason": reason, "client_uuid": str(item.client_uuid),
             "device_sequence": item.device_sequence, "capture_mode": item.capture_mode,
             "credential_ref": credential_ref(item.token)},
        )
        db.commit()
    except Exception:  # noqa: BLE001 - failure logging must never mask the original result
        db.rollback()


# PUBLIC_INTERFACE
def process_scan(db: Session, device: Device, item: ScanIn) -> tuple[int, dict]:
    """Persist one scan atomically and return its HTTP status and token-safe result."""
    fingerprint = _fingerprint(device, item)
    existing = db.get(ScanRequest, item.client_uuid)
    if existing:
        status, response = _replay(existing, device, fingerprint, item)
        if status == 409:
            _record_failure(db, device, item, "conflict", response["reason"])
        return status, response

    sequence_match = db.scalar(
        select(ScanRequest).where(
            ScanRequest.device_id == device.id,
            ScanRequest.device_sequence == item.device_sequence,
        )
    )
    if sequence_match:
        last = db.scalar(select(Device.last_sequence).where(Device.id == device.id))
        _record_failure(db, device, item, "conflict", "device_sequence_reused")
        return 409, _response(item, "conflict", 409, reason="device_sequence_reused", last_sequence=last)

    try:
        result = _evaluate(db, device, item)
        db.add(
            ScanRequest(
                client_uuid=item.client_uuid,
                device_id=device.id,
                device_sequence=item.device_sequence,
                payload_fingerprint=fingerprint,
                outcome=result.response["outcome"],
                event_id=result.event_id,
                employee_id=result.employee_id,
                reason=result.response["reason"],
                capture_mode=item.capture_mode,
                captured_at=_aware(item.captured_at),
                occurred_at=result.occurred_at,
                response=result.response,
            )
        )
        locked_device = db.get(Device, device.id, with_for_update=True, populate_existing=True)
        locked_device.last_sequence = max(locked_device.last_sequence, item.device_sequence)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(ScanRequest, item.client_uuid)
        if existing:
            return _replay(existing, db.get(Device, device.id), fingerprint, item)
        _record_failure(db, device, item, "conflict", "concurrent_conflict")
        return 409, _response(item, "conflict", 409, reason="concurrent_conflict", retryable=True)
    except Exception:
        db.rollback()
        raise

    if result.response["outcome"] == "rejected":
        # Operational/security log line: a keyed reference only, never the credential (FR-03).
        log.warning(
            "scan_rejected reason=%s credential_ref=%s device_id=%s site_id=%s capture_mode=%s",
            result.response["reason"], credential_ref(item.token), device.id, device.site_id, item.capture_mode,
        )
    return result.status, result.response


# PUBLIC_INTERFACE
def process_sync(db: Session, device: Device, items: list[ScanIn]) -> list[dict]:
    """Process an offline batch by ascending device sequence, stopping at the first retryable failure.

    The failing item returns ``outcome: error`` and every later item ``outcome: skipped``
    (both retryable and unprocessed) so the tablet keeps them pending and resends in order.
    """
    results: list[dict] = []
    failed = False
    for item in sorted(items, key=lambda entry: entry.device_sequence):
        if failed:
            results.append(_response(item, "skipped", 424, reason="preceding_item_failed", retryable=True))
            continue
        try:
            status, response = process_scan(db, device, item)
        except Exception as exc:  # noqa: BLE001 - isolate the item; the tablet retries it
            db.rollback()
            log.error("scan_processing_failed error_type=%s device_id=%s", type(exc).__name__, device.id)
            _record_failure(db, device, item, "error", "retry_later")
            status, response = 503, _response(item, "error", 503, reason="retry_later", retryable=True)
        if response.get("retryable"):
            failed = True
        results.append({**response, "status": status})
    return results

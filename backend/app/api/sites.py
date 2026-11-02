"""Site, gate, attendance-policy, and scanner-device administration endpoints."""
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.api.deps import get_db, get_device, require_permission
from app.config import get_settings
from app.crypto import new_token, token_hash
from app.errors import ApiError
from app.models import Device, Gate, Site, SiteSettings, User
from app.schemas import (
    DeviceCreate,
    DeviceCreated,
    DeviceOut,
    DeviceUpdate,
    GateCreate,
    GateCreateFlat,
    GateOut,
    GateUpdate,
    ScannerStatusIn,
    SiteCreate,
    SiteOut,
    SiteSettingsIO,
    SiteUpdate,
)
from app.services import audit

router = APIRouter(tags=["sites"])


def _site(db: Session, site_id: uuid.UUID) -> Site:
    """Load a site or produce the standard not-found error."""
    site = db.get(Site, site_id)
    if not site:
        raise ApiError(404, "site_not_found", "Site not found")
    return site


def _validate_timezone(value: str) -> str:
    """Validate an IANA timezone name."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiError(422, "invalid_timezone", "Unknown IANA timezone") from exc
    return value


def _commit(db: Session, code: str, message: str) -> None:
    """Commit a transaction and translate unique-constraint failures."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, code, message) from exc


def _settings(db: Session, site_id: uuid.UUID) -> SiteSettings:
    """Load the site's policy, creating the default policy if required."""
    _site(db, site_id)
    settings = db.get(SiteSettings, site_id)
    if settings is None:
        settings = SiteSettings(site_id=site_id, duplicate_window_seconds=120)
        db.add(settings)
        db.flush()
    return settings


# PUBLIC_INTERFACE
@router.get("/sites", response_model=list[SiteOut], summary="List sites")
def list_sites(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attendance.view")),
) -> list[Site]:
    """List registered sites ordered by their stable site code."""
    return list(db.scalars(select(Site).order_by(Site.code)))


# PUBLIC_INTERFACE
@router.post("/sites", response_model=SiteOut, status_code=201, summary="Create site")
def create_site(
    body: SiteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Site:
    """Create a site together with its default attendance settings."""
    code = body.code.strip()
    if db.scalar(select(Site.id).where(Site.code == code)):
        raise ApiError(409, "site_code_taken", "Site code already exists")
    site = Site(
        id=uuid.uuid4(),
        code=code,
        name=body.name.strip(),
        timezone=_validate_timezone(body.timezone),
    )
    db.add(site)
    db.flush()
    db.add(SiteSettings(site_id=site.id))
    audit.record(db, user.id, "site.create", "site", site.id, {"code": site.code})
    _commit(db, "site_code_taken", "Site code already exists")
    db.refresh(site)
    return site


# PUBLIC_INTERFACE
@router.patch("/sites/{site_id}", response_model=SiteOut, summary="Update site")
def update_site(
    site_id: uuid.UUID,
    body: SiteUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Site:
    """Update the editable attributes of a site."""
    site = _site(db, site_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "timezone" in changes:
        changes["timezone"] = _validate_timezone(changes["timezone"])
    for key, value in changes.items():
        setattr(site, key, value.strip() if isinstance(value, str) else value)
    audit.record(db, user.id, "site.update", "site", site.id, {"fields": sorted(changes)})
    db.commit()
    db.refresh(site)
    return site


# PUBLIC_INTERFACE
@router.get(
    "/sites/{site_id}/settings",
    response_model=SiteSettingsIO,
    summary="Get site settings",
)
def get_site_settings(
    site_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attendance.view")),
) -> SiteSettings:
    """Return duplicate-window and missing-OUT policy configuration."""
    return _settings(db, site_id)


# PUBLIC_INTERFACE
@router.put(
    "/sites/{site_id}/settings",
    response_model=SiteSettingsIO,
    summary="Update site settings",
)
def put_site_settings(
    site_id: uuid.UUID,
    body: SiteSettingsIO,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> SiteSettings:
    """Replace the configured attendance policy for a site."""
    settings = _settings(db, site_id)
    settings.duplicate_window_seconds = body.duplicate_window_seconds
    settings.missing_out_cutoff_time = body.missing_out_cutoff_time
    audit.record(
        db,
        user.id,
        "site.settings",
        "site",
        site_id,
        {"new": body.model_dump(mode="json")},
    )
    db.commit()
    db.refresh(settings)
    return settings


# PUBLIC_INTERFACE
@router.get(
    "/sites/{site_id}/gates",
    response_model=list[GateOut],
    summary="List site gates",
)
def list_gates(
    site_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attendance.view")),
) -> list[Gate]:
    """List the gates configured at one site."""
    _site(db, site_id)
    return list(db.scalars(select(Gate).where(Gate.site_id == site_id).order_by(Gate.name)))


# PUBLIC_INTERFACE
@router.post(
    "/sites/{site_id}/gates",
    response_model=GateOut,
    status_code=201,
    summary="Create gate",
)
def create_gate(
    site_id: uuid.UUID,
    body: GateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Gate:
    """Create a uniquely named gate for a site."""
    _site(db, site_id)
    gate = Gate(id=uuid.uuid4(), site_id=site_id, name=body.name.strip())
    db.add(gate)
    audit.record(db, user.id, "gate.create", "gate", gate.id, {"name": gate.name})
    _commit(db, "gate_name_taken", "Gate name already exists at this site")
    db.refresh(gate)
    return gate


# PUBLIC_INTERFACE
@router.get("/gates", response_model=list[GateOut], summary="List gates (flat route)")
def list_gates_flat(
    site_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("attendance.view")),
) -> list[Gate]:
    """List gates, optionally filtered by site."""
    query = select(Gate).order_by(Gate.name)
    if site_id:
        query = query.where(Gate.site_id == site_id)
    return list(db.scalars(query))


# PUBLIC_INTERFACE
@router.post("/gates", response_model=GateOut, status_code=201, summary="Create gate (flat route)")
def create_gate_flat(
    body: GateCreateFlat,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Gate:
    """Create a uniquely named gate; the site id is part of the body."""
    _site(db, body.site_id)
    gate = Gate(id=uuid.uuid4(), site_id=body.site_id, name=body.name.strip())
    db.add(gate)
    audit.record(db, user.id, "gate.create", "gate", gate.id, {"name": gate.name})
    _commit(db, "gate_name_taken", "Gate name already exists at this site")
    db.refresh(gate)
    return gate


# PUBLIC_INTERFACE
@router.patch("/gates/{gate_id}", response_model=GateOut, summary="Update gate")
def update_gate(
    gate_id: uuid.UUID,
    body: GateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Gate:
    """Update a gate's name or active state."""
    gate = db.get(Gate, gate_id)
    if not gate:
        raise ApiError(404, "gate_not_found", "Gate not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(gate, key, value.strip() if isinstance(value, str) else value)
    audit.record(db, user.id, "gate.update", "gate", gate.id, {"fields": sorted(changes)})
    _commit(db, "gate_name_taken", "Gate name already exists at this site")
    db.refresh(gate)
    return gate


# PUBLIC_INTERFACE
@router.get("/devices", response_model=list[DeviceOut], tags=["devices"], summary="List devices")
def list_devices(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("scanlog.view")),
) -> list[Device]:
    """List devices without exposing their secret tokens."""
    return list(db.scalars(select(Device).order_by(Device.name)))


# PUBLIC_INTERFACE
@router.post(
    "/devices",
    response_model=DeviceCreated,
    status_code=201,
    tags=["devices"],
    summary="Register scanner device",
)
def create_device(
    body: DeviceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> DeviceCreated:
    """Register a scanner device and expose its token exactly once."""
    gate = db.get(Gate, body.gate_id)
    if not gate or not gate.is_active:
        raise ApiError(422, "invalid_gate", "Gate not found or inactive")

    token = new_token()
    device = Device(
        id=uuid.uuid4(),
        name=body.name.strip(),
        site_id=gate.site_id,
        gate_id=gate.id,
        token_hash=token_hash(token),
    )
    db.add(device)
    audit.record(db, user.id, "device.create", "device", device.id, {"gate_id": str(gate.id)})
    db.commit()
    db.refresh(device)
    return DeviceCreated(**DeviceOut.model_validate(device).model_dump(), device_token=token)


# PUBLIC_INTERFACE
@router.patch(
    "/devices/{device_id}",
    response_model=DeviceOut,
    tags=["devices"],
    summary="Activate or deactivate scanner device",
)
def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sites.manage")),
) -> Device:
    """Toggle a device's active state."""
    device = db.get(Device, device_id)
    if not device:
        raise ApiError(404, "device_not_found", "Device not found")
    device.is_active = body.is_active
    audit.record(
        db,
        user.id,
        "device.update",
        "device",
        device.id,
        {"is_active": body.is_active},
    )
    db.commit()
    db.refresh(device)
    return device


# PUBLIC_INTERFACE
@router.get(
    "/scanner/context",
    tags=["scanning"],
    summary="Get scanner context",
)
def scanner_context(
    device: Device = Depends(get_device),
    db: Session = Depends(get_db),
) -> dict:
    """Return the bound scanner device, site, gate, and duplicate-window setting."""
    site = db.get(Site, device.site_id)
    gate = db.get(Gate, device.gate_id)
    settings = db.get(SiteSettings, device.site_id)
    cfg = get_settings()
    return {
        "device": {
            "id": str(device.id),
            "name": device.name,
            "last_sequence": device.last_sequence,
        },
        "site": {
            "id": str(site.id),
            "code": site.code,
            "name": site.name,
            "timezone": site.timezone,
        },
        "gate": {"id": str(gate.id), "name": gate.name},
        "duplicate_window_seconds": (
            settings.duplicate_window_seconds if settings else 120
        ),
        "server_time": clock.now().isoformat(),
        "offline_max_age_hours": cfg.OFFLINE_MAX_AGE_HOURS,
        "online_skew_seconds": cfg.ONLINE_SKEW_SECONDS,
    }


# PUBLIC_INTERFACE
@router.get(
    "/scanner/ping",
    tags=["scanning"],
    summary="Scanner heartbeat",
    description="Records the tablet as seen; returns the server time and last accepted sequence.",
)
def scanner_ping(device: Device = Depends(get_device), db: Session = Depends(get_db)) -> dict:
    """Lightweight reachability probe used by the scanner to detect connectivity."""
    now = clock.now()
    device.last_seen_at = now
    db.commit()
    return {
        "ok": True,
        "server_time": now.isoformat(),
        "last_sequence": device.last_sequence,
        "device": {"id": str(device.id), "name": device.name},
    }


# PUBLIC_INTERFACE
@router.post(
    "/scanner/status",
    tags=["scanning"],
    summary="Report scanner queue status",
    description="Stores the tablet's pending and failed scan counts for the supervisor sync view.",
)
def scanner_status(
    body: ScannerStatusIn,
    device: Device = Depends(get_device),
    db: Session = Depends(get_db),
) -> dict:
    """Persist the queue summary reported by the scanner."""
    now = clock.now()
    device.last_seen_at = now
    device.reported_pending = body.pending
    device.reported_failed = body.failed
    device.reported_oldest_pending_at = body.oldest_pending_at if body.pending else None
    db.commit()
    return {"ok": True, "server_time": now.isoformat()}

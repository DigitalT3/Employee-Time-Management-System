"""Pydantic request/response models for the Employee Time Management API."""
import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginIn(BaseModel):
    """Staff login credentials."""

    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class UserOut(BaseModel):
    """Authenticated staff user."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    role: str


class MeOut(UserOut):
    """Authenticated staff user together with the permissions granted to the role."""

    permissions: list[str] = Field(default_factory=list, description="Permission keys granted to the role")


class EmployeeCreate(BaseModel):
    """Employee creation request."""

    employee_number: str = Field(..., min_length=1, max_length=32)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    site_ids: list[uuid.UUID] = Field(..., min_length=1)

    @field_validator("employee_number", "first_name", "last_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        """Reject blank values after trimming whitespace."""
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class EmployeeUpdate(BaseModel):
    """Partial employee update request."""

    employee_number: str | None = Field(None, min_length=1, max_length=32)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    site_ids: list[uuid.UUID] | None = Field(None, min_length=1)


class SiteRef(BaseModel):
    """Compact site reference."""

    id: uuid.UUID
    code: str
    name: str


class EmployeeOut(BaseModel):
    """Employee response excluding the secret QR token."""

    id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    is_active: bool
    site_ids: list[uuid.UUID]
    sites: list[SiteRef] = Field(default_factory=list)
    credential_id: uuid.UUID | None = Field(None, description="Current (active or blocked) credential")
    credential_status: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeStatusIn(BaseModel):
    """Employee activation request."""

    is_active: bool


class CredentialAction(BaseModel):
    """Optional reason recorded in the audit entry of a credential lifecycle action."""

    reason: str | None = Field(None, max_length=500)


class CredentialOut(BaseModel):
    """QR credential metadata. The secret token is never part of this model."""

    id: uuid.UUID
    employee_id: uuid.UUID
    status: str
    is_current: bool
    issued_at: datetime
    blocked_at: datetime | None = None
    revoked_at: datetime | None = None


class QrInfoOut(CredentialOut):
    """Credential metadata with download links for the current credential."""

    png_url: str | None = None
    pdf_url: str | None = None


class SiteCreate(BaseModel):
    """Site creation request."""

    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=200)
    timezone: str = Field("Europe/Amsterdam", max_length=64)


class SiteUpdate(BaseModel):
    """Partial site update request."""

    name: str | None = Field(None, min_length=1, max_length=200)
    timezone: str | None = Field(None, max_length=64)
    is_active: bool | None = None


class SiteOut(BaseModel):
    """Site response."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    timezone: str
    is_active: bool


class SiteSettingsIO(BaseModel):
    """Per-site attendance policy."""

    model_config = ConfigDict(from_attributes=True)
    duplicate_window_seconds: int = Field(..., ge=0, le=3600)
    missing_out_cutoff_time: time


class GateCreate(BaseModel):
    """Gate creation request."""

    name: str = Field(..., min_length=1, max_length=200)


class GateCreateFlat(GateCreate):
    """Gate creation request carrying its site id (flat /gates route)."""

    site_id: uuid.UUID


class GateUpdate(BaseModel):
    """Partial gate update request."""

    name: str | None = Field(None, min_length=1, max_length=200)
    is_active: bool | None = None


class GateOut(BaseModel):
    """Gate response."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    is_active: bool


class DeviceCreate(BaseModel):
    """Scanner-device registration request."""

    name: str = Field(..., min_length=1, max_length=100)
    gate_id: uuid.UUID


class DeviceOut(BaseModel):
    """Scanner-device response without its secret token."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    site_id: uuid.UUID
    gate_id: uuid.UUID
    last_sequence: int
    is_active: bool


class DeviceCreated(DeviceOut):
    """New scanner-device response that exposes its token once."""

    device_token: str


class DeviceUpdate(BaseModel):
    """Scanner-device state update."""

    is_active: bool


class ScanIn(BaseModel):
    """One QR capture submitted from a scanner device."""

    client_uuid: uuid.UUID
    device_sequence: int = Field(..., ge=1)
    token: str = Field(..., min_length=1, max_length=512)
    captured_at: datetime | None = None
    capture_mode: Literal["online", "offline"] = "online"
    tentative_direction: Literal["IN", "OUT"] | None = Field(
        None, description="Tablet's offline guess; never used to decide direction, only to report a mismatch"
    )


class SyncIn(BaseModel):
    """Offline scan synchronization batch."""

    items: list[ScanIn] = Field(..., min_length=1, max_length=500)


class CorrectionIn(BaseModel):
    """Supervisor correction request for an attendance session."""

    field: Literal["in", "out"]
    new_value: datetime
    reason: str = Field(..., min_length=1, max_length=1000)
    expected_version: int = Field(..., ge=1)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        """Require a non-whitespace correction reason."""
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class CorrectionCreate(CorrectionIn):
    """Correction request for the global corrections route (session id in the body)."""

    session_id: uuid.UUID


class ScannerStatusIn(BaseModel):
    """Heartbeat reported by a scanner tablet."""

    pending: int = Field(0, ge=0, description="Scans waiting for synchronisation")
    failed: int = Field(0, ge=0, description="Scans whose last synchronisation attempt failed")
    oldest_pending_at: datetime | None = None


class PermissionMatrixIn(BaseModel):
    """Permission matrix update: role -> permission key -> allowed (partial updates allowed)."""

    matrix: dict[str, dict[str, bool]]


class PermissionMatrixOut(BaseModel):
    """Effective permission matrix with catalogue and locked entries."""

    roles: list[str]
    permissions: list[dict[str, str]]
    matrix: dict[str, dict[str, bool]]
    locked: list[dict[str, str]]

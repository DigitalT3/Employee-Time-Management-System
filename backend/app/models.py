"""SQLAlchemy 2 declarative models. Migration 0001_initial is the schema authority."""
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, Time, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all models."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Site(Base):
    """Physical site."""
    __tablename__ = "sites"
    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Amsterdam")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Gate(Base):
    """Gate within a site."""
    __tablename__ = "gates"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_gates_site_name"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class SiteSettings(Base):
    """Per-site attendance policy (DEC-05, DEC-06)."""
    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("duplicate_window_seconds BETWEEN 0 AND 3600", name="ck_site_settings_window"),
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    duplicate_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="120")
    missing_out_cutoff_time: Mapped[time] = mapped_column(Time, nullable=False, server_default="06:00")


class Employee(Base):
    """Employee (synthetic data only)."""
    __tablename__ = "employees"
    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmployeeSite(Base):
    """Employee-to-site assignment."""
    __tablename__ = "employee_sites"
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), primary_key=True)


class QrCredential(Base):
    """QR credential with immutable historical rows after revocation."""
    __tablename__ = "qr_credentials"
    __table_args__ = (
        CheckConstraint("status IN ('active','blocked','revoked')", name="ck_qr_credentials_status"),
        Index(
            "uq_qr_credentials_current_per_employee",
            "employee_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'blocked')"),
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    issued_at: Mapped[datetime] = _now()
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    """Staff user account."""
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','supervisor','hr')", name="ck_users_role"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class UserSession(Base):
    """Opaque login session; id is the hash of the cookie token."""
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Device(Base):
    """Scanner tablet bound to one site/gate."""
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_pending: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reported_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reported_oldest_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceEvent(Base):
    """Immutable raw scan event."""
    __tablename__ = "attendance_events"
    __table_args__ = (
        CheckConstraint("direction IN ('IN','OUT')", name="ck_attendance_events_direction"),
        CheckConstraint("capture_mode IN ('online','offline')", name="ck_attendance_events_capture_mode"),
        Index("ix_attendance_events_site_occurred", "site_id", "occurred_at"),
        Index("ix_attendance_events_employee_occurred", "employee_id", "occurred_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    gate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = _now()
    capture_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)


class ScanRequest(Base):
    """Idempotency record for every scan submission (replay/conflict detection)."""
    __tablename__ = "scan_requests"
    __table_args__ = (
        UniqueConstraint("device_id", "device_sequence", name="uq_scan_requests_device_seq"),
        CheckConstraint(
            "capture_mode IS NULL OR capture_mode IN ('online','offline')",
            name="ck_scan_requests_capture_mode",
        ),
        Index("ix_scan_requests_outcome_received", "outcome", "received_at"),
    )
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    device_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attendance_events.id", ondelete="RESTRICT"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(String(64))
    capture_mode: Mapped[str | None] = mapped_column(String(8))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = _now()


class AttendanceSession(Base):
    """IN/OUT pair with effective (possibly corrected) times."""
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        Index(
            "uq_attendance_sessions_open", "employee_id", "site_id",
            unique=True, postgresql_where=text("effective_out IS NULL"),
        ),
        CheckConstraint("effective_out IS NULL OR effective_out > effective_in", name="ck_attendance_sessions_order"),
        Index("ix_attendance_sessions_shift_date", "shift_date"),
        Index("ix_attendance_sessions_employee_shift", "employee_id", "shift_date"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    in_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    out_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="RESTRICT"), unique=True
    )
    effective_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class AttendanceCorrection(Base):
    """Append-only supervisor correction (DEC-08)."""
    __tablename__ = "attendance_corrections"
    __table_args__ = (
        CheckConstraint("field IN ('in','out')", name="ck_attendance_corrections_field"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_attendance_corrections_reason"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(3), nullable=False)
    old_value: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_value: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = _now()


class AuditLog(Base):
    """Append-only audit trail."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity_type", "entity_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _now()


class LoginAttempt(Base):
    """Persisted login attempt used by the authentication throttle."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_username_attempted", "username", "attempted_at"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    attempted_at: Mapped[datetime] = _now()


class RolePermission(Base):
    """Configurable permission setting for one staff role."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        CheckConstraint("role IN ('admin','supervisor','hr')", name="ck_role_permissions_role"),
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    updated_at: Mapped[datetime] = _now()
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

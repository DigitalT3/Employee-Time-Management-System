"""Initial schema for the Employee Time Management System.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _pk():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _ts(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.func.now())


def _true(name="is_active"):
    return sa.Column(name, sa.Boolean, nullable=False, server_default=sa.true())


def upgrade() -> None:
    op.create_table(
        "sites", _pk(),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Amsterdam"),
        _true(),
    )
    op.create_table(
        "gates", _pk(),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        _true(),
        sa.UniqueConstraint("site_id", "name", name="uq_gates_site_name"),
    )
    op.create_table(
        "site_settings",
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("duplicate_window_seconds", sa.Integer, nullable=False, server_default="120"),
        sa.Column("missing_out_cutoff_time", sa.Time, nullable=False, server_default="06:00"),
        sa.CheckConstraint("duplicate_window_seconds BETWEEN 0 AND 3600", name="ck_site_settings_window"),
    )
    op.create_table(
        "employees", _pk(),
        sa.Column("employee_number", sa.String(32), nullable=False, unique=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        _true(), _ts("created_at"), _ts("updated_at"),
    )
    op.create_table(
        "employee_sites",
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), primary_key=True),
    )
    op.create_table(
        "qr_credentials", _pk(),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="RESTRICT"),
                  nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_encrypted", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _ts("issued_at"),
        sa.CheckConstraint("status IN ('active','blocked','revoked')", name="ck_qr_credentials_status"),
    )
    op.create_table(
        "users", _pk(),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        _true(),
        sa.CheckConstraint("role IN ('admin','supervisor','hr')", name="ck_users_role"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "devices", _pk(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("gate_id", UUID(as_uuid=True), sa.ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("last_sequence", sa.BigInteger, nullable=False, server_default="0"),
        _true(),
    )
    op.create_table(
        "attendance_events", _pk(),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("gate_id", UUID(as_uuid=True), sa.ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _ts("received_at"),
        sa.Column("capture_mode", sa.String(8), nullable=False),
        sa.Column("client_uuid", UUID(as_uuid=True), nullable=False, unique=True),
        sa.CheckConstraint("direction IN ('IN','OUT')", name="ck_attendance_events_direction"),
        sa.CheckConstraint("capture_mode IN ('online','offline')", name="ck_attendance_events_capture_mode"),
    )
    op.create_index("ix_attendance_events_site_occurred", "attendance_events", ["site_id", "occurred_at"])
    op.create_index("ix_attendance_events_employee_occurred", "attendance_events", ["employee_id", "occurred_at"])
    op.create_table(
        "scan_requests",
        sa.Column("client_uuid", UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_sequence", sa.BigInteger, nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("attendance_events.id", ondelete="RESTRICT")),
        sa.Column("response", JSONB, nullable=False),
        _ts("received_at"),
        sa.UniqueConstraint("device_id", "device_sequence", name="uq_scan_requests_device_seq"),
    )
    op.create_table(
        "attendance_sessions", _pk(),
        sa.Column("employee_id", UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("in_event_id", UUID(as_uuid=True), sa.ForeignKey("attendance_events.id", ondelete="RESTRICT"),
                  nullable=False, unique=True),
        sa.Column("out_event_id", UUID(as_uuid=True), sa.ForeignKey("attendance_events.id", ondelete="RESTRICT"),
                  unique=True),
        sa.Column("effective_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_out", sa.DateTime(timezone=True)),
        sa.Column("shift_date", sa.Date, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint("effective_out IS NULL OR effective_out > effective_in", name="ck_attendance_sessions_order"),
    )
    # At most one open session per employee per site (R-04).
    op.create_index(
        "uq_attendance_sessions_open", "attendance_sessions", ["employee_id", "site_id"],
        unique=True, postgresql_where=sa.text("effective_out IS NULL"),
    )
    op.create_table(
        "attendance_corrections", _pk(),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("field", sa.String(3), nullable=False),
        sa.Column("old_value", sa.DateTime(timezone=True)),
        sa.Column("new_value", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        _ts("created_at"),
        sa.CheckConstraint("field IN ('in','out')", name="ck_attendance_corrections_field"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_attendance_corrections_reason"),
    )
    op.create_index("ix_attendance_corrections_session_id", "attendance_corrections", ["session_id"])
    op.create_table(
        "audit_log", _pk(),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])


def downgrade() -> None:
    for table in (
        "audit_log", "attendance_corrections", "attendance_sessions", "scan_requests",
        "attendance_events", "devices", "user_sessions", "users", "qr_credentials",
        "employee_sites", "employees", "site_settings", "gates", "sites",
    ):
        op.drop_table(table)

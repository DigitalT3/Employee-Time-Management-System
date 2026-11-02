"""Gap remediation schema foundations.

Revision ID: 0002_gap_remediation
Revises: 0001_initial
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002_gap_remediation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_LEGACY_UNIQUE = "qr_credentials_employee_id_key"
_CURRENT_CREDENTIAL_INDEX = "uq_qr_credentials_current_per_employee"


def _existing_indexes(table: str) -> set[str]:
    """Return the current index names for a table."""
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_absent(name: str, table: str, columns: list[str]) -> None:
    """Create a non-unique index only when this revision has not already created it."""
    if name not in _existing_indexes(table):
        op.create_index(name, table, columns)


def _employee_id_unique_constraints() -> list[str]:
    """Return QR credential unique constraints that enforce one row per employee."""
    return [
        item["name"]
        for item in sa.inspect(op.get_bind()).get_unique_constraints("qr_credentials")
        if item["column_names"] == ["employee_id"]
    ]


def upgrade() -> None:
    """Apply STEP-01 schema foundations transactionally."""
    # Credential history: preserve revoked rows while allowing a replacement.
    for name in _employee_id_unique_constraints():
        op.drop_constraint(name, "qr_credentials", type_="unique")
    op.add_column("qr_credentials", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("qr_credentials", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        _CURRENT_CREDENTIAL_INDEX,
        "qr_credentials",
        ["employee_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'blocked')"),
    )

    # Scanner device heartbeat state.
    op.add_column("devices", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("reported_pending", sa.Integer, nullable=False, server_default="0"))
    op.add_column("devices", sa.Column("reported_failed", sa.Integer, nullable=False, server_default="0"))
    op.add_column(
        "devices",
        sa.Column("reported_oldest_pending_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Operational scan log fields. All are nullable for pre-existing requests.
    op.add_column(
        "scan_requests",
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("scan_requests", sa.Column("reason", sa.String(64), nullable=True))
    op.add_column("scan_requests", sa.Column("capture_mode", sa.String(8), nullable=True))
    op.add_column("scan_requests", sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scan_requests", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_scan_requests_capture_mode",
        "scan_requests",
        "capture_mode IS NULL OR capture_mode IN ('online', 'offline')",
    )
    op.create_index("ix_scan_requests_outcome_received", "scan_requests", ["outcome", "received_at"])

    # Reporting indexes; existing indexes are intentionally not recreated.
    _create_index_if_absent("ix_attendance_sessions_shift_date", "attendance_sessions", ["shift_date"])
    _create_index_if_absent(
        "ix_attendance_sessions_employee_shift",
        "attendance_sessions",
        ["employee_id", "shift_date"],
    )
    _create_index_if_absent(
        "ix_attendance_events_site_occurred",
        "attendance_events",
        ["site_id", "occurred_at"],
    )

    # Persistent login-attempt history for the STEP-02 throttle implementation.
    op.create_table(
        "login_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("succeeded", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_login_attempts_username_attempted", "login_attempts", ["username", "attempted_at"])

    # Database-backed permissions for STEP-02's configurable role matrix.
    op.create_table(
        "role_permissions",
        sa.Column("role", sa.String(16), primary_key=True),
        sa.Column("permission", sa.String(64), primary_key=True),
        sa.Column("allowed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("role IN ('admin', 'supervisor', 'hr')", name="ck_role_permissions_role"),
    )


def downgrade() -> None:
    """Revert STEP-01 unless credential history would be destroyed."""
    multi_credential_employee_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT employee_id FROM qr_credentials "
            "GROUP BY employee_id HAVING count(*) > 1"
            ") AS employees_with_history"
        )
    ).scalar_one()
    if multi_credential_employee_count:
        raise RuntimeError(
            "Cannot downgrade 0002_gap_remediation because "
            f"{multi_credential_employee_count} employee(s) have credential history. "
            "Resolve the history manually before restoring the old one-credential constraint."
        )

    op.drop_table("role_permissions")
    op.drop_index("ix_login_attempts_username_attempted", table_name="login_attempts")
    op.drop_table("login_attempts")

    op.drop_index("ix_attendance_sessions_employee_shift", table_name="attendance_sessions")
    op.drop_index("ix_attendance_sessions_shift_date", table_name="attendance_sessions")

    op.drop_index("ix_scan_requests_outcome_received", table_name="scan_requests")
    op.drop_constraint("ck_scan_requests_capture_mode", "scan_requests", type_="check")
    for column in ("occurred_at", "captured_at", "capture_mode", "reason", "employee_id"):
        op.drop_column("scan_requests", column)

    for column in (
        "reported_oldest_pending_at",
        "reported_failed",
        "reported_pending",
        "last_seen_at",
    ):
        op.drop_column("devices", column)

    op.drop_index(_CURRENT_CREDENTIAL_INDEX, table_name="qr_credentials")
    op.drop_column("qr_credentials", "revoked_at")
    op.drop_column("qr_credentials", "blocked_at")
    op.create_unique_constraint(_LEGACY_UNIQUE, "qr_credentials", ["employee_id"])

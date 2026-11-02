"""Synthetic local seed profiles.

Run from ``backend`` with ``python -m app.seed --profile base`` or
``python -m app.seed --profile demo``. The command only runs in dev or test.
Account passwords come exclusively from the SEED_*_PASSWORD environment values
(generated into backend/.env by scripts/gen_env.sh); there are no defaults.
"""
import argparse
import sys
import uuid
from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.crypto import new_token, token_hash
from app.db import SessionLocal
from app.models import (
    AttendanceEvent,
    AttendanceSession,
    Device,
    Employee,
    EmployeeSite,
    Gate,
    Site,
    SiteSettings,
    User,
)
from app.schemas import CorrectionIn, ScanIn
from app.security import hash_password
from app.services.attendance import process_scan
from app.services.corrections import apply_correction
from app.services.credentials import credential_payload, current_credential, issue_credential

_BASE_EMPLOYEE = ("EMP-001", "Alex", "Morgan", True)
_DEMO_EMPLOYEES = (
    ("EMP-002", "Jamie", "Taylor", True),
    ("EMP-003", "Sam", "Wilson", True),
    ("EMP-004", "Taylor", "Brown", True),
    ("EMP-005", "Jordan", "Lee", False),
)
_PASSWORD_SETTINGS = ("SEED_ADMIN_PASSWORD", "SEED_SUPERVISOR_PASSWORD", "SEED_HR_PASSWORD")


class SeedConfigError(RuntimeError):
    """Raised when required seed configuration is missing."""


def missing_seed_passwords() -> list[str]:
    """Return the names of SEED_*_PASSWORD settings that have no value."""
    settings = get_settings()
    return [name for name in _PASSWORD_SETTINGS if not getattr(settings, name, None)]


def _get_or_create(db: Session, model: type, lookup: dict, **values: object) -> tuple[object, bool]:
    """Return an existing model row or persist a new one."""
    row = db.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup, **values)
        db.add(row)
        db.flush()
        return row, True
    return row, False


def _seed_employee(
    db: Session,
    site: Site,
    employee_number: str,
    first_name: str,
    last_name: str,
    is_active: bool,
    issue: bool,
) -> bool:
    """Create or update a synthetic employee, its site assignment and optional credential."""
    employee, created = _get_or_create(
        db,
        Employee,
        {"employee_number": employee_number},
        first_name=first_name,
        last_name=last_name,
        is_active=is_active,
    )
    _get_or_create(db, EmployeeSite, {"employee_id": employee.id, "site_id": site.id})
    if issue and current_credential(db, employee.id) is None:
        issue_credential(db, employee)
        db.flush()
    return created


def _local(tz: ZoneInfo, day, hour: int, minute: int = 0) -> datetime:
    """Return the UTC instant of a local wall-clock time on a given site-local date."""
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(timezone.utc)


def _scan_at(db: Session, device: Device, employee: Employee, at: datetime) -> dict:
    """Submit an online scan through the real scan service with the clock fixed at ``at``."""
    token = credential_payload(current_credential(db, employee.id))
    clock.set_now(lambda: at)
    db.refresh(device)
    item = ScanIn(client_uuid=uuid.uuid4(), device_sequence=device.last_sequence + 1,
                  token=token, capture_mode="online")
    return process_scan(db, device, item)[1]


def _seed_sample_sessions(db: Session, site: Site, device: Device, supervisor: User) -> int:
    """Create demo attendance (completed, corrected, missing-OUT, rejected) via the real services.

    Idempotent: nothing is created when attendance events already exist. Returns the
    number of scans submitted.
    """
    if db.scalar(select(AttendanceEvent.id).limit(1)) is not None:
        return 0
    tz = ZoneInfo(site.timezone)
    today = datetime.now(tz).date()
    yesterday, two_days_ago = today - timedelta(days=1), today - timedelta(days=2)
    by_number = {e.employee_number: e for e in db.scalars(select(Employee))}
    scans = 0
    try:
        # EMP-002: a normal completed session yesterday.
        _scan_at(db, device, by_number["EMP-002"], _local(tz, yesterday, 8, 0))
        _scan_at(db, device, by_number["EMP-002"], _local(tz, yesterday, 16, 30))
        # EMP-003: a session whose OUT was corrected by the supervisor.
        _scan_at(db, device, by_number["EMP-003"], _local(tz, yesterday, 8, 15))
        _scan_at(db, device, by_number["EMP-003"], _local(tz, yesterday, 16, 45))
        session = db.scalar(select(AttendanceSession).where(
            AttendanceSession.employee_id == by_number["EMP-003"].id))
        clock.set_now(lambda: _local(tz, yesterday, 17, 30))
        apply_correction(db, session.id, CorrectionIn(
            field="out", new_value=_local(tz, yesterday, 17, 0),
            reason="Demo: employee left later than the scan was recorded",
            expected_version=session.version), supervisor)
        # EMP-004: IN two days ago with no OUT (missing-OUT exception).
        _scan_at(db, device, by_number["EMP-004"], _local(tz, two_days_ago, 22, 0))
        # EMP-005 is inactive: its scan is rejected and shows in the scan log.
        _scan_at(db, device, by_number["EMP-005"], _local(tz, yesterday, 9, 0))
        scans = 6
    finally:
        clock.set_now(None)
    return scans


# PUBLIC_INTERFACE
def seed(db: Session, profile: str = "demo") -> dict[str, object]:
    """Seed the selected synthetic profile and return created counts and token metadata."""
    if profile not in {"base", "demo"}:
        raise ValueError("profile must be 'base' or 'demo'")
    missing = missing_seed_passwords()
    if missing:
        raise SeedConfigError(
            "Missing seed passwords: " + ", ".join(missing)
            + ". Run scripts/gen_env.sh to generate them in backend/.env."
        )

    settings = get_settings()
    created: dict[str, object] = {
        "users": 0, "employees": 0, "device_token": None, "profile": profile, "sample_scans": 0,
    }

    site, _ = _get_or_create(
        db,
        Site,
        {"code": "AMS-01"},
        name="Amsterdam Depot",
        timezone="Europe/Amsterdam",
    )
    gate, _ = _get_or_create(db, Gate, {"site_id": site.id, "name": "Main Gate"})
    _get_or_create(db, SiteSettings, {"site_id": site.id})

    users: dict[str, User] = {}
    for username, role, password in (
        ("admin", "admin", settings.SEED_ADMIN_PASSWORD),
        ("supervisor", "supervisor", settings.SEED_SUPERVISOR_PASSWORD),
        ("hr", "hr", settings.SEED_HR_PASSWORD),
    ):
        user, user_created = _get_or_create(
            db,
            User,
            {"username": username},
            role=role,
            password_hash=hash_password(password),
        )
        users[username] = user
        created["users"] = int(created["users"]) + int(user_created)

    device = db.scalar(select(Device).filter_by(name="Tablet-1"))
    if device is None:
        device_token = new_token()
        device = Device(
            name="Tablet-1",
            site_id=site.id,
            gate_id=gate.id,
            token_hash=token_hash(device_token),
        )
        db.add(device)
        db.flush()
        created["device_token"] = device_token

    # Alex is intentionally unregistered: Demonstration A registers EMP-001 through the UI.
    employee_specs: Iterable[tuple[str, str, str, bool]] = (_BASE_EMPLOYEE,)
    if profile == "demo":
        employee_specs = (*employee_specs, *_DEMO_EMPLOYEES)

    for number, first_name, last_name, is_active in employee_specs:
        employee_created = _seed_employee(
            db, site, number, first_name, last_name, is_active, issue=number != "EMP-001",
        )
        created["employees"] = int(created["employees"]) + int(employee_created)
    db.commit()

    if profile == "demo":
        created["sample_scans"] = _seed_sample_sessions(db, site, device, users["supervisor"])
    return created


# PUBLIC_INTERFACE
def main() -> int:
    """Run a requested seed profile only in development or test environments."""
    parser = argparse.ArgumentParser(description="Seed synthetic ETMS data.")
    parser.add_argument("--profile", choices=("base", "demo"), default="demo")
    args = parser.parse_args()

    environment = get_settings().APP_ENV
    if environment not in {"dev", "test"}:
        print(f"Refusing to seed: APP_ENV={environment!r} (allowed: dev, test)", file=sys.stderr)
        return 1
    missing = missing_seed_passwords()
    if missing:
        print(
            "Cannot seed: " + ", ".join(missing) + " not set. Run scripts/gen_env.sh to generate them.",
            file=sys.stderr,
        )
        return 1

    with SessionLocal() as db:
        result = seed(db, args.profile)

    print(
        "Seed complete: "
        f"profile={result['profile']}, users created={result['users']}, "
        f"employees created={result['employees']}, sample scans={result['sample_scans']}"
    )
    if result["device_token"]:
        print(f"Device 'Tablet-1' token (shown once): {result['device_token']}")
    print("Seed passwords were read from backend/.env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

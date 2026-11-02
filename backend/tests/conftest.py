"""Shared PostgreSQL integration-test fixtures for the FastAPI backend."""
import os
import uuid
from datetime import datetime, timezone

# This must precede all application imports so app.db selects TEST_DATABASE_URL.
os.environ.setdefault("APP_ENV", "test")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import clock
from app.crypto import encrypt_token, token_hash
from app.db import SessionLocal
from app.main import app
from app.models import Device, Employee, EmployeeSite, Gate, QrCredential, Site, SiteSettings, User
from app.security import hash_password

UTC = timezone.utc


class FakeClock:
    """Mutable timezone-aware clock used to exercise time-dependent attendance rules."""

    def __init__(self) -> None:
        self.t = datetime(2026, 3, 2, 7, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        """Return the currently configured test timestamp."""
        return self.t

    def set(self, value: datetime) -> None:
        """Set the current test timestamp to an aware UTC datetime."""
        assert value.tzinfo is not None
        self.t = value


class Scanner:
    """Small authenticated scanner client that generates unique idempotency fields."""

    def __init__(self, client: TestClient, device_token: str) -> None:
        self.client = client
        self.headers = {"X-Device-Token": device_token}
        self.sequence = 0

    def item(self, token: str, **overrides: object) -> dict:
        """Build a valid scan payload with a new client UUID and sequence."""
        self.sequence += 1
        return {
            "client_uuid": str(uuid.uuid4()),
            "device_sequence": self.sequence,
            "token": token,
            **overrides,
        }

    def scan(self, token: str, **overrides: object):
        """Submit one authenticated scan."""
        return self.client.post(
            "/api/attendance/scan",
            json=self.item(token, **overrides),
            headers=self.headers,
        )


@pytest.fixture(scope="session", autouse=True)
def migrate_test_database() -> None:
    """Migrate the configured etms_test database to the current Alembic revision."""
    config = Config("alembic.ini")
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def reset_database() -> None:
    """Remove test rows before every test without changing the migrated schema."""
    with SessionLocal.begin() as db:
        tables = ", ".join(
            table.name for table in reversed(__import__("app.models", fromlist=["Base"]).Base.metadata.sorted_tables)
        )
        db.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def fake_clock() -> FakeClock:
    """Install and later restore an injectable test clock."""
    value = FakeClock()
    clock.set_now(value)
    try:
        yield value
    finally:
        clock.set_now(None)


@pytest.fixture
def anon() -> TestClient:
    """Return an unauthenticated API client."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def world() -> dict:
    """Create isolated staff, site, gate, device, employee, and QR credential records."""
    qr_token = "test-permanent-qr-token"
    device_token = "test-scanner-device-token"

    with SessionLocal.begin() as db:
        admin = User(username="admin", password_hash=hash_password("admin-pass"), role="admin")
        supervisor = User(username="sup", password_hash=hash_password("supervisor-pass"), role="supervisor")
        hr = User(username="hr", password_hash=hash_password("hr-pass"), role="hr")
        site = Site(id=uuid.uuid4(), code="AMS", name="Amsterdam", timezone="Europe/Amsterdam")
        gate = Gate(id=uuid.uuid4(), site_id=site.id, name="Main Gate")
        device = Device(
            id=uuid.uuid4(),
            name="Tablet 1",
            site_id=site.id,
            gate_id=gate.id,
            token_hash=token_hash(device_token),
        )
        employee = Employee(
            id=uuid.uuid4(),
            employee_number="E-1",
            first_name="Ada",
            last_name="Lovelace",
        )
        credential = QrCredential(
            employee_id=employee.id,
            token_hash=token_hash(qr_token),
            token_encrypted=encrypt_token(qr_token),
        )
        # Models declare no ORM relationships, so flush parents before children
        # to satisfy foreign keys.
        db.add_all([admin, supervisor, hr, site, employee])
        db.flush()
        db.add(gate)
        db.flush()
        db.add_all(
            [
                SiteSettings(site_id=site.id, duplicate_window_seconds=120),
                device,
                EmployeeSite(employee_id=employee.id, site_id=site.id),
                credential,
            ]
        )

    return {
        "site": {"id": str(site.id), "code": site.code},
        "gate": {"id": str(gate.id), "name": gate.name},
        "employee": {"id": str(employee.id), "employee_number": employee.employee_number},
        "qr": qr_token,
        "device_token": device_token,
    }


def _authenticated_client(username: str, password: str) -> TestClient:
    """Create a client authenticated as one of the fixture staff accounts."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def admin(world: dict) -> TestClient:
    """Return an authenticated administrator client."""
    client = _authenticated_client("admin", "admin-pass")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def supervisor(world: dict) -> TestClient:
    """Return an authenticated supervisor client."""
    client = _authenticated_client("sup", "supervisor-pass")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def hr(world: dict) -> TestClient:
    """Return an authenticated HR client."""
    client = _authenticated_client("hr", "hr-pass")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def scanner(world: dict) -> Scanner:
    """Return an authenticated scanner client for the fixture device."""
    return Scanner(TestClient(app), world["device_token"])

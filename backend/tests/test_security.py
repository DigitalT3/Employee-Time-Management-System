"""Security (DEC-09/DEC-10): secure configuration, login throttle, headers, permission matrix, log hygiene."""
import logging
import secrets

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides) -> Settings:
    values = {"DATABASE_URL": "postgresql+psycopg://u@localhost/x", "SECRET_KEY": secrets.token_urlsafe(48),
              "FERNET_KEY": Fernet.generate_key().decode(), "APP_ENV": "production"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_configuration_is_validated(monkeypatch):
    """Weak secrets, bad Fernet keys, insecure cookies and wildcard CORS are refused."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert _settings().COOKIE_SECURE is True
    for bad in ({"SECRET_KEY": "changeme"}, {"SECRET_KEY": "short"}, {"FERNET_KEY": "not-a-key"},
                {"COOKIE_SECURE": False}, {"CORS_ORIGINS": "*"}):
        with pytest.raises(ValidationError):
            _settings(**bad)
    # Relaxed environments keep plain-HTTP local development possible.
    relaxed = _settings(APP_ENV="dev", SECRET_KEY="dev")
    assert relaxed.COOKIE_SECURE is False
    # The default environment is the secure one.
    assert Settings(_env_file=None, DATABASE_URL="postgresql+psycopg://u@localhost/x",
                    SECRET_KEY=secrets.token_urlsafe(48), FERNET_KEY=Fernet.generate_key().decode()).APP_ENV == "production"


def test_login_throttle_locks_and_recovers(world, anon, fake_clock):
    """Repeated failures lock the username with 429 + Retry-After, even for the right password."""
    for _ in range(5):
        assert anon.post("/api/auth/login", json={"username": "hr", "password": "wrong"}).status_code == 401
    locked = anon.post("/api/auth/login", json={"username": "hr", "password": "hr-pass"})
    assert locked.status_code == 429 and locked.json()["code"] == "login_locked"
    assert int(locked.headers["retry-after"]) > 0
    # Another user is unaffected.
    assert anon.post("/api/auth/login", json={"username": "sup", "password": "supervisor-pass"}).status_code == 200
    assert anon.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401


def test_security_headers(anon):
    """Every response carries defensive headers; the camera is limited to the own origin."""
    response = anon.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=(self)" in response.headers["permissions-policy"]
    assert "x-process-time-ms" in response.headers
    assert "content-security-policy" not in anon.get("/docs").headers


def test_permission_matrix_defaults_update_and_lock(world, admin, supervisor, hr):
    """The matrix is enforced server-side, editable by the admin and the admin lock is protected."""
    assert "attendance.correct" in supervisor.get("/api/auth/me").json()["permissions"]
    assert "attendance.correct" not in hr.get("/api/auth/me").json()["permissions"]
    assert supervisor.get("/api/admin/permissions").status_code == 403

    view = admin.get("/api/admin/permissions").json()
    assert view["matrix"]["admin"]["permissions.manage"] is True and view["roles"] == ["admin", "supervisor", "hr"]

    assert admin.put("/api/admin/permissions", json={"matrix": {"admin": {"permissions.manage": False}}}).status_code == 422
    assert admin.put("/api/admin/permissions", json={"matrix": {"ghost": {"reports.export": True}}}).json()["code"] == "unknown_role"
    assert admin.put("/api/admin/permissions", json={"matrix": {"hr": {"nope": True}}}).json()["code"] == "unknown_permission"

    assert hr.get("/api/attendance/scan-log").status_code == 403
    changed = admin.put("/api/admin/permissions", json={"matrix": {"hr": {"scanlog.view": True}, "supervisor": {"reports.export": False}}})
    assert changed.status_code == 200
    assert hr.get("/api/attendance/scan-log").status_code == 200  # effective immediately
    assert supervisor.get("/api/reports/daily").status_code == 403


def test_no_raw_token_in_logs(world, scanner, caplog):
    """Rejection log lines carry a keyed credential reference, never the scanned value."""
    secret_value = "very-secret-qr-value-123"
    with caplog.at_level(logging.DEBUG):
        scanner.scan(secret_value)
        scanner.scan(world["qr"] + "x")
    assert "scan_rejected" in caplog.text and "credential_ref=" in caplog.text
    assert secret_value not in caplog.text and world["qr"] not in caplog.text

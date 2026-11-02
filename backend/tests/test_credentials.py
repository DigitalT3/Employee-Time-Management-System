"""Credential lifecycle (DEC-02): block, unblock, revoke, re-issue; QR PNG round trip."""
import io

import pytest
from sqlalchemy import select

from app.api import employees
from app.db import SessionLocal
from app.models import AuditLog, Employee, QrCredential
from app.services.credentials import normalize_payload


def _decode(png: bytes) -> str:
    """Decode a QR PNG back to its payload (zxing-cpp is a test-only dependency)."""
    zxingcpp = pytest.importorskip("zxingcpp")
    from PIL import Image

    results = zxingcpp.read_barcodes(Image.open(io.BytesIO(png)))
    assert len(results) == 1
    return results[0].text


def _credential_id(admin, world) -> str:
    return admin.get(f"/api/employees/{world['employee']['id']}/qr").json()["id"]


def test_block_unblock_revoke_and_reissue(world, scanner, admin, supervisor, fake_clock):
    """Blocked and revoked credentials are rejected; re-issue creates exactly one new current one."""
    employee_id = world["employee"]["id"]
    credential_id = _credential_id(admin, world)

    assert admin.patch(f"/api/qr-credentials/{credential_id}/block", json={"reason": "lost"}).json()["status"] == "blocked"
    assert admin.get(f"/api/employees/{employee_id}").json()["credential_status"] == "blocked"
    assert scanner.scan(world["qr"]).json()["reason"] == "blocked"
    # Blocking twice is an invalid transition.
    assert admin.patch(f"/api/qr-credentials/{credential_id}/block").status_code == 409

    assert admin.patch(f"/api/qr-credentials/{credential_id}/unblock").json()["status"] == "active"
    fake_clock.set(fake_clock.t.replace(hour=8))
    assert scanner.scan(world["qr"]).status_code == 201

    # Only users with credentials.manage may change the lifecycle.
    assert supervisor.patch(f"/api/qr-credentials/{credential_id}/revoke").status_code == 403
    assert admin.patch(f"/api/qr-credentials/{credential_id}/revoke").json()["status"] == "revoked"
    assert admin.patch(f"/api/qr-credentials/{credential_id}/unblock").status_code == 409
    revoked_scan = scanner.scan(world["qr"]).json()
    assert revoked_scan["reason"] == "revoked" and revoked_scan["employee"] is None

    # Revoked employee: downloads give a clear 409, not a stale QR.
    assert admin.get(f"/api/employees/{employee_id}").json()["credential_status"] == "revoked"
    gone = admin.get(f"/api/employees/{employee_id}/qr.png")
    assert gone.status_code == 409 and gone.json()["code"] == "credential_revoked"

    reissued = admin.post(f"/api/employees/{employee_id}/qr/reissue", json={"reason": "replacement"})
    assert reissued.status_code == 201, reissued.text
    assert admin.post(f"/api/employees/{employee_id}/qr/reissue").json()["code"] == "credential_exists"

    new_payload = normalize_payload(_decode(admin.get(f"/api/employees/{employee_id}/qr.png").content))
    assert new_payload != world["qr"]
    fake_clock.set(fake_clock.t.replace(hour=12))
    assert scanner.scan(new_payload).status_code == 201
    # The old token stays revoked.
    assert scanner.scan(world["qr"]).json()["reason"] == "revoked"

    history = admin.get(f"/api/employees/{employee_id}/credentials").json()
    assert [c["status"] for c in history] == ["revoked", "active"]
    assert [c["is_current"] for c in history] == [False, True]
    assert "token" not in history[0]

    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.action.like("credential.%"))))
        rows = list(db.scalars(select(QrCredential).where(QrCredential.employee_id == employee_id)))
    assert {"credential.block", "credential.unblock", "credential.revoke", "credential.reissue"} <= actions
    assert len(rows) == 2


def test_reprint_returns_same_qr(world, admin):
    """Reprint and repeated PNG downloads show the unchanged permanent payload."""
    employee_id = world["employee"]["id"]
    first = admin.get(f"/api/employees/{employee_id}/qr.png").content
    assert normalize_payload(_decode(first)) == world["qr"]
    reprint = admin.post(f"/api/employees/{employee_id}/qr/reprint")
    assert reprint.status_code == 200
    assert admin.get(f"/api/employees/{employee_id}/qr.png").content == first
    assert world["qr"] not in reprint.text


def test_employee_creation_rolls_back_when_credential_issue_fails(world, admin, monkeypatch):
    """Employee creation remains atomic when permanent credential issuance raises an exception."""
    employee_number = "ATOMIC-FAIL"

    def fail_issue(*_args, **_kwargs):
        raise RuntimeError("credential generator unavailable")

    monkeypatch.setattr(employees, "issue_credential", fail_issue)
    with pytest.raises(RuntimeError, match="credential generator unavailable"):
        admin.post(
            "/api/employees",
            json={
                "employee_number": employee_number,
                "first_name": "Atomic",
                "last_name": "Failure",
                "site_ids": [world["site"]["id"]],
            },
        )

    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.employee_number == employee_number))
        credential_count = len(list(db.scalars(select(QrCredential))))
    assert employee is None
    # The fixture's one pre-existing credential is the only remaining row.
    assert credential_count == 1


def test_bulk_employee_creation_issues_25_unique_credentials(world, admin):
    """Every created employee receives one unique persistent credential without exposing its token."""
    employee_ids: list[str] = []
    for number in range(25):
        response = admin.post(
            "/api/employees",
            json={
                "employee_number": f"UNIQUE-{number:02d}",
                "first_name": "Unique",
                "last_name": f"Employee{number:02d}",
                "site_ids": [world["site"]["id"]],
            },
        )
        assert response.status_code == 201, response.text
        employee_ids.append(response.json()["id"])

    with SessionLocal() as db:
        credentials = list(
            db.scalars(
                select(QrCredential)
                .join(Employee, Employee.id == QrCredential.employee_id)
                .where(Employee.employee_number.like("UNIQUE-%"))
            )
        )

    assert len(employee_ids) == 25
    assert len(credentials) == 25
    assert len({credential.employee_id for credential in credentials}) == 25
    assert len({credential.token_hash for credential in credentials}) == 25
    assert all(credential.status == "active" for credential in credentials)

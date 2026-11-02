"""VAL-02: employee lifecycle, site assignment, and permanent QR reprints."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import QrCredential


def test_employee_creation_lifecycle_and_permanent_qr(world, admin, supervisor):
    """Creation atomically issues one credential, and reprints do not rotate it."""
    payload = {
        "employee_number": "E-2",
        "first_name": "Grace",
        "last_name": "Hopper",
        "site_ids": [world["site"]["id"]],
    }
    created = admin.post("/api/employees", json=payload)
    assert created.status_code == 201, created.text
    employee = created.json()
    assert employee["credential_status"] == "active"
    assert employee["site_ids"] == [world["site"]["id"]]

    assert admin.post("/api/employees", json=payload).status_code == 409
    assert supervisor.post("/api/employees", json=payload).status_code == 403

    first_png = admin.get(f"/api/employees/{employee['id']}/qr.png")
    second_png = admin.get(f"/api/employees/{employee['id']}/qr.png")
    pdf = admin.get(f"/api/employees/{employee['id']}/qr.pdf")
    assert first_png.status_code == 200
    assert first_png.headers["cache-control"] == "no-store"
    assert first_png.content == second_png.content
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    assert admin.post(f"/api/employees/{employee['id']}/deactivate").json()["is_active"] is False
    assert admin.post(f"/api/employees/{employee['id']}/activate").json()["is_active"] is True
    updated = admin.patch(
        f"/api/employees/{employee['id']}",
        json={"first_name": "Rear Admiral", "site_ids": [world["site"]["id"]]},
    )
    assert updated.status_code == 200
    assert updated.json()["first_name"] == "Rear Admiral"

    with SessionLocal() as db:
        credentials = list(
            db.scalars(select(QrCredential).where(QrCredential.employee_id == employee["id"]))
        )
    assert len(credentials) == 1


def test_employee_filters_and_site_validation(world, admin):
    """Lists honor supported filters and creation rejects an unknown site."""
    assert admin.get("/api/employees", params={"search": "Ada"}).json()[0]["employee_number"] == "E-1"
    assert admin.get("/api/employees", params={"active": True}).status_code == 200
    invalid = admin.post(
        "/api/employees",
        json={
            "employee_number": "E-invalid",
            "first_name": "Invalid",
            "last_name": "Site",
            "site_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "unknown_site"

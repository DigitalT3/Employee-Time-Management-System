"""Concurrent attendance-transition and rejected-retry regression tests (STEP-03)."""
import threading
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.crypto import token_hash
from app.db import SessionLocal
from app.models import AttendanceEvent, Device
from app.schemas import ScanIn
from app.services.attendance import process_scan


def _event_count() -> int:
    """Return the persisted attendance event count for the current test database."""
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AttendanceEvent))


def test_cross_device_concurrent_out_creates_one_transition(world, scanner, fake_clock):
    """Two devices closing one session concurrently produce one OUT and one duplicate response."""
    first_scan = scanner.scan(world["qr"])
    assert first_scan.status_code == 201
    fake_clock.set(fake_clock.t + timedelta(seconds=121))

    with SessionLocal.begin() as db:
        first_device = db.scalar(
            select(Device).where(Device.token_hash == token_hash(world["device_token"]))
        )
        second_device = Device(
            id=uuid.uuid4(),
            name="Tablet 2",
            site_id=first_device.site_id,
            gate_id=first_device.gate_id,
            token_hash=token_hash("second-device-token"),
        )
        db.add(second_device)
        db.flush()
        first_device_id = first_device.id
        second_device_id = second_device.id

    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def scan_from_device(device_id: uuid.UUID, sequence: int) -> None:
        with SessionLocal() as db:
            device = db.get(Device, device_id)
            barrier.wait()
            _, result = process_scan(
                db,
                device,
                ScanIn(
                    client_uuid=uuid.uuid4(),
                    device_sequence=sequence,
                    token=world["qr"],
                ),
            )
            outcomes.append(result["outcome"])

    threads = [
        threading.Thread(target=scan_from_device, args=(first_device_id, 2)),
        threading.Thread(target=scan_from_device, args=(second_device_id, 1)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["accepted", "duplicate"]
    assert _event_count() == 2


def test_rejected_request_replays_until_a_fresh_request_is_sent(world, scanner, admin):
    """A rejected idempotency key is stable, while a fresh request succeeds after remediation."""
    credential_id = admin.get(
        f"/api/employees/{world['employee']['id']}/qr"
    ).json()["id"]
    assert admin.patch(f"/api/qr-credentials/{credential_id}/block").status_code == 200

    rejected_item = scanner.item(world["qr"])
    rejected = scanner.client.post(
        "/api/attendance/scan",
        json=rejected_item,
        headers=scanner.headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["outcome"] == "rejected"
    assert rejected.json()["reason"] == "blocked"
    assert _event_count() == 0

    assert admin.patch(f"/api/qr-credentials/{credential_id}/unblock").status_code == 200
    replay = scanner.client.post(
        "/api/attendance/scan",
        json=rejected_item,
        headers=scanner.headers,
    )
    assert replay.status_code == 200
    assert replay.json()["outcome"] == "replay"
    assert replay.json()["original_outcome"] == "rejected"
    assert _event_count() == 0

    accepted = scanner.scan(world["qr"])
    assert accepted.status_code == 201
    assert accepted.json()["outcome"] == "accepted"
    assert accepted.json()["direction"] == "IN"
    assert _event_count() == 1

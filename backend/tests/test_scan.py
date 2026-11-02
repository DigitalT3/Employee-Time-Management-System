"""VAL-03/VAL-04: scan direction, validation, idempotency, concurrency, and offline sync."""
import threading
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AttendanceEvent, AttendanceSession, Device
from app.schemas import ScanIn
from app.services.attendance import process_scan


def _events():
    """Return the number of persisted attendance events."""
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AttendanceEvent))


def test_in_out_toggle_and_duplicate_window(world, scanner, fake_clock):
    """A first scan is IN, duplicate-window scans do not create events, then OUT follows."""
    accepted = scanner.scan(world["qr"])
    assert accepted.status_code == 201 and accepted.json()["direction"] == "IN"
    # DEC-03: the scanner result carries the employee name only, never the employee number.
    assert accepted.json()["employee"] == {"name": "Ada Lovelace"}
    assert world["qr"] not in accepted.text

    fake_clock.set(fake_clock.t + timedelta(seconds=119))
    duplicate = scanner.scan(world["qr"])
    assert duplicate.status_code == 200 and duplicate.json()["outcome"] == "duplicate"

    fake_clock.set(fake_clock.t + timedelta(seconds=1))
    outgoing = scanner.scan(world["qr"])
    assert outgoing.status_code == 201 and outgoing.json()["direction"] == "OUT"

    fake_clock.set(fake_clock.t + timedelta(hours=1))
    assert scanner.scan("ETMS:" + world["qr"]).json()["direction"] == "IN"
    assert _events() == 3


def test_rejections_create_no_event(world, scanner, admin):
    """Invalid credentials, wrong-site assignments, and inactive employees are rejected."""
    assert scanner.scan("nope").json()["reason"] == "unknown_credential"
    assert scanner.scan("nope").json()["employee"] is None
    other = admin.post("/api/sites", json={"code": "OTH", "name": "Other"}).json()

    admin.patch(
        f"/api/employees/{world['employee']['id']}",
        json={"site_ids": [other["id"]]},
    )
    assert scanner.scan(world["qr"]).json()["reason"] == "wrong_site"

    admin.patch(
        f"/api/employees/{world['employee']['id']}",
        json={"site_ids": [world["site"]["id"]]},
    )
    admin.post(f"/api/employees/{world['employee']['id']}/deactivate")
    assert scanner.scan(world["qr"]).json()["reason"] == "inactive_employee"
    assert _events() == 0

    response = scanner.client.post(
        "/api/attendance/scan",
        json=scanner.item(world["qr"]),
        headers={"X-Device-Token": "bad"},
    )
    assert response.status_code == 401


def test_replay_and_conflict(world, scanner):
    """Exact replays return the stored result; changed UUID or sequence data conflicts."""
    item = scanner.item(world["qr"])
    first = scanner.client.post("/api/attendance/scan", json=item, headers=scanner.headers)
    replay = scanner.client.post("/api/attendance/scan", json=item, headers=scanner.headers)
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["outcome"] == "replay"
    assert replay.json()["event_id"] == first.json()["event_id"]

    changed = {**item, "token": "different"}
    assert scanner.client.post(
        "/api/attendance/scan", json=changed, headers=scanner.headers
    ).status_code == 409

    sequence_reused = {**item, "client_uuid": str(uuid.uuid4())}
    response = scanner.client.post(
        "/api/attendance/scan", json=sequence_reused, headers=scanner.headers
    )
    assert response.json()["reason"] == "device_sequence_reused"
    assert _events() == 1

    with SessionLocal() as db:
        assert db.scalar(select(Device.last_sequence)) == item["device_sequence"]


def test_concurrent_first_scans_create_one_event(world):
    """Employee-row locking serializes concurrent first scans into one accepted event."""
    with SessionLocal() as db:
        device = db.scalar(select(Device))
        db.expunge(device)

    results = []
    barrier = threading.Barrier(4)

    def run(sequence: int) -> None:
        with SessionLocal() as db:
            scanner_device = db.merge(device)
            barrier.wait()
            outcome = process_scan(
                db,
                scanner_device,
                ScanIn(
                    client_uuid=uuid.uuid4(),
                    device_sequence=sequence,
                    token=world["qr"],
                ),
            )[1]["outcome"]
            results.append(outcome)

    threads = [threading.Thread(target=run, args=(sequence,)) for sequence in range(1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["accepted", "duplicate", "duplicate", "duplicate"]
    assert _events() == 1


def test_offline_sync_ordered_with_replay(world, scanner, fake_clock):
    """Offline batches are sorted by device sequence and exact retries are idempotent."""
    base = fake_clock.t
    items = [
        scanner.item(
            world["qr"],
            capture_mode="offline",
            captured_at=(base - timedelta(hours=hours)).isoformat(),
        )
        for hours in (8, 4)
    ]
    response = scanner.client.post(
        "/api/attendance/sync",
        json={"items": list(reversed(items))},
        headers=scanner.headers,
    )
    results = response.json()["results"]
    assert [item["direction"] for item in results] == ["IN", "OUT"]
    assert all(item["status"] == 201 for item in results)

    replay = scanner.client.post(
        "/api/attendance/sync",
        json={"items": items},
        headers=scanner.headers,
    ).json()["results"]
    assert [item["outcome"] for item in replay] == ["replay", "replay"]

    future = scanner.item(
        world["qr"],
        capture_mode="offline",
        captured_at=(base + timedelta(days=1)).isoformat(),
    )
    accepted = scanner.client.post(
        "/api/attendance/sync",
        json={"items": [future]},
        headers=scanner.headers,
    ).json()["results"][0]
    # DEC-05: an offline timestamp beyond the future tolerance is rejected, not clamped.
    assert accepted["outcome"] == "rejected" and accepted["reason"] == "captured_in_future"
    assert accepted["employee"] is None
    assert _events() == 2

    with SessionLocal() as db:
        session = db.scalars(
            select(AttendanceSession).order_by(AttendanceSession.effective_in)
        ).first()
        assert session.effective_out - session.effective_in == timedelta(hours=4)
        modes = set(db.scalars(select(AttendanceEvent.capture_mode)))
    assert modes == {"offline"}

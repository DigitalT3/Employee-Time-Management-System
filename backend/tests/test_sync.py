"""Offline protocol (DEC-04/DEC-05): stop at first failure, timestamp bounds, heartbeat, sync status, scan log."""
from datetime import timedelta

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import AttendanceEvent
from app.services import attendance


def _events() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AttendanceEvent))


def test_sync_stops_at_first_retryable_failure(world, scanner, fake_clock, monkeypatch):
    """A failing item returns error and every later item is skipped, retryable and unprocessed."""
    base = fake_clock.t
    items = [
        scanner.item(world["qr"], capture_mode="offline",
                     captured_at=(base - timedelta(hours=h)).isoformat())
        for h in (6, 4, 2)
    ]
    original = attendance._evaluate

    def flaky(db, device, item):
        if item.device_sequence == 2:
            raise RuntimeError("database unavailable")
        return original(db, device, item)

    monkeypatch.setattr(attendance, "_evaluate", flaky)
    results = scanner.client.post("/api/attendance/sync", json={"items": items}, headers=scanner.headers).json()["results"]
    assert [r["outcome"] for r in results] == ["accepted", "error", "skipped"]
    assert [r["status"] for r in results] == [201, 503, 424]
    assert results[1]["retryable"] and results[2]["retryable"]
    assert _events() == 1

    # After recovery the same batch resumes in order; the first item is an exact replay.
    monkeypatch.setattr(attendance, "_evaluate", original)
    again = scanner.client.post("/api/attendance/sync", json={"items": items}, headers=scanner.headers).json()["results"]
    assert [r["outcome"] for r in again] == ["replay", "accepted", "accepted"]
    assert [r["direction"] for r in again] == ["IN", "OUT", "IN"]


def test_timestamp_bounds(world, scanner, fake_clock):
    """Online skew keeps the server time; offline too-old and future captures are rejected."""
    base = fake_clock.t
    within = scanner.scan(world["qr"], captured_at=(base - timedelta(seconds=20)).isoformat())
    assert within.json()["occurred_at"].startswith((base - timedelta(seconds=20)).isoformat()[:19])

    fake_clock.set(base + timedelta(hours=1))
    skewed = scanner.scan(world["qr"], captured_at=(base - timedelta(hours=5)).isoformat())
    assert skewed.json()["occurred_at"].startswith(fake_clock.t.isoformat()[:19])  # online: server time

    old = scanner.scan(world["qr"], capture_mode="offline",
                       captured_at=(fake_clock.t - timedelta(hours=49)).isoformat()).json()
    assert old["outcome"] == "rejected" and old["reason"] == "captured_too_old" and old["employee"] is None
    future = scanner.scan(world["qr"], capture_mode="offline",
                          captured_at=(fake_clock.t + timedelta(minutes=5)).isoformat()).json()
    assert future["reason"] == "captured_in_future"
    assert _events() == 2


def test_tentative_direction_mismatch_is_reported_not_trusted(world, scanner):
    """The backend decides IN/OUT; a wrong tablet guess only raises direction_mismatch."""
    result = scanner.scan(world["qr"], tentative_direction="OUT").json()
    assert result["direction"] == "IN" and result["direction_mismatch"] is True


def test_ping_status_context_and_sync_status(world, scanner, admin, supervisor, hr, fake_clock):
    """Heartbeat updates last_seen; reported queue counts feed the supervisor sync view."""
    context = scanner.client.get("/api/scanner/context", headers=scanner.headers).json()
    assert context["offline_max_age_hours"] == 48 and "server_time" in context
    assert admin.get("/api/attendance/sync/status").json()["items"][0]["connection"] == "never_seen"

    ping = scanner.client.get("/api/scanner/ping", headers=scanner.headers).json()
    assert ping["ok"] and ping["last_sequence"] == 0
    report = scanner.client.post("/api/scanner/status", headers=scanner.headers,
                                 json={"pending": 3, "failed": 1,
                                       "oldest_pending_at": (fake_clock.t - timedelta(hours=2)).isoformat()})
    assert report.status_code == 200
    row = supervisor.get("/api/attendance/sync/status").json()["items"][0]
    assert (row["connection"], row["state"], row["pending"], row["failed"]) == ("online", "failed", 3, 1)

    fake_clock.set(fake_clock.t + timedelta(minutes=10))
    assert supervisor.get("/api/attendance/sync/status").json()["items"][0]["connection"] == "offline"
    assert hr.get("/api/attendance/sync/status").status_code == 403
    assert scanner.client.get("/api/scanner/ping").status_code == 401


def test_scan_log_lists_problems_for_staff_only(world, scanner, admin, supervisor, hr):
    """Rejected and conflicting scans appear in the log without any raw credential."""
    scanner.scan("unknown-secret-value")
    item = scanner.item(world["qr"])
    scanner.client.post("/api/attendance/scan", json=item, headers=scanner.headers)
    scanner.client.post("/api/attendance/scan", json={**item, "token": "other"}, headers=scanner.headers)

    log = supervisor.get("/api/attendance/scan-log").json()
    outcomes = {entry["outcome"]: entry for entry in log["items"]}
    assert {"rejected", "conflict"} <= set(outcomes)
    assert outcomes["rejected"]["reason"] == "unknown_credential"
    assert "unknown-secret-value" not in str(log) and world["qr"] not in str(log)
    only = admin.get("/api/attendance/scan-log", params={"outcome": "conflict"}).json()
    assert only["total"] == 1
    assert hr.get("/api/attendance/scan-log").status_code == 403

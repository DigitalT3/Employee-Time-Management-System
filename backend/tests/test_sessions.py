"""VAL-05: on-site attendance, daily hours, missing-OUT exceptions, and corrections."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AttendanceEvent, AuditLog

UTC = timezone.utc


def test_on_site_daily_and_overnight_missing_out(world, scanner, admin, fake_clock):
    """Sessions are assigned to their IN date and are exceptions after the local cutoff."""
    fake_clock.set(datetime(2026, 3, 2, 21, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    on_site = admin.get(
        "/api/attendance/on-site", params={"site_id": world["site"]["id"]}
    ).json()
    assert on_site["count"] == 1
    assert on_site["items"][0]["employee_number"] == "E-1"

    fake_clock.set(datetime(2026, 3, 3, 5, 30, tzinfo=UTC))
    assert scanner.scan(world["qr"]).json()["direction"] == "OUT"
    assert admin.get("/api/attendance/on-site").json()["count"] == 0

    daily = admin.get(
        "/api/attendance/daily",
        params={"site_id": world["site"]["id"], "date": "2026-03-02"},
    ).json()
    assert daily["employees"][0]["total_hours"] == 8.5
    assert admin.get(
        "/api/attendance/daily", params={"date": "2026-03-03"}
    ).json()["employees"] == []

    fake_clock.set(datetime(2026, 3, 3, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 4, 4, 59, tzinfo=UTC))
    assert admin.get("/api/attendance/exceptions").json()["items"] == []
    assert admin.get("/api/attendance/on-site").json()["count"] == 1

    fake_clock.set(datetime(2026, 3, 4, 5, 0, tzinfo=UTC))
    exceptions = admin.get(
        "/api/attendance/exceptions", params={"date": "2026-03-03"}
    ).json()["items"]
    assert len(exceptions) == 1 and exceptions[0]["type"] == "missing_out"
    # The employee remains on site (latest recorded direction is IN) but is flagged missing OUT.
    after_cutoff = admin.get("/api/attendance/on-site").json()
    assert after_cutoff["count"] == 1
    assert after_cutoff["items"][0]["status"] == "missing_out"


def test_corrections_reason_version_and_audit(world, scanner, admin, supervisor, hr, fake_clock):
    """Supervisor corrections preserve raw events, require a reason, and append history."""
    fake_clock.set(datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 3, 9, 0, tzinfo=UTC))

    session_id = admin.get(
        "/api/attendance/daily", params={"date": "2026-03-02"}
    ).json()["employees"][0]["sessions"][0]["id"]
    body = {
        "field": "out",
        "new_value": "2026-03-02T16:00:00+00:00",
        "reason": "Forgot to scan out",
        "expected_version": 1,
    }

    assert supervisor.post(
        f"/api/attendance/sessions/{session_id}/corrections",
        json={**body, "reason": "  "},
    ).status_code == 422
    assert hr.post(
        f"/api/attendance/sessions/{session_id}/corrections", json=body
    ).status_code == 403

    correction = supervisor.post(
        f"/api/attendance/sessions/{session_id}/corrections", json=body
    )
    assert correction.status_code == 201, correction.text
    result = correction.json()
    assert result["hours"] == 9.0
    assert result["version"] == 2
    assert result["out_event"] is None

    stale = supervisor.post(
        f"/api/attendance/sessions/{session_id}/corrections", json=body
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"

    history = hr.get(
        f"/api/attendance/sessions/{session_id}/corrections"
    ).json()["items"]
    assert history[0]["field"] == "out"
    assert history[0]["actor"] == "sup"

    with SessionLocal() as db:
        events = list(db.scalars(select(AttendanceEvent)))
        audits = list(
            db.scalars(select(AuditLog).where(AuditLog.action == "session.correct"))
        )
    assert len(events) == 1
    assert events[0].occurred_at == datetime(2026, 3, 2, 7, 0, tzinfo=UTC)
    assert len(audits) == 1


def test_correction_overlap_and_future_times_are_rejected(world, scanner, supervisor, admin, fake_clock):
    """Corrections cannot overlap another session or set a future timestamp."""
    for hour in (7, 9, 11, 13):
        fake_clock.set(datetime(2026, 3, 2, hour, 0, tzinfo=UTC))
        scanner.scan(world["qr"])

    first = admin.get(
        "/api/attendance/daily", params={"date": "2026-03-02"}
    ).json()["employees"][0]["sessions"][0]

    overlap = supervisor.post(
        f"/api/attendance/sessions/{first['id']}/corrections",
        json={
            "field": "out",
            "new_value": "2026-03-02T12:00:00+00:00",
            "reason": "Incorrect departure",
            "expected_version": 1,
        },
    )
    assert overlap.status_code == 422
    assert overlap.json()["code"] == "overlap"

    future = supervisor.post(
        f"/api/attendance/sessions/{first['id']}/corrections",
        json={
            "field": "in",
            "new_value": (fake_clock.t + timedelta(days=1)).isoformat(),
            "reason": "Incorrect arrival",
            "expected_version": 1,
        },
    )
    assert future.status_code == 422
    assert future.json()["code"] == "future_time"

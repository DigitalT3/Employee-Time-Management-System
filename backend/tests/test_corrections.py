"""Correction rules (DEC-07): site-zone input, DST gaps/overlaps, global audit."""
from datetime import datetime, timezone

UTC = timezone.utc


def _open_session(world, scanner, admin, fake_clock, when: datetime) -> str:
    fake_clock.set(when)
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 4, 5, 12, 0, tzinfo=UTC))
    return admin.get("/api/attendance/history").json()["items"][0]["id"]


def test_naive_time_is_site_local(world, scanner, admin, supervisor, fake_clock):
    """A naive time is read in the site's zone; the result is stored as UTC with local display."""
    session_id = _open_session(world, scanner, admin, fake_clock, datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    response = supervisor.post(f"/api/attendance/sessions/{session_id}/corrections", json={
        "field": "out", "new_value": "2026-03-02T17:00:00", "reason": "Left at five", "expected_version": 1})
    assert response.status_code == 201, response.text
    correction = response.json()["corrections"][0]
    assert correction["new_value"].startswith("2026-03-02T16:00:00")  # 17:00 CET == 16:00 UTC
    assert correction["new_value_local"].startswith("2026-03-02T17:00:00+01:00")
    assert response.json()["flags"].count("corrected") == 1


def test_dst_gap_and_overlap_are_explicit_errors(world, scanner, admin, supervisor, fake_clock):
    """Nonexistent (spring forward) and ambiguous (fall back) local times return 422."""
    session_id = _open_session(world, scanner, admin, fake_clock, datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    url = f"/api/attendance/sessions/{session_id}/corrections"
    gap = supervisor.post(url, json={"field": "out", "new_value": "2026-03-29T02:30:00",
                                     "reason": "gap", "expected_version": 1})
    assert gap.status_code == 422 and gap.json()["code"] == "nonexistent_local_time"
    fold = supervisor.post(url, json={"field": "out", "new_value": "2026-10-25T02:30:00",
                                      "reason": "fold", "expected_version": 1})
    assert fold.status_code == 422 and fold.json()["code"] in {"ambiguous_local_time", "future_time"}
    # An explicit offset removes the ambiguity.
    ok = supervisor.post(url, json={"field": "out", "new_value": "2026-03-02T18:00:00+01:00",
                                    "reason": "explicit offset", "expected_version": 1})
    assert ok.status_code == 201


def test_global_correction_routes(world, scanner, admin, supervisor, hr, fake_clock):
    """Global create/list/get routes keep the audit visible with original value, actor and time."""
    session_id = _open_session(world, scanner, admin, fake_clock, datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    created = supervisor.post("/api/attendance/corrections", json={
        "session_id": session_id, "field": "out", "new_value": "2026-03-02T16:30:00",
        "reason": "Global route", "expected_version": 1})
    assert created.status_code == 201, created.text
    assert hr.post("/api/attendance/corrections", json={
        "session_id": session_id, "field": "out", "new_value": "2026-03-02T17:00:00",
        "reason": "Not allowed", "expected_version": 2}).status_code == 403

    listing = hr.get("/api/attendance/corrections", params={"session_id": session_id}).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["actor"] == "sup" and item["old_value"] is None and item["employee_number"] == "E-1"
    assert item["site_code"] == "AMS" and item["reason"] == "Global route"
    assert hr.get(f"/api/attendance/corrections/{item['id']}").json()["id"] == item["id"]
    assert hr.get("/api/attendance/corrections/00000000-0000-0000-0000-000000000000").status_code == 404

"""Dashboard, current, history and events read models (FR-05, FR-09)."""
from datetime import datetime, timezone

UTC = timezone.utc


def test_dashboard_single_request(world, scanner, admin, supervisor, hr, fake_clock):
    """One request gives counts, on-site list, recent activity, exceptions, scan problems and sync."""
    fake_clock.set(datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    scanner.scan("unknown")
    data = supervisor.get("/api/attendance/dashboard").json()
    assert data["counts"]["on_site"] == 1 and data["counts"]["incomplete"] == 0
    assert data["on_site"][0]["employee_number"] == "E-1"
    assert data["on_site"][0]["site_timezone"] == "Europe/Amsterdam"
    assert data["recent_activity"][0]["direction"] == "IN"
    assert data["scan_problems"][0]["reason"] == "unknown_credential"
    assert data["device_sync"][0]["device_name"] == "Tablet 1"
    assert {"as_of", "date", "exceptions"} <= set(data)
    # HR may view the dashboard but gets no scan log or device status (no scanlog.view).
    hr_view = hr.get("/api/attendance/dashboard")
    assert hr_view.status_code == 200 and hr_view.json()["scan_problems"] == []


def test_current_alias_and_missing_out_status(world, scanner, admin, fake_clock):
    """/current equals /on-site; a session past cut-off stays listed with status missing_out."""
    fake_clock.set(datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    assert admin.get("/api/attendance/current").json()["count"] == 1
    fake_clock.set(datetime(2026, 3, 4, 12, 0, tzinfo=UTC))
    item = admin.get("/api/attendance/current").json()["items"][0]
    assert item["status"] == "missing_out" and "missing_out" in item["flags"]
    dashboard = admin.get("/api/attendance/dashboard").json()
    assert dashboard["counts"]["on_site"] == 1 and dashboard["counts"]["incomplete"] >= 1


def test_history_filters_pagination_and_events(world, scanner, admin, fake_clock):
    """History filters by status/date range and paginates; events carry site-local times."""
    for hour in (7, 9, 11):
        fake_clock.set(datetime(2026, 3, 2, hour, 0, tzinfo=UTC))
        scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 2, 13, 0, tzinfo=UTC))
    full = admin.get("/api/attendance/history", params={"from": "2026-03-02", "to": "2026-03-02"}).json()
    assert full["total"] == 2 and len(full["items"]) == 2
    assert full["items"][0]["status"] == "open" and full["items"][1]["status"] == "complete"
    assert full["items"][1]["duration_minutes"] == 120 and full["items"][1]["local_in"].startswith("2026-03-02T08:00")
    assert admin.get("/api/attendance/history", params={"status": "complete"}).json()["total"] == 1
    page = admin.get("/api/attendance/history", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert admin.get("/api/attendance/history", params={"from": "2026-03-05", "to": "2026-03-01"}).status_code == 422

    events = admin.get("/api/attendance/events").json()["items"]
    assert len(events) == 3 and events[0]["employee_name"] == "Ada Lovelace" and events[0]["gate_name"] == "Main Gate"
    assert events[0]["local_time"].endswith("+01:00")


def test_flat_gate_and_employee_aliases(world, admin, supervisor):
    """Specification aliases: flat gates routes, PUT employee, PATCH status."""
    created = admin.post("/api/gates", json={"site_id": world["site"]["id"], "name": "Side Gate"})
    assert created.status_code == 201
    names = [g["name"] for g in supervisor.get("/api/gates", params={"site_id": world["site"]["id"]}).json()]
    assert names == ["Main Gate", "Side Gate"]
    assert supervisor.post("/api/gates", json={"site_id": world["site"]["id"], "name": "X"}).status_code == 403
    employee_id = world["employee"]["id"]
    assert admin.put(f"/api/employees/{employee_id}", json={"first_name": "Augusta"}).json()["first_name"] == "Augusta"
    assert admin.patch(f"/api/employees/{employee_id}/status", json={"is_active": False}).json()["is_active"] is False
    assert admin.get(f"/api/employees/{employee_id}").json()["sites"][0]["code"] == "AMS"

"""VAL-02: sites, gates, settings, devices and scanner context."""


def test_site_gate_settings_device(admin, supervisor):
    r = admin.post("/api/sites", json={"code": "RTM", "name": "Rotterdam"})
    assert r.status_code == 201
    site = r.json()
    assert admin.post("/api/sites", json={"code": "RTM", "name": "x"}).status_code == 409
    assert admin.post("/api/sites", json={"code": "X", "name": "x", "timezone": "Mars/Base"}).status_code == 422
    assert admin.patch(f"/api/sites/{site['id']}", json={"name": "Rotterdam Port"}).json()["name"] == "Rotterdam Port"

    st = admin.get(f"/api/sites/{site['id']}/settings").json()
    assert st == {"duplicate_window_seconds": 120, "missing_out_cutoff_time": "06:00:00"}
    put = admin.put(f"/api/sites/{site['id']}/settings",
                    json={"duplicate_window_seconds": 60, "missing_out_cutoff_time": "05:00:00"})
    assert put.json()["duplicate_window_seconds"] == 60
    assert admin.put(f"/api/sites/{site['id']}/settings",
                     json={"duplicate_window_seconds": 99999, "missing_out_cutoff_time": "05:00"}).status_code == 422

    gate = admin.post(f"/api/sites/{site['id']}/gates", json={"name": "North"}).json()
    assert admin.post(f"/api/sites/{site['id']}/gates", json={"name": "North"}).status_code == 409
    assert admin.patch(f"/api/gates/{gate['id']}", json={"name": "North 2"}).json()["name"] == "North 2"
    assert len(admin.get(f"/api/sites/{site['id']}/gates").json()) == 1

    assert supervisor.post("/api/devices", json={"name": "T", "gate_id": gate["id"]}).status_code == 403
    dev = admin.post("/api/devices", json={"name": "T", "gate_id": gate["id"]}).json()
    assert dev["site_id"] == site["id"] and dev["device_token"]
    listed = admin.get("/api/devices").json()
    assert "device_token" not in listed[0]

    from fastapi.testclient import TestClient
    from app.main import app
    t = TestClient(app)
    assert t.get("/api/scanner/context").status_code == 401
    ctx = t.get("/api/scanner/context", headers={"X-Device-Token": dev["device_token"]}).json()
    assert ctx["site"]["code"] == "RTM" and ctx["gate"]["name"] == "North 2" and ctx["duplicate_window_seconds"] == 60
    admin.patch(f"/api/devices/{dev['id']}", json={"is_active": False})
    assert t.get("/api/scanner/context", headers={"X-Device-Token": dev["device_token"]}).status_code == 401


def test_openapi_lists_endpoints(anon):
    paths = anon.get("/openapi.json").json()["paths"]
    for p in ["/api/health", "/api/auth/login", "/api/employees", "/api/employees/{employee_id}/qr.pdf",
              "/api/sites/{site_id}/settings", "/api/devices", "/api/scanner/context", "/api/attendance/scan",
              "/api/attendance/sync", "/api/attendance/on-site", "/api/attendance/daily",
              "/api/attendance/exceptions", "/api/attendance/events",
              "/api/attendance/sessions/{session_id}/corrections", "/api/reports/attendance.csv"]:
        assert p in paths, p

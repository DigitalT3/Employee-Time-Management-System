#!/usr/bin/env python3
"""Run the 20 live ETMS attendance scenarios against a running synthetic stack.

The runner creates unique synthetic staff-test employees, gates, devices, and
requests for each invocation. It does not print QR tokens, passwords, or
device tokens. Scenarios that use historical capture times deliberately use
the documented offline protocol so timestamp preservation and bounds are
tested through the public API.

Run after ``bash scripts/reset_demo.sh`` and starting the backend:

    backend/.venv/bin/python scripts/scenarios_20.py
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]


def seed_password(name: str) -> str | None:
    """Read a generated seed password from the environment or backend .env."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = ROOT / "backend" / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("=")
        if key == name and value:
            return value.strip(chr(34) + chr(39))
    return None


def issued_payload(employee_id: str) -> str:
    """Read a synthetic credential through backend test helpers without printing it."""
    sys.path.insert(0, str(ROOT / "backend"))
    previous_directory = os.getcwd()
    try:
        os.chdir(ROOT / "backend")
        from app.db import SessionLocal
        from app.services.credentials import credential_payload, current_credential

        with SessionLocal() as db:
            credential = current_credential(db, uuid.UUID(employee_id))
            if credential is None:
                raise RuntimeError("employee has no current credential")
            return credential_payload(credential)
    finally:
        os.chdir(previous_directory)


@dataclass
class Employee:
    """Synthetic employee and opaque credential kept in-memory for one run."""

    id: str
    number: str
    credential_id: str
    token: str


class Results:
    """Collect named scenario outcomes and keep execution going after failures."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, scenario: str, condition: bool, detail: str = "") -> None:
        """Record and print one scenario result without leaking test credentials."""
        self.rows.append((scenario, bool(condition), detail))
        suffix = f" -- {detail}" if detail and not condition else ""
        print(f"[{'PASS' if condition else 'FAIL'}] {scenario}{suffix}")

    @property
    def passed(self) -> int:
        """Return the number of passing scenarios."""
        return sum(ok for _, ok, _ in self.rows)


class ScenarioApi:
    """Small public-API client that allocates monotonic device sequence numbers."""

    def __init__(self, base_url: str, admin_password: str, results: Results) -> None:
        self.base_url = base_url.rstrip("/")
        self.results = results
        self.admin = httpx.Client(base_url=self.base_url, timeout=20)
        self.scanner = httpx.Client(base_url=self.base_url, timeout=20)
        login = self.admin.post(
            "/api/auth/login", json={"username": "admin", "password": admin_password}
        )
        if login.status_code != 200:
            raise RuntimeError(f"administrator login failed with HTTP {login.status_code}")
        self.headers: dict[str, str] = {}
        self.sequence = 0
        self.site_id = ""
        self.run = uuid.uuid4().hex[:8].upper()

    def close(self) -> None:
        """Close both HTTP clients."""
        self.admin.close()
        self.scanner.close()

    def setup(self) -> None:
        """Create one isolated scanner device and a short configured duplicate window."""
        sites = self.admin.get("/api/sites").json()
        if not sites:
            raise RuntimeError("no synthetic site exists; run bash scripts/reset_demo.sh first")
        self.site_id = sites[0]["id"]
        settings = self.admin.put(
            f"/api/sites/{self.site_id}/settings",
            json={"duplicate_window_seconds": 60, "missing_out_cutoff_time": "06:00:00"},
        )
        if settings.status_code != 200:
            raise RuntimeError(f"could not set test policy (HTTP {settings.status_code})")
        gate = self.admin.post(
            f"/api/sites/{self.site_id}/gates", json={"name": f"Scenario Gate {self.run}"}
        )
        if gate.status_code != 201:
            raise RuntimeError(f"could not create test gate (HTTP {gate.status_code})")
        device = self.admin.post(
            "/api/devices",
            json={"name": f"Scenario Tablet {self.run}", "gate_id": gate.json()["id"]},
        )
        if device.status_code != 201:
            raise RuntimeError(f"could not create test scanner device (HTTP {device.status_code})")
        self.headers = {"X-Device-Token": device.json()["device_token"]}

    def employee(self, tag: str, site_ids: list[str] | None = None) -> Employee:
        """Create an isolated employee and retrieve its current opaque QR payload."""
        response = self.admin.post(
            "/api/employees",
            json={
                "employee_number": f"SCN-{self.run}-{tag}",
                "first_name": "Scenario",
                "last_name": tag,
                "site_ids": site_ids or [self.site_id],
            },
        )
        if response.status_code != 201:
            raise RuntimeError(f"could not create employee {tag} (HTTP {response.status_code})")
        body = response.json()
        credential = self.admin.get(f"/api/employees/{body['id']}/qr").json()
        return Employee(
            id=body["id"],
            number=body["employee_number"],
            credential_id=credential["id"],
            token=issued_payload(body["id"]),
        )

    def item(
        self,
        token: str,
        *,
        captured_at: datetime | None = None,
        mode: str = "online",
        request_id: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        """Build a token-bearing scan request without logging the secret token."""
        if sequence is None:
            self.sequence += 1
            sequence = self.sequence
        else:
            self.sequence = max(self.sequence, sequence)
        return {
            "client_uuid": request_id or str(uuid.uuid4()),
            "device_sequence": sequence,
            "token": token,
            "captured_at": captured_at.isoformat() if captured_at else None,
            "capture_mode": mode,
        }

    def scan(self, item: dict[str, Any]) -> httpx.Response:
        """Submit one scanner request using the paired device header."""
        return self.scanner.post("/api/attendance/scan", json=item, headers=self.headers)

    def events(self, employee: Employee) -> list[dict[str, Any]]:
        """Return immutable stored events for one synthetic employee."""
        response = self.admin.get("/api/attendance/events", params={"employee_id": employee.id})
        return response.json()["items"] if response.status_code == 200 else []


# PUBLIC_INTERFACE
def main() -> int:
    """Execute S01 through S20 and return nonzero when any observable result fails."""
    parser = argparse.ArgumentParser(description="Run the 20 ETMS API attendance scenarios.")
    parser.add_argument("--base-url", default=os.environ.get("ETMS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-password", default=seed_password("SEED_ADMIN_PASSWORD"))
    args = parser.parse_args()
    if not args.admin_password:
        print("Missing SEED_ADMIN_PASSWORD; run bash scripts/gen_env.sh first.", file=sys.stderr)
        return 2

    results = Results()
    api = ScenarioApi(args.base_url, args.admin_password, results)
    now = datetime.now(timezone.utc)
    historical = now - timedelta(hours=3)

    try:
        api.setup()
        print(
            "Conditions: live loopback API; synthetic data; one generated device; "
            "duplicate window=60 seconds; historical cases use offline capture timestamps; "
            "no physical QR camera, tablet, or lighting measurement."
        )

        first = api.employee("S01")
        s01 = api.scan(api.item(first.token, captured_at=historical, mode="offline"))
        results.check("S01 first scan records IN", s01.status_code == 201 and s01.json().get("direction") == "IN")

        s02 = api.scan(api.item(first.token, captured_at=historical + timedelta(minutes=5), mode="offline"))
        results.check(
            "S02 later scan records OUT with duration",
            s02.status_code == 201
            and s02.json().get("direction") == "OUT"
            and s02.json().get("duration_minutes") == 5,
        )

        s03 = api.scan(api.item(first.token, captured_at=historical + timedelta(minutes=7), mode="offline"))
        results.check("S03 next scan records IN", s03.status_code == 201 and s03.json().get("direction") == "IN")

        s04 = api.scan(api.item(first.token, captured_at=historical + timedelta(minutes=7, seconds=30), mode="offline"))
        results.check("S04 duplicate inside configured window is ignored", s04.json().get("outcome") == "duplicate")

        unknown = api.scan(api.item("synthetic-unknown-token", captured_at=historical, mode="offline"))
        results.check(
            "S05 unknown token is rejected without identity",
            unknown.json().get("outcome") == "rejected"
            and unknown.json().get("reason") == "unknown_credential"
            and unknown.json().get("employee") is None,
        )

        blocked = api.employee("S06")
        api.admin.patch(f"/api/qr-credentials/{blocked.credential_id}/block", json={"reason": "scenario"})
        s06 = api.scan(api.item(blocked.token, captured_at=historical, mode="offline"))
        results.check("S06 blocked credential is rejected", s06.json().get("reason") == "blocked")

        api.admin.patch(f"/api/qr-credentials/{blocked.credential_id}/unblock", json={"reason": "scenario"})
        s07 = api.scan(api.item(blocked.token, captured_at=historical, mode="offline"))
        results.check("S07 unblocked credential is accepted", s07.status_code == 201 and s07.json().get("outcome") == "accepted")

        inactive = api.employee("S08")
        api.admin.patch(f"/api/employees/{inactive.id}/status", json={"is_active": False})
        s08 = api.scan(api.item(inactive.token, captured_at=historical, mode="offline"))
        results.check("S08 inactive employee is rejected", s08.json().get("reason") == "inactive_employee")

        other_site = api.admin.post(
            "/api/sites",
            json={"code": f"SCN-{api.run}", "name": "Scenario Other Site", "timezone": "Europe/Amsterdam"},
        ).json()
        wrong_site = api.employee("S09", [other_site["id"]])
        s09 = api.scan(api.item(wrong_site.token, captured_at=historical, mode="offline"))
        results.check("S09 wrong-site employee is rejected", s09.json().get("reason") == "wrong_site")

        replay_employee = api.employee("S10")
        replay_item = api.item(replay_employee.token, captured_at=historical, mode="offline")
        api.scan(replay_item)
        s10 = api.scan(replay_item)
        results.check(
            "S10 exact request replay returns stored result without a new event",
            s10.status_code == 200 and s10.json().get("outcome") == "replay" and len(api.events(replay_employee)) == 1,
        )

        conflict_employee = api.employee("S11")
        conflicting = {**replay_item, "token": conflict_employee.token}
        s11 = api.scan(conflicting)
        results.check("S11 client UUID reuse with another payload conflicts", s11.status_code == 409 and s11.json().get("outcome") == "conflict")

        batch_a, batch_b = api.employee("S12A"), api.employee("S12B")
        batch_time = historical + timedelta(minutes=20)
        batch = [
            api.item(batch_a.token, captured_at=batch_time, mode="offline"),
            api.item(batch_a.token, captured_at=batch_time + timedelta(minutes=4), mode="offline"),
            api.item(batch_b.token, captured_at=batch_time + timedelta(minutes=8), mode="offline"),
        ]
        s12 = api.scanner.post("/api/attendance/sync", json={"items": list(reversed(batch))}, headers=api.headers)
        s12_results = s12.json().get("results", [])
        results.check(
            "S12 ordered offline batch preserves timestamps and order",
            s12.status_code == 200
            and [row.get("direction") for row in s12_results] == ["IN", "OUT", "IN"]
            and [row.get("outcome") for row in s12_results] == ["accepted", "accepted", "accepted"],
        )

        s13 = api.scanner.post("/api/attendance/sync", json={"items": batch}, headers=api.headers)
        results.check(
            "S13 synchronized batch replay creates no duplicates",
            s13.status_code == 200 and all(row.get("outcome") == "replay" for row in s13.json().get("results", [])),
        )

        resequence_employee = api.employee("S14")
        original = api.item(resequence_employee.token, captured_at=historical, mode="offline")
        api.scan(original)
        reused = api.item(
            resequence_employee.token,
            captured_at=historical + timedelta(minutes=2),
            mode="offline",
            sequence=original["device_sequence"],
        )
        conflict = api.scan(reused)
        last_sequence = conflict.json().get("last_sequence")
        repaired = {**reused, "client_uuid": str(uuid.uuid4()), "device_sequence": int(last_sequence) + 1}
        # The tablet adopts the repaired sequence; later scenarios must continue after it.
        api.sequence = max(api.sequence, repaired["device_sequence"])
        s14 = api.scan(repaired)
        results.check(
            "S14 reused sequence reports last sequence and resequenced retry succeeds",
            conflict.status_code == 409
            and conflict.json().get("reason") == "device_sequence_reused"
            and s14.status_code == 201,
        )

        ordered = api.employee("S15")
        api.scan(api.item(ordered.token, captured_at=historical, mode="offline"))
        s15 = api.scan(api.item(ordered.token, captured_at=historical - timedelta(minutes=3), mode="offline"))
        results.check("S15 older event is rejected as out of order", s15.json().get("reason") == "out_of_order")

        expired = api.employee("S16")
        s16 = api.scan(api.item(expired.token, captured_at=now - timedelta(hours=49), mode="offline"))
        results.check("S16 offline capture beyond maximum age is rejected", s16.json().get("reason") == "captured_too_old")

        revoked = api.employee("S17")
        api.admin.patch(f"/api/qr-credentials/{revoked.credential_id}/revoke", json={"reason": "scenario"})
        old_rejected = api.scan(api.item(revoked.token, captured_at=historical, mode="offline"))
        reissued = api.admin.post(f"/api/employees/{revoked.id}/qr/reissue", json={"reason": "scenario"})
        renewed_token = issued_payload(revoked.id)
        renewed = api.scan(api.item(renewed_token, captured_at=historical, mode="offline"))
        results.check(
            "S17 revoked credential is rejected and reissued credential succeeds",
            old_rejected.json().get("reason") == "revoked"
            and reissued.status_code == 201
            and renewed.status_code == 201,
        )

        overnight = api.employee("S18")
        zone = ZoneInfo("Europe/Amsterdam")
        local_day = now.astimezone(zone).date() - timedelta(days=1)
        overnight_in = datetime(local_day.year, local_day.month, local_day.day, 22, tzinfo=zone).astimezone(timezone.utc)
        overnight_out = overnight_in + timedelta(hours=8)
        api.scan(api.item(overnight.token, captured_at=overnight_in, mode="offline"))
        s18 = api.scan(api.item(overnight.token, captured_at=overnight_out, mode="offline"))
        results.check(
            "S18 overnight session calculates eight hours",
            s18.status_code == 201 and s18.json().get("duration_minutes") == 480,
        )

        missing = api.employee("S19")
        api.scan(api.item(missing.token, captured_at=now - timedelta(hours=47), mode="offline"))
        exceptions = api.admin.get("/api/attendance/exceptions", params={"site_id": api.site_id}).json().get("items", [])
        results.check(
            "S19 old open session appears in missing-OUT exceptions",
            any(row.get("employee_number") == missing.number and row.get("missing_out") for row in exceptions),
        )

        concurrent = api.employee("S20")
        first_item = api.item(concurrent.token)
        second_item = api.item(concurrent.token)
        barrier = threading.Barrier(2)
        responses: list[httpx.Response] = []

        def submit(item: dict[str, Any]) -> None:
            barrier.wait()
            responses.append(
                httpx.post(
                    f"{api.base_url}/api/attendance/scan",
                    json=item,
                    headers=api.headers,
                    timeout=20,
                )
            )

        threads = [threading.Thread(target=submit, args=(item,)) for item in (first_item, second_item)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        outcomes = sorted(response.json().get("outcome") for response in responses)
        results.check(
            "S20 concurrent scans produce one accepted event and one duplicate",
            outcomes == ["accepted", "duplicate"] and len(api.events(concurrent)) == 1,
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"Scenario setup or execution error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        api.close()

    print(f"\nSummary: {results.passed}/{len(results.rows)} scenarios passed")
    return 0 if results.passed == len(results.rows) == 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Measure synthetic ETMS API scan and dashboard timings against a running backend.

This script measures loopback HTTP processing only. It deliberately does not
claim physical QR-decoding, tablet rendering, camera autofocus, lighting, or
network-latency evidence.

Run after ``bash scripts/reset_demo.sh`` and starting the backend:

    backend/.venv/bin/python scripts/perf_check.py
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = 50


def seed_password(name: str) -> str | None:
    """Read a generated seed password without putting it in source."""
    if os.environ.get(name):
        return os.environ[name]
    path = ROOT / "backend" / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("=")
        if key == name and value:
            return value.strip(chr(34) + chr(39))
    return None


def credential_payload(employee_id: str) -> str:
    """Retrieve a current synthetic QR token for a live API test without logging it."""
    sys.path.insert(0, str(ROOT / "backend"))
    previous_directory = os.getcwd()
    try:
        os.chdir(ROOT / "backend")
        from app.db import SessionLocal
        from app.services.credentials import credential_payload as decrypt_payload
        from app.services.credentials import current_credential

        with SessionLocal() as db:
            credential = current_credential(db, uuid.UUID(employee_id))
            if credential is None:
                raise RuntimeError("test employee has no current credential")
            return decrypt_payload(credential)
    finally:
        os.chdir(previous_directory)


def percentile(values: list[float], fraction: float) -> float:
    """Return nearest-rank percentile for a non-empty sample list."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) * fraction + 0.999999)) - 1))]


@dataclass
class Measurement:
    """One API response measurement."""

    client_ms: float
    server_ms: float | None


# PUBLIC_INTERFACE
def main() -> int:
    """Run fifty serial scans and report client/server/dashboard timing summaries."""
    parser = argparse.ArgumentParser(description="Measure ETMS scan and dashboard API timings.")
    parser.add_argument("--base-url", default=os.environ.get("ETMS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-password", default=seed_password("SEED_ADMIN_PASSWORD"))
    parser.add_argument("--samples", type=int, default=SAMPLES, help="Positive even scan count (default: 50).")
    args = parser.parse_args()
    if not args.admin_password:
        print("Missing SEED_ADMIN_PASSWORD; run bash scripts/gen_env.sh first.", file=sys.stderr)
        return 2
    if args.samples < 2 or args.samples % 2:
        print("--samples must be an even integer of at least two.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    run = uuid.uuid4().hex[:8].upper()
    with httpx.Client(base_url=base_url, timeout=20) as admin, httpx.Client(base_url=base_url, timeout=20) as scanner:
        login = admin.post("/api/auth/login", json={"username": "admin", "password": args.admin_password})
        if login.status_code != 200:
            print(f"Administrator login failed with HTTP {login.status_code}.", file=sys.stderr)
            return 2

        sites = admin.get("/api/sites").json()
        if not sites:
            print("No synthetic site found; run bash scripts/reset_demo.sh first.", file=sys.stderr)
            return 2
        site_id = sites[0]["id"]
        policy = admin.put(
            f"/api/sites/{site_id}/settings",
            json={"duplicate_window_seconds": 0, "missing_out_cutoff_time": "06:00:00"},
        )
        if policy.status_code != 200:
            print(f"Could not set isolated performance policy (HTTP {policy.status_code}).", file=sys.stderr)
            return 2

        gate = admin.post(f"/api/sites/{site_id}/gates", json={"name": f"Performance Gate {run}"})
        device = admin.post(
            "/api/devices",
            json={"name": f"Performance Tablet {run}", "gate_id": gate.json()["id"]},
        )
        if gate.status_code != 201 or device.status_code != 201:
            print("Could not create performance test scanner resources.", file=sys.stderr)
            return 2
        headers = {"X-Device-Token": device.json()["device_token"]}

        employees: list[tuple[str, str]] = []
        for number in range(args.samples // 2):
            created = admin.post(
                "/api/employees",
                json={
                    "employee_number": f"PERF-{run}-{number:03d}",
                    "first_name": "Performance",
                    "last_name": f"Employee{number:03d}",
                    "site_ids": [site_id],
                },
            )
            if created.status_code != 201:
                print(f"Could not create sample employee {number} (HTTP {created.status_code}).", file=sys.stderr)
                return 2
            body = created.json()
            employees.append((body["id"], credential_payload(body["id"])))

        measurements: list[Measurement] = []
        dashboard_latencies: list[float] = []
        sequence = 0
        for pass_number in range(2):
            for employee_id, token in employees:
                sequence += 1
                started = time.perf_counter()
                response = scanner.post(
                    "/api/attendance/scan",
                    json={
                        "client_uuid": str(uuid.uuid4()),
                        "device_sequence": sequence,
                        "token": token,
                        "capture_mode": "online",
                    },
                    headers=headers,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                if response.status_code != 201 or response.json().get("outcome") != "accepted":
                    print(
                        f"Scan {sequence} failed with HTTP {response.status_code} / "
                        f"{response.json().get('outcome')}.",
                        file=sys.stderr,
                    )
                    return 1
                header = response.headers.get("X-Process-Time-Ms")
                measurements.append(Measurement(elapsed_ms, float(header) if header else None))

                # Poll the dashboard immediately. This observes API-to-dashboard-read-model
                # availability, not the frontend's five-second polling interval.
                deadline = started + 10
                appeared = False
                while time.perf_counter() < deadline:
                    dashboard = admin.get("/api/attendance/dashboard", params={"site_id": site_id})
                    if dashboard.status_code == 200 and any(
                        item.get("employee_id") == employee_id
                        for item in dashboard.json().get("on_site", [])
                    ) == (pass_number == 0):
                        appeared = True
                        break
                    time.sleep(0.05)
                if appeared:
                    dashboard_latencies.append((time.perf_counter() - started) * 1000)

    client_times = [sample.client_ms for sample in measurements]
    server_times = [sample.server_ms for sample in measurements if sample.server_ms is not None]
    print(
        "Conditions: loopback HTTP; synthetic data; one generated scanner device; "
        f"{args.samples} sequential online API scans; duplicate window=0; no browser, "
        "physical QR decoder, camera, tablet, lighting, or remote-network measurement."
    )
    print(
        f"Client scan request: n={len(client_times)} median={statistics.median(client_times):.2f} ms "
        f"p95={percentile(client_times, 0.95):.2f} ms"
    )
    if server_times:
        print(
            f"X-Process-Time-Ms: n={len(server_times)} median={statistics.median(server_times):.2f} ms "
            f"p95={percentile(server_times, 0.95):.2f} ms"
        )
    else:
        print("X-Process-Time-Ms: Not Run (header absent).")
    if dashboard_latencies:
        print(
            f"Scan-to-dashboard-read-model: n={len(dashboard_latencies)} "
            f"median={statistics.median(dashboard_latencies):.2f} ms "
            f"p95={percentile(dashboard_latencies, 0.95):.2f} ms"
        )
    else:
        print("Scan-to-dashboard-read-model: FAILED (no sample appeared within ten seconds).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

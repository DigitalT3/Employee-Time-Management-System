#!/usr/bin/env python3
"""End-to-end API smoke test against a running ETMS backend (STEP-03).

Run with the backend virtualenv from the repo root, with the backend and the
local PostgreSQL cluster running:

    backend/.venv/bin/python scripts/e2e_smoke.py [--base-url http://127.0.0.1:8000]

Uses only synthetic data (unique employee numbers per run). The QR payload is
read via the backend's own credential decryption (no QR image decoder is
installed); PNG reprint determinism is checked byte-for-byte instead.
Exit code 0 only when every check passed.
"""
import argparse
import csv
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    """Record and print one check result."""
    RESULTS.append((bool(ok), name))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    return bool(ok)


def qr_payload(employee_id: str) -> str:
    """Return the employee's permanent QR payload using backend crypto (test harness only)."""
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    os.chdir(os.path.join(ROOT, "backend"))  # so app.config finds backend/.env
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import QrCredential
    from app.services.credentials import credential_payload

    with SessionLocal() as db:
        cred = db.scalar(select(QrCredential).where(QrCredential.employee_id == uuid.UUID(employee_id)))
        return credential_payload(cred)


def iso(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601."""
    return dt.isoformat()


def seed_password(name: str) -> str | None:
    """Return a SEED_*_PASSWORD from the environment or backend/.env (never from a literal)."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = os.path.join(ROOT, "backend", ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key == name and value:
                    return value.strip(chr(34) + chr(39))
    return None


def main() -> int:
    """Run the workflow and print a pass/fail summary."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("ETMS_BASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--admin-password", default=seed_password("SEED_ADMIN_PASSWORD"))
    ap.add_argument("--supervisor-password", default=seed_password("SEED_SUPERVISOR_PASSWORD"))
    ap.add_argument("--hr-password", default=seed_password("SEED_HR_PASSWORD"))
    args = ap.parse_args()
    if not (args.admin_password and args.supervisor_password and args.hr_password):
        print("Seed passwords not found: run scripts/gen_env.sh or set SEED_*_PASSWORD.", file=sys.stderr)
        return 2
    run = uuid.uuid4().hex[:8].upper()
    now = datetime.now(timezone.utc)
    print(
        "Conditions: live loopback API; generated synthetic employees, gate and device; "
        "backend credential helper used only to obtain test payloads; no physical QR camera, "
        "tablet, browser rendering, Excel, or remote-network evidence."
    )

    with httpx.Client(base_url=args.base_url, timeout=20) as admin, \
            httpx.Client(base_url=args.base_url, timeout=20) as sup, \
            httpx.Client(base_url=args.base_url, timeout=20) as hr, \
            httpx.Client(base_url=args.base_url, timeout=20) as anon:
        check(anon.get("/api/health").json() == {"status": "ok"}, "health endpoint")
        check(anon.get("/api/employees").status_code == 401, "unauthenticated staff call rejected (401)")
        check(anon.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401,
              "bad password rejected (401)")
        r = admin.post("/api/auth/login", json={"username": "admin", "password": args.admin_password})
        check(r.status_code == 200 and r.json()["role"] == "admin", "admin login", r.text)
        check(admin.get("/api/auth/me").json()["username"] == "admin", "session cookie authenticates /auth/me")
        check(sup.post("/api/auth/login", json={"username": "supervisor", "password": args.supervisor_password})
              .status_code == 200, "supervisor login")
        check(hr.post("/api/auth/login", json={"username": "hr", "password": args.hr_password}).status_code == 200,
              "hr login")

        site = admin.get("/api/sites").json()[0]
        gate = admin.post(f"/api/sites/{site['id']}/gates", json={"name": f"E2E Gate {run}"})
        check(gate.status_code == 201, "create gate", gate.text)
        dev = admin.post("/api/devices", json={"name": f"E2E Tablet {run}", "gate_id": gate.json()["id"]})
        check(dev.status_code == 201 and dev.json().get("device_token"), "pair device (token shown once)", dev.text)
        dtoken = dev.json()["device_token"]
        dh = {"X-Device-Token": dtoken}
        ctx = anon.get("/api/scanner/context", headers=dh)
        check(ctx.status_code == 200 and ctx.json()["site"]["id"] == site["id"], "scanner context via device token")
        check(anon.get("/api/scanner/context", headers={"X-Device-Token": "bogus"}).status_code == 401,
              "invalid device token rejected")
        # Short duplicate window is not needed; keep site default.

        # --- employees and permanent QR
        emps = {}
        for tag in ("A", "B"):
            r = admin.post("/api/employees", json={"employee_number": f"E2E-{run}-{tag}", "first_name": f"Test{tag}",
                                                   "last_name": "Synthetic", "site_ids": [site["id"]]})
            check(r.status_code == 201, f"create employee {tag}", r.text)
            emps[tag] = r.json()
        check(admin.post("/api/employees", json={"employee_number": f"E2E-{run}-A", "first_name": "x",
                                                 "last_name": "y", "site_ids": [site["id"]]}).status_code == 409,
              "duplicate employee number rejected (409)")
        check(hr.post("/api/employees", json={"employee_number": f"E2E-{run}-Z", "first_name": "x", "last_name": "y",
                                              "site_ids": [site["id"]]}).status_code == 403,
              "hr cannot create employees (403)")
        png1 = admin.get(f"/api/employees/{emps['A']['id']}/qr.png")
        png2 = admin.get(f"/api/employees/{emps['A']['id']}/qr.png")
        check(png1.status_code == 200 and png1.content[:8] == b"\x89PNG\r\n\x1a\n", "QR PNG download is a PNG")
        check(png1.content == png2.content, "QR reprint is byte-identical (permanent credential)")
        pdf = admin.get(f"/api/employees/{emps['A']['id']}/qr.pdf")
        check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", "QR badge PDF download")
        tok = {t: qr_payload(e["id"]) for t, e in emps.items()}

        # --- online scanning: employee A
        seq = 0

        def body(token, captured, mode="online", client_uuid=None):
            nonlocal seq
            seq += 1
            return {"client_uuid": client_uuid or str(uuid.uuid4()), "device_sequence": seq, "token": token,
                    "captured_at": iso(captured), "capture_mode": mode}

        r = anon.post("/api/attendance/scan", headers=dh, json=body(tok["A"], now))
        check(r.status_code == 201 and r.json()["outcome"] == "accepted" and r.json()["direction"] == "IN",
              "first scan is accepted as IN", r.text)
        check("token" not in r.text, "scan response does not echo the QR token")
        r = anon.post("/api/attendance/scan", headers=dh, json=body(tok["A"], now))
        check(r.status_code == 200 and r.json()["outcome"] == "duplicate", "immediate rescan is a duplicate", r.text)
        r = anon.post("/api/attendance/scan", headers=dh, json=body("not-a-real-token", now))
        check(r.status_code == 200 and r.json()["outcome"] == "rejected", "unknown QR token rejected", r.text)
        replay = body(tok["A"], now)
        first = anon.post("/api/attendance/scan", headers=dh, json=replay)
        again = anon.post("/api/attendance/scan", headers=dh, json=replay)
        check(again.status_code == 200 and again.json()["outcome"] == "replay", "exact client_uuid replay is idempotent",
              again.text)
        del first
        onsite = admin.get(f"/api/attendance/on-site?site_id={site['id']}").json()
        check(any(i.get("employee_number") == emps["A"]["employee_number"] or
                  i.get("employee", {}).get("employee_number") == emps["A"]["employee_number"]
                  for i in onsite["items"]), "employee A appears on the live on-site list", str(onsite)[:300])

        # --- offline-style batch with replay: employee B (IN 8h ago, OUT 1h ago)
        t_in, t_out = now - timedelta(hours=8), now - timedelta(hours=1)
        batch = [body(tok["B"], t_in, "offline"), body(tok["B"], t_out, "offline")]
        r = anon.post("/api/attendance/sync", headers=dh, json={"items": list(reversed(batch))})
        res = r.json().get("results", []) if r.status_code == 200 else []
        check(r.status_code == 200 and [x["outcome"] for x in res] == ["accepted", "accepted"] and
              [x["direction"] for x in res] == ["IN", "OUT"], "sync batch processed in sequence order IN then OUT", r.text)
        r = anon.post("/api/attendance/sync", headers=dh, json={"items": batch})
        check(r.status_code == 200 and all(x["outcome"] == "replay" for x in r.json()["results"]),
              "replayed sync batch creates no duplicates", r.text)
        events = admin.get(f"/api/attendance/events?employee_id={emps['B']['id']}").json()["items"]
        check(len(events) == 2, "exactly two events stored for employee B", str(len(events)))
        onsite = admin.get(f"/api/attendance/on-site?site_id={site['id']}").json()
        check(not any(emps["B"]["employee_number"] in str(i) for i in onsite["items"]),
              "employee B (signed out) is not on site")

        # --- daily hours and session
        sess_id = None
        for day_offset in (0, 1):  # B's IN may fall on the previous local date near midnight
            day = (t_in + timedelta(hours=2)).date() - timedelta(days=0 if day_offset == 0 else 1)
            daily = admin.get(f"/api/attendance/daily?site_id={site['id']}&date={day.isoformat()}").json()
            rows = [e for e in daily["employees"] if e["employee_number"] == emps["B"]["employee_number"]]
            if rows:
                break
        check(bool(rows) and abs(rows[0]["total_hours"] - 7.0) < 0.05, "daily hours for B about 7.00",
              str(rows)[:300])
        sess = rows[0]["sessions"][0]
        sess_id = sess["id"]

        # --- audited correction
        new_out = iso(t_out - timedelta(hours=1))
        r = sup.post(f"/api/attendance/sessions/{sess_id}/corrections",
                     json={"field": "out", "new_value": new_out, "reason": "", "expected_version": 1})
        check(r.status_code == 422, "correction without a reason is rejected (422)", r.text)
        r = hr.post(f"/api/attendance/sessions/{sess_id}/corrections",
                    json={"field": "out", "new_value": new_out, "reason": "x", "expected_version": 1})
        check(r.status_code == 403, "hr cannot correct (403)")
        r = sup.post(f"/api/attendance/sessions/{sess_id}/corrections",
                     json={"field": "out", "new_value": new_out, "reason": "E2E: forgot to scan out", "expected_version": 1})
        check(r.status_code == 201 and r.json()["version"] == 2 and r.json()["corrected"], "supervisor correction applied",
              r.text)
        r = sup.post(f"/api/attendance/sessions/{sess_id}/corrections",
                     json={"field": "out", "new_value": new_out, "reason": "stale", "expected_version": 1})
        check(r.status_code == 409, "stale expected_version rejected (409)", r.text)
        detail = admin.get(f"/api/attendance/sessions/{sess_id}").json()
        check(abs(detail["hours"] - 6.0) < 0.05 and len(detail["corrections"]) == 1 and
              detail["corrections"][0]["actor"] == "supervisor" and
              detail["out_event"]["occurred_at"][:19] == iso(t_out)[:19],
              "history lists correction; original OUT event unchanged; hours now 6.00", str(detail)[:400])
        hist = admin.get(f"/api/attendance/sessions/{sess_id}/corrections").json()["items"]
        check(len(hist) == 1 and hist[0]["reason"] == "E2E: forgot to scan out", "correction history endpoint")

        # --- CSV
        d_from = (t_in - timedelta(days=1)).date().isoformat()
        d_to = (now + timedelta(days=1)).date().isoformat()
        r = hr.get(f"/api/reports/attendance.csv?from={d_from}&to={d_to}&site_id={site['id']}")
        check(r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), "CSV export", r.text[:200])
        parsed = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
        mine = [x for x in parsed if x["employee_number"] == emps["B"]["employee_number"]]
        check(len(mine) == 1 and mine[0]["hours"] == "6.00" and mine[0]["corrected"] == "yes",
              "CSV row for B parsed (6.00 h, corrected=yes)", str(mine))

        # --- inactive employee rejected
        admin.post(f"/api/employees/{emps['A']['id']}/deactivate")
        r = anon.post("/api/attendance/scan", headers=dh, json=body(tok["A"], now + timedelta(seconds=1)))
        check(r.json().get("outcome") == "rejected" and r.json().get("reason") == "inactive_employee",
              "deactivated employee scan rejected")
        admin.post(f"/api/employees/{emps['A']['id']}/activate")

        admin.post("/api/auth/logout")
        check(admin.get("/api/auth/me").status_code == 401, "logout invalidates session")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\nSummary: {passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

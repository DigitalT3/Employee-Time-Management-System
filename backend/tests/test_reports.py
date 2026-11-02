"""VAL-06: CSV export parse, open-session blanks and formula escaping."""
import csv
import io
from datetime import datetime, timezone

from app.services.reports import escape_cell

UTC = timezone.utc


def test_csv_export(world, scanner, admin, hr, fake_clock):
    admin.patch(f"/api/employees/{world['employee']['id']}", json={"first_name": "=HYPERLINK(1)"})
    fake_clock.set(datetime(2026, 3, 2, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 2, 15, 30, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 3, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    r = hr.get("/api/reports/attendance.csv", params={"from": "2026-03-01", "to": "2026-03-03"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("\ufeff")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    assert len(rows) == 2
    assert rows[0]["in_local"] == "2026-03-02 08:00:00" and rows[0]["hours"] == "8.50"
    assert rows[0]["first_name"] == "'=HYPERLINK(1)"
    assert rows[1]["out_local"] == "" and rows[1]["hours"] == ""
    assert admin.get("/api/reports/attendance.csv", params={"from": "2026-03-05", "to": "2026-03-01"}).status_code == 422


def test_escape_cell():
    assert escape_cell("-1") == "'-1" and escape_cell("abc") == "abc" and escape_cell(None) == ""

"""Reports: daily/weekly previews, export periods, delimiters and appended columns (FR-12, DEC-11)."""
import csv
import io
from datetime import datetime, timezone

UTC = timezone.utc


def _worked_day(world, scanner, fake_clock, day: int):
    fake_clock.set(datetime(2026, 3, day, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, day, 15, 30, tzinfo=UTC))
    scanner.scan(world["qr"])


def test_daily_and_weekly_preview(world, scanner, hr, fake_clock):
    """Daily covers one shift date; weekly the ISO week Monday to Sunday, with totals."""
    _worked_day(world, scanner, fake_clock, 2)   # Monday
    _worked_day(world, scanner, fake_clock, 8)   # Sunday of the same ISO week
    _worked_day(world, scanner, fake_clock, 9)   # next Monday
    daily = hr.get("/api/reports/daily", params={"date": "2026-03-02"}).json()
    assert daily["period"] == "daily" and daily["summary"]["sessions"] == 1
    assert daily["summary"]["completed_minutes"] == 510 and daily["rows"][0]["duration_hhmm"] == "8:30"
    weekly = hr.get("/api/reports/weekly", params={"date": "2026-03-05"}).json()
    assert (weekly["from"], weekly["to"]) == ("2026-03-02", "2026-03-08") and weekly["summary"]["sessions"] == 2
    assert weekly["duration_label"] == "attendance_duration_not_paid_time"


def test_export_period_delimiter_and_columns(world, scanner, supervisor, fake_clock):
    """Legacy columns keep their order, new ones are appended; delimiter and period are honoured."""
    _worked_day(world, scanner, fake_clock, 2)
    fake_clock.set(datetime(2026, 3, 3, 7, 0, tzinfo=UTC))
    scanner.scan(world["qr"])
    fake_clock.set(datetime(2026, 3, 3, 12, 0, tzinfo=UTC))
    response = supervisor.get("/api/reports/export", params={"period": "weekly", "date": "2026-03-03", "delimiter": "semicolon"})
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
    assert rows[0][:10] == ["employee_number", "first_name", "last_name", "site_code", "shift_date",
                            "in_local", "out_local", "hours", "corrected", "missing_out"]
    assert rows[0][10:] == ["site_name", "duration_hhmm", "status", "flags", "offline"]
    assert len(rows) == 3 and rows[1][12] == "complete" and rows[2][12] == "open"
    tab = supervisor.get("/api/reports/export", params={"date": "2026-03-02", "delimiter": "tab"}).content.decode()
    assert "\t" in tab.splitlines()[0]
    assert supervisor.get("/api/reports/export", params={"delimiter": "pipe"}).status_code == 422
    assert supervisor.get("/api/reports/export", params={"from": "2026-03-05", "to": "2026-03-01"}).status_code == 422

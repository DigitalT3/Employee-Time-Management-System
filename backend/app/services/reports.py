"""Attendance reports (FR-12): one row per effective session, formula-escaped CSV with UTF-8 BOM.

Durations are attendance durations (OUT minus IN), not paid working time.
"""
import csv
import io
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.errors import ApiError
from app.models import AttendanceSession, Employee, Site
from app.services.sessions import (
    Policy, duration_minutes, hours, is_missing_out, load_capture_modes, session_flags, session_status,
    local_today,
)
from app.timeutil import local_iso

# Existing columns keep their order; new columns are appended (DEC-11).
HEADER = ["employee_number", "first_name", "last_name", "site_code", "shift_date", "in_local", "out_local",
          "hours", "corrected", "missing_out",
          "site_name", "duration_hhmm", "status", "flags", "offline"]
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t", ",": ",", ";": ";"}
MAX_RANGE_DAYS = 366


# PUBLIC_INTERFACE
def escape_cell(value) -> str:
    """Neutralise spreadsheet formula injection by prefixing risky text with an apostrophe."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_DANGEROUS) else s


# PUBLIC_INTERFACE
def resolve_delimiter(name: str | None) -> str:
    """Map a delimiter name (comma, semicolon, tab) to its character; 422 for anything else."""
    if name is None or name == "":
        return ","
    try:
        return DELIMITERS[name]
    except KeyError:
        raise ApiError(422, "invalid_delimiter", "delimiter must be comma, semicolon or tab")


# PUBLIC_INTERFACE
def resolve_period(db: Session, site_id: uuid.UUID | None, period: str | None, anchor: date | None,
                   date_from: date | None, date_to: date | None) -> tuple[str, date, date]:
    """Resolve the inclusive shift-date range and its label.

    Explicit ``from``/``to`` win ("range"); otherwise ``weekly`` is the ISO week (Monday to
    Sunday) containing the anchor and ``daily`` is the anchor day. The anchor defaults to
    today in the site's local time zone.
    """
    if date_from or date_to:
        start = date_from or date_to
        end = date_to or date_from
        label = "range"
    else:
        day = anchor or local_today(db, site_id)
        if period == "weekly":
            start = day - timedelta(days=day.weekday())
            end = start + timedelta(days=6)
            label = "weekly"
        else:
            start = end = day
            label = "daily"
    if end < start:
        raise ApiError(422, "invalid_range", "'to' must not be before 'from'")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(422, "range_too_large", "Range is limited to 366 days")
    return label, start, end


def _hhmm(minutes: int | None) -> str:
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


# PUBLIC_INTERFACE
def report_rows(db: Session, site_id: uuid.UUID | None, date_from: date, date_to: date,
                employee_id: uuid.UUID | None = None) -> list[dict]:
    """Return one dict per session whose shift date lies in [date_from, date_to]."""
    now, policy = clock.now(), Policy(db)
    q = (select(AttendanceSession, Employee, Site)
         .join(Employee, Employee.id == AttendanceSession.employee_id)
         .join(Site, Site.id == AttendanceSession.site_id)
         .where(AttendanceSession.shift_date >= date_from, AttendanceSession.shift_date <= date_to)
         .order_by(AttendanceSession.shift_date, Employee.employee_number, AttendanceSession.effective_in))
    if site_id:
        q = q.where(AttendanceSession.site_id == site_id)
    if employee_id:
        q = q.where(AttendanceSession.employee_id == employee_id)
    found = db.execute(q).all()
    modes = load_capture_modes(db, [s for s, _, _ in found])
    rows = []
    for s, e, site in found:
        tz = policy.get(s.site_id)[0]
        h = hours(s)
        flags = session_flags(s, policy, now, modes)
        rows.append({
            "employee_number": e.employee_number, "first_name": e.first_name, "last_name": e.last_name,
            "site_code": site.code, "site_name": site.name, "shift_date": s.shift_date.isoformat(),
            "in_local": s.effective_in.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"),
            "out_local": s.effective_out.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if s.effective_out else "",
            "in_iso": local_iso(s.effective_in, tz), "out_iso": local_iso(s.effective_out, tz),
            "hours": f"{h:.2f}" if h is not None else "",
            "duration_minutes": duration_minutes(s),
            "duration_hhmm": _hhmm(duration_minutes(s)),
            "corrected": "yes" if s.version > 1 else "no",
            "missing_out": "yes" if is_missing_out(s, policy, now) else "no",
            "status": session_status(s, policy, now),
            "flags": flags,
            "offline": "yes" if "offline_capture" in flags else "no",
            "session_id": str(s.id),
        })
    return rows


# PUBLIC_INTERFACE
def summarize(rows: list[dict]) -> dict:
    """Return totals for a report preview: sessions, completed minutes and incomplete count."""
    minutes = sum(r["duration_minutes"] or 0 for r in rows)
    return {
        "sessions": len(rows),
        "completed_minutes": minutes,
        "completed_hours": round(minutes / 60, 2),
        "incomplete": sum(1 for r in rows if r["status"] != "complete"),
        "missing_out": sum(1 for r in rows if r["status"] == "missing_out"),
    }


# PUBLIC_INTERFACE
def attendance_csv(db: Session, site_id: uuid.UUID | None, date_from: date, date_to: date,
                   employee_id: uuid.UUID | None = None, delimiter: str = ",") -> str:
    """Build the CSV text (with BOM) for sessions whose shift date lies in [date_from, date_to]."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    w.writerow(HEADER)
    for r in report_rows(db, site_id, date_from, date_to, employee_id):
        values = {**r, "flags": "|".join(r["flags"])}
        w.writerow([escape_cell(values[column]) for column in HEADER])
    return "\ufeff" + buf.getvalue()

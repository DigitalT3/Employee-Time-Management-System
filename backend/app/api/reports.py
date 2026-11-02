"""Report endpoints (FR-12): legacy CSV, daily and weekly previews, and the export."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models import User
from app.services import audit
from app.services.reports import (
    attendance_csv, report_rows, resolve_delimiter, resolve_period, summarize,
)

router = APIRouter(prefix="/reports", tags=["reports"])

_ROW_HIDDEN = {"in_iso", "out_iso"}


def _csv_response(db: Session, user: User, label: str, start: date, end: date, site_id, employee_id,
                  delimiter: str) -> Response:
    text = attendance_csv(db, site_id, start, end, employee_id, delimiter)
    audit.record(db, user.id, "report.export", "report", "attendance.csv",
                 {"period": label, "from": start.isoformat(), "to": end.isoformat(),
                  "site_id": str(site_id) if site_id else None,
                  "employee_id": str(employee_id) if employee_id else None})
    db.commit()
    name = f"attendance_{start.isoformat()}_{end.isoformat()}.csv"
    return Response(content=text.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


def _preview(db: Session, period: str, site_id, employee_id, day: date | None) -> dict:
    label, start, end = resolve_period(db, site_id, period, day, None, None)
    rows = report_rows(db, site_id, start, end, employee_id)
    return {"period": label, "from": start.isoformat(), "to": end.isoformat(),
            "site_id": str(site_id) if site_id else None,
            "employee_id": str(employee_id) if employee_id else None,
            "duration_label": "attendance_duration_not_paid_time",
            "summary": summarize(rows), "rows": [{k: v for k, v in r.items() if k not in _ROW_HIDDEN} for r in rows]}


# PUBLIC_INTERFACE
@router.get("/daily", summary="Daily attendance report (JSON preview)",
            description="One row per session for the shift date (default: today at the site) with totals.")
def daily_report(site_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None,
                 day: date | None = Query(None, alias="date"), db: Session = Depends(get_db),
                 _: User = Depends(require_permission("reports.export"))):
    """Return the daily report rows and summary."""
    return _preview(db, "daily", site_id, employee_id, day)


# PUBLIC_INTERFACE
@router.get("/weekly", summary="Weekly attendance report (JSON preview)",
            description="One row per session for the ISO week (Monday to Sunday) containing the date.")
def weekly_report(site_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None,
                  day: date | None = Query(None, alias="date"), db: Session = Depends(get_db),
                  _: User = Depends(require_permission("reports.export"))):
    """Return the weekly report rows and summary."""
    return _preview(db, "weekly", site_id, employee_id, day)


# PUBLIC_INTERFACE
@router.get("/export", summary="Export attendance CSV", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}},
            description="Explicit from/to win; otherwise period=daily|weekly around date (default: site-local today). "
                        "delimiter is comma, semicolon or tab. Excel-compatible UTF-8 with BOM.")
def export(period: str | None = Query(None, pattern="^(daily|weekly)$"), day: date | None = Query(None, alias="date"),
           date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
           site_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None,
           delimiter: str | None = Query(None), db: Session = Depends(get_db),
           user: User = Depends(require_permission("reports.export"))):
    """Download the attendance CSV for the resolved period."""
    char = resolve_delimiter(delimiter)
    label, start, end = resolve_period(db, site_id, period, day, date_from, date_to)
    return _csv_response(db, user, label, start, end, site_id, employee_id, char)


# PUBLIC_INTERFACE
@router.get("/attendance.csv", summary="Export attendance CSV (legacy route)", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}},
            description="One row per effective session in the inclusive shift-date range; open sessions have blank OUT/hours.")
def export_csv(date_from: date = Query(..., alias="from"), date_to: date = Query(..., alias="to"),
               site_id: uuid.UUID | None = None, employee_id: uuid.UUID | None = None,
               delimiter: str | None = Query(None), db: Session = Depends(get_db),
               user: User = Depends(require_permission("reports.export"))):
    """Download the attendance CSV for an explicit range."""
    char = resolve_delimiter(delimiter)
    label, start, end = resolve_period(db, site_id, None, None, date_from, date_to)
    return _csv_response(db, user, label, start, end, site_id, employee_id, char)

"""Site time zone helpers: local formatting, day bounds and DST-aware parsing (DEC-07)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.errors import ApiError

UTC = timezone.utc


# PUBLIC_INTERFACE
def local_iso(value: datetime | None, tz: ZoneInfo) -> str | None:
    """Format an instant as an offset-aware ISO string in the site's time zone."""
    return value.astimezone(tz).isoformat(timespec="seconds") if value else None


# PUBLIC_INTERFACE
def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC instants of a site-local calendar day."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


# PUBLIC_INTERFACE
def parse_local_value(value: datetime, tz: ZoneInfo) -> datetime:
    """Interpret a correction input in the site zone.

    Offset-aware values are used as given. A naive value is a site-local wall-clock time:
    a time skipped by a spring-forward gap raises ``nonexistent_local_time`` and a time that
    occurs twice at a fall-back transition raises ``ambiguous_local_time`` so the caller
    must supply an explicit offset.
    """
    if value.tzinfo is not None:
        return value
    outcomes = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=tz, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
        outcomes.append((candidate, round_trip == value))
    if not any(ok for _, ok in outcomes):
        raise ApiError(422, "nonexistent_local_time",
                       "That local time does not exist at the site because of a daylight-saving change")
    if all(ok for _, ok in outcomes) and outcomes[0][0].utcoffset() != outcomes[1][0].utcoffset():
        raise ApiError(422, "ambiguous_local_time",
                       "That local time occurs twice at the site; supply an explicit UTC offset")
    return next(candidate for candidate, ok in outcomes if ok)

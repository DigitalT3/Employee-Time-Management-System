"""Injectable UTC clock so attendance rules can be tested with controlled time."""
from collections.abc import Callable
from datetime import datetime, timezone

_override: Callable[[], datetime] | None = None


# PUBLIC_INTERFACE
def now() -> datetime:
    """Return the current timezone-aware UTC time (or the test override)."""
    return _override() if _override else datetime.now(timezone.utc)


# PUBLIC_INTERFACE
def set_now(fn: Callable[[], datetime] | None) -> None:
    """Override the clock with a callable (None restores the real clock)."""
    global _override
    _override = fn

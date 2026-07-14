from datetime import datetime, timezone

from domain.ports.clock import ClockPort


class SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now()

    def utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

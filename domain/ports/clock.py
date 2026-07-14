from typing import Protocol
from datetime import datetime


class ClockPort(Protocol):
    def now(self) -> datetime:
        ...

    def utc_now(self) -> datetime:
        ...

from uuid import UUID
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from domain.entities.signal import Signal


class SignalRepositoryPort(Protocol):
    async def save(self, signal: Signal) -> None:
        ...

    async def get(self, signal_id: UUID) -> Signal | None:
        ...

    async def list_by_strategy(
        self, strategy_id: UUID, limit: int = 100
    ) -> Sequence[Signal]:
        ...

    async def list_since(self, since: datetime, limit: int = 100) -> Sequence[Signal]:
        ...

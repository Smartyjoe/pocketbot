from uuid import UUID
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from domain.entities.trade import Trade


class TradeRepositoryPort(Protocol):
    async def save(self, trade: Trade) -> None:
        ...

    async def get(self, trade_id: UUID) -> Trade | None:
        ...

    async def list_by_strategy(
        self, strategy_id: UUID, limit: int = 100
    ) -> Sequence[Trade]:
        ...

    async def list_open(self) -> Sequence[Trade]:
        ...

    async def list_since(self, since: datetime, limit: int = 100) -> Sequence[Trade]:
        ...

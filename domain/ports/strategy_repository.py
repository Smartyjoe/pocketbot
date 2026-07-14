from uuid import UUID
from collections.abc import Sequence
from typing import Protocol

from domain.entities.strategy import Strategy


class StrategyRepositoryPort(Protocol):
    async def save(self, strategy: Strategy) -> None:
        ...

    async def get(self, strategy_id: UUID) -> Strategy | None:
        ...

    async def list_active(self) -> Sequence[Strategy]:
        ...

    async def list_all(self) -> Sequence[Strategy]:
        ...

    async def get_by_name(self, name: str) -> Strategy | None:
        ...

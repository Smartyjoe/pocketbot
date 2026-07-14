from typing import Protocol
from datetime import datetime
from decimal import Decimal

from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money


class BrokerPort(Protocol):
    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def is_connected(self) -> bool:
        ...

    async def get_balance(self) -> Money:
        ...

    async def place_trade(
        self,
        symbol: Symbol,
        direction: Direction,
        amount: Money,
        duration_seconds: int,
    ) -> str:
        ...

    async def get_current_price(self, symbol: Symbol) -> Decimal:
        ...

    async def subscribe_candles(
        self,
        symbol: Symbol,
        timeframe_seconds: int,
    ) -> None:
        ...

    async def get_available_assets(self) -> list[Symbol]:
        ...

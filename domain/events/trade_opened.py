from uuid import UUID
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from domain.events.base import DomainEvent
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money


class TradeOpened(DomainEvent):
    trade_id: UUID
    signal_id: UUID | None = None
    strategy_id: UUID | None = None
    symbol: Symbol
    direction: Direction
    amount: Money
    entry_price: Decimal
    expires_at: datetime
    broker_trade_id: str = ""

from uuid import UUID
from decimal import Decimal

from domain.events.base import DomainEvent
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money


class TradeExpired(DomainEvent):
    trade_id: UUID
    symbol: Symbol
    direction: Direction
    entry_price: Decimal
    exit_price: Decimal
    result: str  # "win" | "loss" | "draw"
    profit_loss: Money

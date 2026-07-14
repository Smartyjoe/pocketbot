from uuid import UUID, uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money


class TradeStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"


class TradeResult(Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"
    PENDING = "pending"


@dataclass
class Trade:
    trade_id: UUID
    signal_id: UUID | None
    strategy_id: UUID | None
    symbol: Symbol
    direction: Direction
    amount: Money
    entry_price: Decimal
    expires_at: datetime
    status: TradeStatus
    result: TradeResult
    profit_loss: Money
    broker_trade_id: str
    opened_at: datetime
    closed_at: datetime | None

    @classmethod
    def open(
        cls,
        symbol: Symbol,
        direction: Direction,
        amount: Money,
        entry_price: Decimal,
        expires_at: datetime,
        signal_id: UUID | None = None,
        strategy_id: UUID | None = None,
        broker_trade_id: str = "",
    ) -> "Trade":
        return cls(
            trade_id=uuid4(),
            signal_id=signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            amount=amount,
            entry_price=entry_price,
            expires_at=expires_at,
            status=TradeStatus.OPEN,
            result=TradeResult.PENDING,
            profit_loss=Money(amount="0"),
            broker_trade_id=broker_trade_id,
            opened_at=datetime.now(timezone.utc),
            closed_at=None,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def close(self, exit_price: Decimal, payout_rate: Decimal = Decimal("0.85")) -> None:
        if self.status == TradeStatus.CLOSED:
            raise ValueError("Trade already closed")
        self.status = TradeStatus.CLOSED
        self.closed_at = datetime.now(timezone.utc)

        if self.direction == Direction.CALL:
            won = exit_price > self.entry_price
        elif self.direction == Direction.PUT:
            won = exit_price < self.entry_price
        else:
            won = False

        if exit_price == self.entry_price:
            self.result = TradeResult.DRAW
            self.profit_loss = Money(amount="0")
        elif won:
            self.result = TradeResult.WIN
            win_amount = self.amount.amount * payout_rate
            self.profit_loss = Money(amount=win_amount)
        else:
            self.result = TradeResult.LOSS
            self.profit_loss = -self.amount

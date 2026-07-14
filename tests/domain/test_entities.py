import pytest
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from domain.entities.signal import Signal
from domain.entities.trade import Trade, TradeStatus, TradeResult
from domain.entities.strategy import Strategy
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence
from domain.value_objects.money import Money


@pytest.fixture
def symbol() -> Symbol:
    return Symbol(code="EURUSD_otc")


@pytest.fixture
def strategy_id() -> UUID:
    return uuid4()


class TestSignal:
    def test_create(self, symbol: Symbol, strategy_id: UUID) -> None:
        sig = Signal.create(
            strategy_id=strategy_id,
            symbol=symbol,
            direction=Direction.CALL,
            confidence=Confidence(score=0.82),
            candle_timestamp=datetime.now(timezone.utc),
        )
        assert isinstance(sig.signal_id, UUID)
        assert sig.strategy_id == strategy_id
        assert sig.direction == Direction.CALL
        assert bool(sig.confidence) is True
        assert sig.is_approved is False

    def test_approve(self, symbol: Symbol, strategy_id: UUID) -> None:
        sig = Signal.create(
            strategy_id=strategy_id,
            symbol=symbol,
            direction=Direction.CALL,
            confidence=Confidence(score=0.82),
            candle_timestamp=datetime.now(timezone.utc),
        )
        sig.approve()
        assert sig.is_approved is True

    def test_reject(self, symbol: Symbol, strategy_id: UUID) -> None:
        sig = Signal.create(
            strategy_id=strategy_id,
            symbol=symbol,
            direction=Direction.PUT,
            confidence=Confidence(score=0.3),
            candle_timestamp=datetime.now(timezone.utc),
        )
        sig.reject("low confidence")
        assert sig.is_approved is False
        assert sig.rejection_reason == "low confidence"


class TestTrade:
    def test_open(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.CALL,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        assert isinstance(t.trade_id, UUID)
        assert t.status == TradeStatus.OPEN
        assert t.result == TradeResult.PENDING
        assert t.closed_at is None

    def test_expired(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.CALL,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert t.is_expired() is True

    def test_not_expired(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.CALL,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        assert t.is_expired() is False

    def test_close_win_call(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.CALL,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        t.close(exit_price=Decimal("1.1060"))
        assert t.status == TradeStatus.CLOSED
        assert t.result == TradeResult.WIN
        assert t.profit_loss.amount == Decimal("8.50")

    def test_close_loss_put(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.PUT,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        t.close(exit_price=Decimal("1.1060"))
        assert t.status == TradeStatus.CLOSED
        assert t.result == TradeResult.LOSS
        assert t.profit_loss.amount == Decimal("-10.00")

    def test_close_twice_raises(self, symbol: Symbol) -> None:
        t = Trade.open(
            symbol=symbol,
            direction=Direction.CALL,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        t.close(exit_price=Decimal("1.1060"))
        with pytest.raises(ValueError, match="already closed"):
            t.close(exit_price=Decimal("1.1070"))


class TestStrategy:
    def test_create(self) -> None:
        s = Strategy.create(
            name="RSI_Scalper",
            parameters={"rsi_period": 14, "rsi_overbought": 70},
            version="1.0.0",
            description="RSI-based scalping",
        )
        assert isinstance(s.strategy_id, UUID)
        assert s.name == "RSI_Scalper"
        assert s.is_active is False

    def test_activate_deactivate(self) -> None:
        s = Strategy.create(name="Test")
        s.activate()
        assert s.is_active is True
        s.deactivate()
        assert s.is_active is False

    def test_record_result(self) -> None:
        s = Strategy.create(name="Test")
        s.record_result(won=True)
        s.record_result(won=False)
        s.record_result(won=True)
        assert s.live_total_trades == 3
        assert s.live_wins == 2
        assert s.live_win_rate == 2 / 3

from uuid import uuid4
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from domain.events.signal_generated import SignalGenerated
from domain.events.trade_opened import TradeOpened
from domain.events.trade_expired import TradeExpired
from domain.events.balance_changed import BalanceChanged
from domain.events.broker_status import BrokerConnected, BrokerDisconnected, BrokerError
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence
from domain.value_objects.money import Money


class TestEvents:
    def test_signal_generated(self) -> None:
        event = SignalGenerated(
            signal_id=uuid4(),
            strategy_id=uuid4(),
            symbol=Symbol(code="EURUSD"),
            direction=Direction.CALL,
            confidence=Confidence(score=0.85),
            feature_values={"rsi": 30.0},
            candle_timestamp=datetime.now(timezone.utc),
            model_version="1.0.0",
        )
        assert event.event_id is not None
        assert event.occurred_at is not None
        assert event.direction == Direction.CALL

    def test_trade_opened(self) -> None:
        event = TradeOpened(
            trade_id=uuid4(),
            symbol=Symbol(code="EURUSD"),
            direction=Direction.PUT,
            amount=Money(amount="10"),
            entry_price=Decimal("1.1050"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        assert event.direction == Direction.PUT

    def test_trade_expired_win(self) -> None:
        event = TradeExpired(
            trade_id=uuid4(),
            symbol=Symbol(code="EURUSD"),
            direction=Direction.CALL,
            entry_price=Decimal("1.1050"),
            exit_price=Decimal("1.1060"),
            result="win",
            profit_loss=Money(amount="8.50"),
        )
        assert event.result == "win"

    def test_balance_changed(self) -> None:
        event = BalanceChanged(
            old_balance=Money(amount="100"),
            new_balance=Money(amount="108.50"),
        )
        assert event.new_balance.amount == Decimal("108.50")

    def test_broker_status_events(self) -> None:
        connected = BrokerConnected()
        assert connected.event_id is not None

        disconnected = BrokerDisconnected(reconnect_attempt=1, next_attempt_in=10.0)
        assert disconnected.reconnect_attempt == 1

        error = BrokerError(error_code="AUTH_FAILED", message="SSID expired")
        assert error.error_code == "AUTH_FAILED"

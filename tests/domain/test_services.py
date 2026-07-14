import pytest
from uuid import uuid4
from datetime import datetime, timezone

from domain.entities.signal import Signal
from domain.services.signal_evaluator import SignalEvaluator
from domain.services.risk_calculator import RiskCalculator
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence
from domain.value_objects.money import Money


@pytest.fixture
def symbol() -> Symbol:
    return Symbol(code="EURUSD_otc")


class TestSignalEvaluator:
    def test_approves_high_confidence(self, symbol: Symbol) -> None:
        sig = Signal.create(
            strategy_id=uuid4(),
            symbol=symbol,
            direction=Direction.CALL,
            confidence=Confidence(score=0.82),
            candle_timestamp=datetime.now(timezone.utc),
        )
        evaluator = SignalEvaluator()
        assert evaluator.evaluate(sig) is True
        assert sig.is_approved is True

    def test_rejects_low_confidence(self, symbol: Symbol) -> None:
        sig = Signal.create(
            strategy_id=uuid4(),
            symbol=symbol,
            direction=Direction.CALL,
            confidence=Confidence(score=0.4),
            candle_timestamp=datetime.now(timezone.utc),
        )
        evaluator = SignalEvaluator()
        assert evaluator.evaluate(sig, min_confidence=0.6) is False
        assert sig.is_approved is False
        assert "below minimum" in sig.rejection_reason


class TestRiskCalculator:
    def test_normal_stake(self) -> None:
        rc = RiskCalculator()
        stake = rc.calculate_stake(
            confidence_score=0.82,
            current_balance=Money(amount="100"),
            consecutive_losses=0,
            daily_loss=Money(amount="0"),
        )
        assert stake.amount > 0
        expected = Money(amount="2.64")
        assert stake == expected

    def test_zero_stake_when_daily_loss_reached(self) -> None:
        rc = RiskCalculator()
        stake = rc.calculate_stake(
            confidence_score=0.9,
            current_balance=Money(amount="100"),
            consecutive_losses=0,
            daily_loss=Money(amount="50"),
        )
        assert stake.amount == 0

    def test_zero_stake_when_consecutive_losses_reached(self) -> None:
        rc = RiskCalculator()
        stake = rc.calculate_stake(
            confidence_score=0.9,
            current_balance=Money(amount="100"),
            consecutive_losses=3,
            daily_loss=Money(amount="0"),
        )
        assert stake.amount == 0

    def test_should_stop_daily_loss(self) -> None:
        rc = RiskCalculator()
        stop, reason = rc.should_stop_trading(
            consecutive_losses=2,
            daily_loss=Money(amount="60"),
        )
        assert stop is True
        assert "loss limit" in reason

    def test_should_stop_consecutive_losses(self) -> None:
        rc = RiskCalculator()
        stop, reason = rc.should_stop_trading(
            consecutive_losses=3,
            daily_loss=Money(amount="10"),
        )
        assert stop is True
        assert "consecutive" in reason

    def test_no_stop(self) -> None:
        rc = RiskCalculator()
        stop, reason = rc.should_stop_trading(
            consecutive_losses=0,
            daily_loss=Money(amount="10"),
        )
        assert stop is False
        assert reason == ""

    def test_custom_daily_loss_limit(self) -> None:
        rc = RiskCalculator()
        stop, reason = rc.should_stop_trading(
            consecutive_losses=0,
            daily_loss=Money(amount="30"),
            daily_loss_limit=Money(amount="25"),
        )
        assert stop is True

import pytest
from decimal import Decimal

from domain.value_objects.symbol import Symbol
from domain.value_objects.money import Money, CurrencyMismatchError
from domain.value_objects.timeframe import Timeframe
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence, ConfidenceLabel


class TestSymbol:
    def test_creation(self) -> None:
        s = Symbol(code="EURUSD_otc")
        assert s.code == "EURUSD_OTC"
        assert s.broker_name == "pocketoption"

    def test_empty_code(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Symbol(code="  ")

    def test_hashable(self) -> None:
        s1 = Symbol(code="EURUSD")
        s2 = Symbol(code="EURUSD")
        assert {s1, s2} == {s1}

    def test_immutable(self) -> None:
        s = Symbol(code="BTCUSD")
        with pytest.raises(ValueError):
            s.code = "ETHUSD"


class TestMoney:
    def test_creation(self) -> None:
        m = Money(amount="10.5")
        assert m.amount == Decimal("10.50")
        assert m.currency == "USD"

    def test_addition(self) -> None:
        a = Money(amount="10.00")
        b = Money(amount="5.50")
        assert (a + b).amount == Decimal("15.50")

    def test_subtraction(self) -> None:
        a = Money(amount="10.00")
        b = Money(amount="3.00")
        assert (a - b).amount == Decimal("7.00")

    def test_multiplication(self) -> None:
        m = Money(amount="5.00")
        assert (m * 3).amount == Decimal("15.00")

    def test_negation(self) -> None:
        m = Money(amount="10.00")
        assert (-m).amount == Decimal("-10.00")

    def test_abs(self) -> None:
        m = Money(amount="-10.00")
        assert abs(m).amount == Decimal("10.00")

    def test_currency_mismatch(self) -> None:
        usd = Money(amount="10.00", currency="USD")
        eur = Money(amount="10.00", currency="EUR")
        with pytest.raises(CurrencyMismatchError):
            usd + eur

    def test_comparisons(self) -> None:
        m1 = Money(amount="10.00")
        m2 = Money(amount="5.00")
        assert m1 > m2
        assert m2 < m1
        assert m1 >= m2
        assert m1 >= Money(amount="10.00")
        assert not (m1 == m2)
        assert m1 == Money(amount="10.00")

    def test_is_positive(self) -> None:
        assert Money(amount="5.00").is_positive()
        assert not Money(amount="0.00").is_positive()
        assert not Money(amount="-5.00").is_positive()

    def test_is_zero(self) -> None:
        assert Money(amount="0.00").is_zero()
        assert not Money(amount="0.01").is_zero()

    def test_as_float(self) -> None:
        assert Money(amount="10.50").as_float() == 10.5


class TestTimeframe:
    def test_valid_timeframes(self) -> None:
        assert Timeframe(seconds=60).seconds == 60
        assert Timeframe(seconds=300).seconds == 300

    def test_invalid_timeframe(self) -> None:
        with pytest.raises(ValueError, match="not supported"):
            Timeframe(seconds=33)

    def test_to_timedelta(self) -> None:
        from datetime import timedelta
        assert Timeframe(seconds=300).to_timedelta() == timedelta(minutes=5)

    def test_str(self) -> None:
        assert str(Timeframe(seconds=60)) == "1m"
        assert str(Timeframe(seconds=5)) == "5s"


class TestDirection:
    def test_from_str_call(self) -> None:
        assert Direction.from_str("call") == Direction.CALL
        assert Direction.from_str("C") == Direction.CALL

    def test_from_str_put(self) -> None:
        assert Direction.from_str("put") == Direction.PUT
        assert Direction.from_str("P") == Direction.PUT

    def test_from_str_invalid(self) -> None:
        assert Direction.from_str("invalid") == Direction.INVALID

    def test_opposite(self) -> None:
        assert Direction.CALL.opposite == Direction.PUT
        assert Direction.PUT.opposite == Direction.CALL
        assert Direction.INVALID.opposite == Direction.INVALID


class TestConfidence:
    def test_high(self) -> None:
        c = Confidence(score=0.9)
        assert c.label == ConfidenceLabel.HIGH
        assert bool(c) is True

    def test_medium(self) -> None:
        c = Confidence(score=0.7)
        assert c.label == ConfidenceLabel.MEDIUM
        assert bool(c) is True

    def test_low(self) -> None:
        c = Confidence(score=0.3)
        assert c.label == ConfidenceLabel.LOW
        assert bool(c) is False
        assert not c

    def test_invalid_range(self) -> None:
        with pytest.raises(ValueError, match="0, 1"):
            Confidence(score=1.5)
        with pytest.raises(ValueError, match="0, 1"):
            Confidence(score=-0.1)

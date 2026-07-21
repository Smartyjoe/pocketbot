import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from application.use_cases.trading import TradingUseCase
from domain.entities.strategy import Strategy
from domain.entities.trade import Trade, TradeStatus, TradeResult
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money
from domain.services.risk_calculator import RiskCalculator
from domain.services.signal_evaluator import SignalEvaluator
from domain.events.trade_expired import TradeExpired


@pytest.fixture
def mock_broker():
    broker = AsyncMock()
    broker.get_balance.return_value = Money(amount="1000")
    broker.place_trade.return_value = "broker_trade_123"
    broker.get_current_price.return_value = Money(amount="1.1000")
    return broker


@pytest.fixture
def mock_event_bus():
    return AsyncMock()


@pytest.fixture
def mock_strategy_repo():
    repo = AsyncMock()
    strategy = Strategy.create(
        name="test_strategy",
        parameters={"threshold": 0.7},
        version="1.0.0",
    )
    strategy.activate()
    repo.get.return_value = strategy
    repo.list_active.return_value = [strategy]
    repo.list_all.return_value = [strategy]
    return repo


@pytest.fixture
def mock_signal_repo():
    repo = AsyncMock()
    repo.list_since.return_value = []
    return repo


@pytest.fixture
def mock_trade_repo():
    repo = AsyncMock()
    repo.list_open.return_value = []
    repo.list_since.return_value = []
    return repo


@pytest.fixture
def risk_calculator():
    return RiskCalculator(
        max_daily_loss=Money(amount="50"),
        max_consecutive_losses=3,
        base_stake=Money(amount="2"),
        max_stake=Money(amount="10"),
    )


@pytest.fixture
def signal_evaluator():
    return SignalEvaluator()


@pytest.fixture
def trading_uc(
    mock_broker,
    mock_event_bus,
    mock_strategy_repo,
    mock_signal_repo,
    mock_trade_repo,
    risk_calculator,
    signal_evaluator,
):
    return TradingUseCase(
        broker=mock_broker,
        event_bus=mock_event_bus,
        strategy_repo=mock_strategy_repo,
        signal_repo=mock_signal_repo,
        trade_repo=mock_trade_repo,
        risk_calculator=risk_calculator,
        signal_evaluator=signal_evaluator,
    )


@pytest.mark.asyncio
async def test_process_signal_rejected_low_confidence(trading_uc, mock_signal_repo):
    result = await trading_uc.process_signal(
        strategy_id=uuid4(),
        symbol_code="EURUSD_otc",
        direction_str="call",
        confidence_score=0.3,
        feature_values={"rsi": 0.3},
        candle_timestamp=datetime.now(timezone.utc),
    )

    assert result is None
    mock_signal_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_process_signal_success(trading_uc, mock_signal_repo, mock_trade_repo):
    strategy = await trading_uc._strategy_repo.get(uuid4())
    result = await trading_uc.process_signal(
        strategy_id=strategy.strategy_id,
        symbol_code="EURUSD_otc",
        direction_str="call",
        confidence_score=0.85,
        feature_values={"rsi": 0.85},
        candle_timestamp=datetime.now(timezone.utc),
    )

    assert result is not None
    assert result.symbol.code == "EURUSD_OTC"
    assert result.direction.value == "call"
    mock_signal_repo.save.assert_called_once()
    mock_trade_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_manual_trade(trading_uc):
    trade = await trading_uc.manual_trade(
        symbol_code="EURUSD_otc",
        direction_str="put",
        amount=Decimal("10"),
    )

    assert trade.symbol.code == "EURUSD_OTC"
    assert trade.direction.value == "put"
    assert trade.amount == Money(amount="10")


@pytest.mark.asyncio
async def test_get_open_trades(trading_uc, mock_trade_repo):
    trades = await trading_uc.get_open_trades()
    assert trades == []
    mock_trade_repo.list_open.assert_called_once()


def _make_open_trade(expires_in_seconds: int = -10) -> Trade:
    """Create a trade that is either open or expired."""
    now = datetime.now(timezone.utc)
    return Trade.open(
        symbol=Symbol(code="EURUSD_otc"),
        direction=Direction.CALL,
        amount=Money(amount="5"),
        entry_price=Decimal("1.1000"),
        expires_at=now + timedelta(seconds=expires_in_seconds),
        broker_trade_id="broker_001",
    )


@pytest.mark.asyncio
async def test_settle_expired_trades_winning(trading_uc, mock_trade_repo, mock_broker):
    """Expired CALL trade where exit > entry → WIN."""
    trade = _make_open_trade(expires_in_seconds=-5)
    mock_trade_repo.list_open.return_value = [trade]
    mock_broker.get_current_price.return_value = Decimal("1.1050")

    settled = await trading_uc.settle_expired_trades()

    assert len(settled) == 1
    assert settled[0].result == TradeResult.WIN
    assert settled[0].status == TradeStatus.CLOSED
    assert settled[0].profit_loss.amount > 0
    mock_trade_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_settle_expired_trades_losing(trading_uc, mock_trade_repo, mock_broker):
    """Expired CALL trade where exit < entry → LOSS."""
    trade = _make_open_trade(expires_in_seconds=-5)
    mock_trade_repo.list_open.return_value = [trade]
    mock_broker.get_current_price.return_value = Decimal("1.0950")

    settled = await trading_uc.settle_expired_trades()

    assert len(settled) == 1
    assert settled[0].result == TradeResult.LOSS
    assert settled[0].profit_loss.amount < 0


@pytest.mark.asyncio
async def test_settle_expired_trades_skips_non_expired(trading_uc, mock_trade_repo):
    """Non-expired trades should not be settled."""
    trade = _make_open_trade(expires_in_seconds=60)
    mock_trade_repo.list_open.return_value = [trade]

    settled = await trading_uc.settle_expired_trades()

    assert len(settled) == 0


@pytest.mark.asyncio
async def test_settle_expired_trades_publishes_events(trading_uc, mock_trade_repo, mock_broker, mock_event_bus):
    """Settled trades should emit TradeExpired events."""
    trade = _make_open_trade(expires_in_seconds=-5)
    mock_trade_repo.list_open.return_value = [trade]
    mock_broker.get_current_price.return_value = Decimal("1.1050")

    await trading_uc.settle_expired_trades()

    mock_event_bus.publish.assert_called_once()
    event = mock_event_bus.publish.call_args[0][0]
    assert isinstance(event, TradeExpired)
    assert event.result == "win"


@pytest.mark.asyncio
async def test_settle_empty_open_list(trading_uc, mock_trade_repo):
    """No open trades → nothing to settle."""
    mock_trade_repo.list_open.return_value = []

    settled = await trading_uc.settle_expired_trades()

    assert settled == []

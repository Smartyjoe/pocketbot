import pytest
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timezone

from interfaces.telegram.notifications import TelegramNotifier
from domain.events.trade_opened import TradeOpened
from domain.events.trade_expired import TradeExpired
from domain.events.balance_changed import BalanceChanged
from domain.events.broker_status import BrokerConnected, BrokerDisconnected, BrokerError
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    return bot


@pytest.fixture
def notifier(mock_bot):
    return TelegramNotifier(bot=mock_bot, admin_user_ids=[12345, 67890])


@pytest.mark.asyncio
async def test_on_trade_opened(notifier, mock_bot):
    event = TradeOpened(
        trade_id=uuid4(),
        symbol=Symbol(code="EURUSD_otc"),
        direction=Direction.CALL,
        amount=Money(amount="10"),
        entry_price=Decimal("1.1000"),
        expires_at=datetime.now(timezone.utc),
    )
    await notifier.on_trade_opened(event)
    assert mock_bot.send_message.call_count == 2
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "CALL" in text
    assert "EURUSD_OTC" in text


@pytest.mark.asyncio
async def test_on_trade_expired_win(notifier, mock_bot):
    event = TradeExpired(
        trade_id=uuid4(),
        symbol=Symbol(code="EURUSD_otc"),
        direction=Direction.CALL,
        entry_price=Decimal("1.1000"),
        exit_price=Decimal("1.1050"),
        result="win",
        profit_loss=Money(amount="8.50"),
    )
    await notifier.on_trade_expired(event)
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "WIN" in text
    assert "+8.50" in text


@pytest.mark.asyncio
async def test_on_trade_expired_loss(notifier, mock_bot):
    event = TradeExpired(
        trade_id=uuid4(),
        symbol=Symbol(code="EURUSD_otc"),
        direction=Direction.PUT,
        entry_price=Decimal("1.1000"),
        exit_price=Decimal("1.1050"),
        result="loss",
        profit_loss=Money(amount="-10.00"),
    )
    await notifier.on_trade_expired(event)
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "LOSS" in text
    assert "-10.00" in text


@pytest.mark.asyncio
async def test_on_balance_changed(notifier, mock_bot):
    event = BalanceChanged(
        old_balance=Money(amount="9000"),
        new_balance=Money(amount="9500"),
    )
    await notifier.on_balance_changed(event)
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "9500.00" in text


@pytest.mark.asyncio
async def test_on_broker_connected(notifier, mock_bot):
    await notifier.on_broker_connected(BrokerConnected())
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "CONNECTED" in text


@pytest.mark.asyncio
async def test_on_broker_disconnected(notifier, mock_bot):
    event = BrokerDisconnected(next_attempt_in=15.0)
    await notifier.on_broker_disconnected(event)
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "DISCONNECTED" in text
    assert "15" in text


@pytest.mark.asyncio
async def test_sends_to_all_admins(notifier, mock_bot):
    await notifier.on_broker_connected(BrokerConnected())
    chat_ids = [call.kwargs["chat_id"] for call in mock_bot.send_message.call_args_list]
    assert 12345 in chat_ids
    assert 67890 in chat_ids


@pytest.mark.asyncio
async def test_send_failure_does_not_raise(notifier, mock_bot):
    mock_bot.send_message.side_effect = Exception("Telegram API down")
    event = TradeOpened(
        trade_id=uuid4(),
        symbol=Symbol(code="EURUSD_otc"),
        direction=Direction.CALL,
        amount=Money(amount="5"),
        entry_price=Decimal("1.1000"),
        expires_at=datetime.now(timezone.utc),
    )
    await notifier.on_trade_opened(event)

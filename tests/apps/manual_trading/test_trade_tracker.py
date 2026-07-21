"""Tests for trade tracker."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.manual_trading.trade_tracker import TradeTracker, RESOLVE_GRACE_SECONDS


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_pending = AsyncMock(return_value=[])
    store.mark_result_requested = AsyncMock()
    return store


@pytest.fixture
def mock_get_price():
    return AsyncMock(return_value=Decimal("1.0855"))


@pytest.fixture
def mock_send_message():
    return AsyncMock()


@pytest.fixture
def tracker(mock_store, mock_get_price, mock_send_message):
    return TradeTracker(
        prediction_store=mock_store,
        get_price_fn=mock_get_price,
        send_message_fn=mock_send_message,
    )


class TestTradeTracker:
    def test_initial_state(self, tracker: TradeTracker) -> None:
        assert not tracker._running
        assert tracker._task is None

    @pytest.mark.asyncio
    async def test_check_pending_empty(self, tracker: TradeTracker, mock_store) -> None:
        """No pending predictions -- nothing happens."""
        await tracker._check_pending()
        mock_store.mark_result_requested.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pending_sends_result_request(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """Expired prediction with result_requested_at=None -- send result-request."""
        now = datetime.now(timezone.utc)
        prediction_id = uuid4()
        mock_store.get_pending.return_value = [
            {
                "id": prediction_id,
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            }
        ]

        await tracker._check_pending()

        mock_send_message.assert_called_once()
        call_args = mock_send_message.call_args
        assert call_args[0][0] == 123  # telegram_id
        assert "Trade Expired" in call_args[0][1]
        assert "Win" in str(call_args[1].get("reply_markup", ""))
        mock_store.mark_result_requested.assert_called_once_with(prediction_id)

    @pytest.mark.asyncio
    async def test_check_pending_sends_message_with_keyboard(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """Result-request includes inline keyboard with Win/Tie/Loss buttons."""
        now = datetime.now(timezone.utc)
        prediction_id = uuid4()
        mock_store.get_pending.return_value = [
            {
                "id": prediction_id,
                "telegram_id": 456,
                "symbol": "GBPUSD_otc",
                "timeframe_sec": 300,
                "direction": "put",
                "confidence": 0.82,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.2650,
                "entry_time": now - timedelta(seconds=300),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            }
        ]

        await tracker._check_pending()

        call_args = mock_send_message.call_args
        reply_markup = call_args[1]["reply_markup"]
        # Should have 3 buttons: Win, Tie, Loss
        assert len(reply_markup.inline_keyboard) == 1
        assert len(reply_markup.inline_keyboard[0]) == 3
        button_texts = [btn.text for btn in reply_markup.inline_keyboard[0]]
        assert any("Win" in t for t in button_texts)
        assert any("Tie" in t for t in button_texts)
        assert any("Loss" in t for t in button_texts)

    @pytest.mark.asyncio
    async def test_check_pending_multiple_expired(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """Multiple expired predictions all get result-request messages."""
        now = datetime.now(timezone.utc)
        id1 = uuid4()
        id2 = uuid4()
        mock_store.get_pending.return_value = [
            {
                "id": id1,
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            },
            {
                "id": id2,
                "telegram_id": 456,
                "symbol": "GBPUSD_otc",
                "timeframe_sec": 60,
                "direction": "put",
                "confidence": 0.82,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.2650,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            },
        ]

        await tracker._check_pending()

        assert mock_send_message.call_count == 2
        assert mock_store.mark_result_requested.call_count == 2

    @pytest.mark.asyncio
    async def test_within_grace_period_not_sent(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """Expired but within grace period -- should NOT send result-request yet."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": uuid4(),
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=3),
            }
        ]

        await tracker._check_pending()

        mock_send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pending_not_yet_expired(
        self, tracker: TradeTracker, mock_store
    ) -> None:
        """Prediction not yet expired -- skip it."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_store.get_pending.return_value = [
            {
                "id": uuid4(),
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": datetime.now(timezone.utc),
                "expiry_time": future,
            }
        ]

        await tracker._check_pending()

        mock_store.mark_result_requested.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_failure_does_not_crash(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """If sending the message fails, the tracker continues."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": uuid4(),
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            }
        ]
        mock_send_message.side_effect = Exception("Telegram API error")

        # Should not raise
        await tracker._check_pending()

        # mark_result_requested should NOT be called since send failed
        mock_store.mark_result_requested.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_period_exact_boundary(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """Exactly at expiry + grace boundary -- should send."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": uuid4(),
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS),
            }
        ]

        await tracker._check_pending()

        mock_send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_prediction_id_in_callback_data(
        self, tracker: TradeTracker, mock_store, mock_send_message
    ) -> None:
        """The result-request keyboard callback_data contains the prediction_id."""
        now = datetime.now(timezone.utc)
        prediction_id = uuid4()
        mock_store.get_pending.return_value = [
            {
                "id": prediction_id,
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "call",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            }
        ]

        await tracker._check_pending()

        call_args = mock_send_message.call_args
        reply_markup = call_args[1]["reply_markup"]
        # Check that callback_data contains the prediction_id
        for btn_row in reply_markup.inline_keyboard:
            for btn in btn_row:
                assert str(prediction_id) in btn.callback_data

"""Tests for trade tracker."""
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.manual_trading.trade_tracker import TradeTracker, CHECK_INTERVAL, RESOLVE_GRACE_SECONDS


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_pending = AsyncMock(return_value=[])
    store.resolve = AsyncMock()
    return store


@pytest.fixture
def mock_get_price():
    return AsyncMock(return_value=Decimal("1.0855"))


@pytest.fixture
def mock_notify():
    return AsyncMock()


@pytest.fixture
def tracker(mock_store, mock_get_price, mock_notify):
    return TradeTracker(
        prediction_store=mock_store,
        get_price_fn=mock_get_price,
        notify_fn=mock_notify,
    )


class TestTradeTracker:
    def test_initial_state(self, tracker: TradeTracker) -> None:
        assert not tracker._running
        assert tracker._task is None

    @pytest.mark.asyncio
    async def test_check_pending_empty(self, tracker: TradeTracker, mock_store) -> None:
        """No pending predictions — nothing happens."""
        await tracker._check_pending()
        mock_store.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pending_resolves_expired(
        self, tracker: TradeTracker, mock_store, mock_get_price, mock_notify
    ) -> None:
        """Expired prediction with price available — resolve as win/loss."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-1",
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
        mock_get_price.return_value = Decimal("1.0860")

        await tracker._check_pending()

        mock_store.resolve.assert_called_once()
        call_kwargs = mock_store.resolve.call_args[1]
        assert call_kwargs["result"] == "win"
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_pending_resolves_loss(
        self, tracker: TradeTracker, mock_store, mock_get_price
    ) -> None:
        """Expired prediction where price went down for a CALL — resolve as loss."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-2",
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
        mock_get_price.return_value = Decimal("1.0840")

        await tracker._check_pending()

        call_kwargs = mock_store.resolve.call_args[1]
        assert call_kwargs["result"] == "loss"

    @pytest.mark.asyncio
    async def test_check_pending_put_direction(
        self, tracker: TradeTracker, mock_store, mock_get_price
    ) -> None:
        """PUT direction — price going down is a win."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-3",
                "telegram_id": 123,
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "direction": "put",
                "confidence": 0.78,
                "reasoning": "test",
                "indicators": {},
                "entry_price": 1.0850,
                "entry_time": now - timedelta(seconds=60),
                "expiry_time": now - timedelta(seconds=RESOLVE_GRACE_SECONDS + 5),
            }
        ]
        mock_get_price.return_value = Decimal("1.0840")

        await tracker._check_pending()

        call_kwargs = mock_store.resolve.call_args[1]
        assert call_kwargs["result"] == "win"

    @pytest.mark.asyncio
    async def test_check_pending_price_unavailable(
        self, tracker: TradeTracker, mock_store, mock_get_price
    ) -> None:
        """Price unavailable — resolve as tie."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-4",
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
        mock_get_price.return_value = None

        await tracker._check_pending()

        call_kwargs = mock_store.resolve.call_args[1]
        assert call_kwargs["result"] == "tie"

    @pytest.mark.asyncio
    async def test_within_grace_period_not_resolved(
        self, tracker: TradeTracker, mock_store, mock_get_price
    ) -> None:
        """Expired but within grace period — should NOT be resolved yet."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-grace",
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
        mock_get_price.return_value = Decimal("1.0860")

        await tracker._check_pending()

        mock_store.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_pending_not_yet_expired(
        self, tracker: TradeTracker, mock_store
    ) -> None:
        """Prediction not yet expired — skip it."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-5",
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

        mock_store.resolve.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_price_is_tie(
        self, tracker: TradeTracker, mock_store, mock_get_price
    ) -> None:
        """Price exactly equals entry — resolve as tie."""
        now = datetime.now(timezone.utc)
        mock_store.get_pending.return_value = [
            {
                "id": "test-id-6",
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
        mock_get_price.return_value = Decimal("1.0850")

        await tracker._check_pending()

        call_kwargs = mock_store.resolve.call_args[1]
        assert call_kwargs["result"] == "tie"

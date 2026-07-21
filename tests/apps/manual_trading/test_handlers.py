"""Tests for Telegram command handlers."""
import unittest.mock

import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_callback_query(data: str, user_id: int = 12345):
    """Create a mock CallbackQuery with the given callback data."""
    query = AsyncMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.delete = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user = MagicMock()
    update.effective_user.id = user_id

    return update, query


def _make_update(user_id: int = 12345):
    """Create a mock Update with a message."""
    update = MagicMock()
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


def _make_context(**bot_data_extra):
    """Create a mock ContextTypes.DEFAULT_TYPE."""
    context = AsyncMock()
    context.bot_data = {}
    context.bot_data.update(bot_data_extra)
    context.user_data = {}
    return context


def _make_ohlcv_df(n: int = 20, seed: int = 42) -> pd.DataFrame:
    """Create synthetic OHLCV data for handler tests."""
    rng = np.random.default_rng(seed)
    close = 1.0850 + np.cumsum(rng.normal(0, 0.0003, n))
    high = close + rng.uniform(0.0001, 0.001, n)
    low = close - rng.uniform(0.0001, 0.001, n)
    opn = close + rng.normal(0, 0.0002, n)
    volume = rng.integers(1000, 50000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="1min")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestCallbackMode:
    @pytest.mark.asyncio
    async def test_quick_mode_shows_pair_selection(self) -> None:
        from apps.manual_trading.handlers import callback_mode

        update, query = _make_callback_query("mode:quick")
        context = _make_context()

        await callback_mode(update, context)

        query.edit_message_text.assert_called_once()
        msg = query.edit_message_text.call_args[0][0]
        assert "Quick Trade" in msg

    @pytest.mark.asyncio
    async def test_ai_mode_without_model(self) -> None:
        from apps.manual_trading.handlers import callback_mode

        update, query = _make_callback_query("mode:ai")
        context = _make_context(ml_model=None)

        await callback_mode(update, context)

        query.edit_message_text.assert_called_once()
        msg = query.edit_message_text.call_args[0][0]
        assert "Model Not Available" in msg

    @pytest.mark.asyncio
    async def test_ai_mode_with_model_sets_flag(self) -> None:
        from apps.manual_trading.handlers import callback_mode

        update, query = _make_callback_query("mode:ai")
        ml_model = MagicMock()
        ml_model.is_trained = True
        context = _make_context(ml_model=ml_model)

        await callback_mode(update, context)

        assert context.user_data.get("ai_mode") is True
        query.edit_message_text.assert_called_once()
        msg = query.edit_message_text.call_args[0][0]
        assert "AI Analysis" in msg

    @pytest.mark.asyncio
    async def test_non_mode_prefix_ignored(self) -> None:
        from apps.manual_trading.handlers import callback_mode

        update, query = _make_callback_query("pair:EURUSD_otc")
        context = _make_context()

        await callback_mode(update, context)

        query.edit_message_text.assert_not_called()


class TestCmdPredict:
    @pytest.mark.asyncio
    async def test_shows_trade_mode_keyboard(self) -> None:
        from apps.manual_trading.handlers import cmd_predict

        update = _make_update()
        context = _make_context()
        store = MagicMock()
        store.has_pending_result = AsyncMock(return_value=False)
        context.bot_data["prediction_store"] = store

        await cmd_predict(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "trading mode" in msg.lower() or "Choose" in msg

    @pytest.mark.asyncio
    async def test_blocked_when_pending_result(self) -> None:
        from apps.manual_trading.handlers import cmd_predict

        update = _make_update()
        context = _make_context()
        store = MagicMock()
        store.has_pending_result = AsyncMock(return_value=True)
        context.bot_data["prediction_store"] = store

        await cmd_predict(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "report the result" in msg.lower()


class TestHasPendingResult:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_store(self) -> None:
        from apps.manual_trading.handlers import _has_pending_result

        context = _make_context()
        result = await _has_pending_result(context, 12345)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_pending(self) -> None:
        from apps.manual_trading.handlers import _has_pending_result

        store = MagicMock()
        store.has_pending_result = AsyncMock(return_value=False)
        context = _make_context(prediction_store=store)

        result = await _has_pending_result(context, 12345)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_pending(self) -> None:
        from apps.manual_trading.handlers import _has_pending_result

        store = MagicMock()
        store.has_pending_result = AsyncMock(return_value=True)
        context = _make_context(prediction_store=store)

        result = await _has_pending_result(context, 12345)
        assert result is True


class TestStoreTrainingData:
    @pytest.mark.asyncio
    async def test_stores_feature_snapshot(self) -> None:
        from apps.manual_trading.handlers import _store_training_data

        store = MagicMock()
        store.insert = AsyncMock()
        context = _make_context(training_data_store=store)

        await _store_training_data(
            context=context,
            symbol="EURUSD_otc",
            timeframe_sec=60,
            direction="call",
            entry_price=1.0852,
            features={"rsi": 28.0, "macd_hist": 0.001},
            win_probability=0.72,
        )

        store.insert.assert_called_once_with(
            symbol="EURUSD_otc",
            timeframe_sec=60,
            direction="call",
            entry_price=1.0852,
            features={"rsi": 28.0, "macd_hist": 0.001},
            win_probability=0.72,
        )

    @pytest.mark.asyncio
    async def test_silently_fails_without_store(self) -> None:
        from apps.manual_trading.handlers import _store_training_data

        context = _make_context()

        # Should not raise
        await _store_training_data(
            context=context,
            symbol="EURUSD_otc",
            timeframe_sec=60,
            direction="call",
            entry_price=1.0852,
            features={"rsi": 28.0},
            win_probability=0.72,
        )

    @pytest.mark.asyncio
    async def test_silently_fails_on_store_error(self) -> None:
        from apps.manual_trading.handlers import _store_training_data

        store = MagicMock()
        store.insert = AsyncMock(side_effect=Exception("DB error"))
        context = _make_context(training_data_store=store)

        # Should not raise
        await _store_training_data(
            context=context,
            symbol="EURUSD_otc",
            timeframe_sec=60,
            direction="call",
            entry_price=1.0852,
            features={"rsi": 28.0},
            win_probability=0.72,
        )


class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_blocks_same_pair_within_window(self) -> None:
        """After a signal, the same pair is blocked for COOLDOWN_BARS."""
        from apps.manual_trading.handlers import _handle_quick_duration
        from apps.manual_trading.constants import COOLDOWN_BARS

        # Build context with cooldown state
        context = _make_context()
        # df will have 20 rows, so current_bar = 19.
        # Set last_bar = 18 → difference = 1 < COOLDOWN_BARS (3) → blocked
        context.user_data["signal_cooldown"] = {"EURUSD_otc": 18}
        context.bot_data["broker"] = AsyncMock()
        context.bot_data["broker"].is_connected = AsyncMock(return_value=True)
        context.bot_data["market_data"] = AsyncMock()

        df = _make_ohlcv_df(20)
        context.bot_data["market_data"].request_candles = AsyncMock()
        context.bot_data["market_data"].get_candles = AsyncMock(return_value=df)

        update, query = _make_callback_query("dur:EURUSD_otc:60")

        await _handle_quick_duration(query, context, "EURUSD_otc", 60, 12345)

        # edit_message_text is called at least twice: "Analyzing..." + cooldown message
        # Check the LAST call is the cooldown message
        last_msg = query.edit_message_text.call_args_list[-1][0][0]
        assert "No clear signal" in last_msg
        assert "Cooldown" in last_msg or "cooldown" in last_msg.lower()

    @pytest.mark.asyncio
    async def test_cooldown_allows_after_window(self) -> None:
        """After COOLDOWN_BARS have passed, the pair can signal again."""
        from apps.manual_trading.handlers import _handle_quick_duration

        context = _make_context()
        # df will have 20 rows → current_bar = 19.
        # Set last_bar = 0 → difference = 19 >= COOLDOWN_BARS → allowed
        context.user_data["signal_cooldown"] = {"EURUSD_otc": 0}
        context.bot_data["broker"] = AsyncMock()
        context.bot_data["broker"].is_connected = AsyncMock(return_value=True)
        context.bot_data["market_data"] = AsyncMock()

        df = _make_ohlcv_df(20)
        context.bot_data["market_data"].request_candles = AsyncMock()
        context.bot_data["market_data"].get_candles = AsyncMock(return_value=df)

        update, query = _make_callback_query("dur:EURUSD_otc:60")

        # Mock generate_signal to return no signal so we don't need full broker flow
        with unittest.mock.patch(
            "apps.manual_trading.handlers.generate_signal"
        ) as mock_gen:
            mock_gen.return_value = MagicMock(
                has_signal=False,
                reasoning=["test"],
            )
            await _handle_quick_duration(query, context, "EURUSD_otc", 60, 12345)

        # Should NOT mention cooldown in the last message
        last_msg = query.edit_message_text.call_args_list[-1][0][0]
        assert "Cooldown" not in last_msg
        assert "cooldown" not in last_msg.lower()

    @pytest.mark.asyncio
    async def test_cooldown_state_set_after_successful_signal(self) -> None:
        """When a signal is produced, the cooldown dict is updated."""
        from apps.manual_trading.handlers import _handle_quick_duration

        context = _make_context()
        context.user_data["signal_cooldown"] = {}
        context.bot_data["broker"] = AsyncMock()
        context.bot_data["broker"].is_connected = AsyncMock(return_value=True)
        context.bot_data["market_data"] = AsyncMock()

        df = _make_ohlcv_df(20)
        context.bot_data["market_data"].request_candles = AsyncMock()
        context.bot_data["market_data"].get_candles = AsyncMock(return_value=df)

        update, query = _make_callback_query("dur:EURUSD_otc:60")

        mock_signal = MagicMock(
            has_signal=True,
            direction="call",
            confidence=0.80,
            reasoning=["Uptrend", "MACD confirmed"],
            indicators={"rsi": 45.0},
        )

        store = MagicMock()
        store.insert = AsyncMock()
        context.bot_data["prediction_store"] = store

        with unittest.mock.patch(
            "apps.manual_trading.handlers.generate_signal"
        ) as mock_gen:
            mock_gen.return_value = mock_signal
            with unittest.mock.patch(
                "apps.manual_trading.handlers.format_prediction_confirmed",
                return_value="confirmed",
            ):
                await _handle_quick_duration(query, context, "EURUSD_otc", 60, 12345)

        # Cooldown state should have been updated
        assert "EURUSD_otc" in context.user_data["signal_cooldown"]

    @pytest.mark.asyncio
    async def test_has_signal_false_shows_no_signal_message(self) -> None:
        """When signal.has_signal is False, user sees format_no_signal message."""
        from apps.manual_trading.handlers import _handle_quick_duration

        context = _make_context()
        context.user_data["signal_cooldown"] = {}
        context.bot_data["broker"] = AsyncMock()
        context.bot_data["broker"].is_connected = AsyncMock(return_value=True)
        context.bot_data["market_data"] = AsyncMock()

        df = _make_ohlcv_df(20)
        context.bot_data["market_data"].request_candles = AsyncMock()
        context.bot_data["market_data"].get_candles = AsyncMock(return_value=df)

        update, query = _make_callback_query("dur:EURUSD_otc:60")

        mock_signal = MagicMock(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=["No clear trend — EMA cross within dead zone"],
            indicators={},
        )

        with unittest.mock.patch(
            "apps.manual_trading.handlers.generate_signal"
        ) as mock_gen:
            mock_gen.return_value = mock_signal
            await _handle_quick_duration(query, context, "EURUSD_otc", 60, 12345)

        last_msg = query.edit_message_text.call_args_list[-1][0][0]
        assert "No clear signal" in last_msg

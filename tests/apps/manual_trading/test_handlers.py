"""Tests for Telegram command handlers."""
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

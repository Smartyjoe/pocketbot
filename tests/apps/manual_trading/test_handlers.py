"""Tests for Telegram command handlers."""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock


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


class TestCmdPredict:
    @pytest.mark.asyncio
    async def test_shows_pair_selection(self) -> None:
        from apps.manual_trading.handlers import cmd_predict

        update = _make_update()
        context = _make_context()

        await cmd_predict(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Choose" in msg


class TestCmdStats:
    @pytest.mark.asyncio
    async def test_stats_replies(self) -> None:
        from apps.manual_trading.handlers import cmd_stats

        store = MagicMock()
        store.get_user_stats = AsyncMock(return_value={
            "total": 10,
            "wins": 7,
            "losses": 3,
            "win_rate": 70.0,
            "by_symbol": [],
            "by_confidence": [],
        })
        context = _make_context(prediction_store=store)
        update = _make_update()

        await cmd_stats(update, context)

        update.message.reply_text.assert_called_once()


class TestCmdRecent:
    @pytest.mark.asyncio
    async def test_recent_replies(self) -> None:
        from apps.manual_trading.handlers import cmd_recent

        store = MagicMock()
        store.get_recent = AsyncMock(return_value=[])
        context = _make_context(prediction_store=store)
        update = _make_update()

        await cmd_recent(update, context)

        update.message.reply_text.assert_called_once()

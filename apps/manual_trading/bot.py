"""Telegram bot for manual trading mode."""
from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from apps.manual_trading.handlers import (
    cmd_start,
    cmd_help,
    cmd_predict,
    cmd_stats,
    cmd_recent,
    callback_pair,
    callback_duration,
    callback_result,
)

logger = logging.getLogger(__name__)


class ManualTradingBot:
    """Minimal Telegram bot for manual trading predictions."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._app: Application | None = None

    def build(self, **bot_data) -> Application:
        """Build the Telegram Application with all handlers."""
        self._app = (
            Application.builder()
            .token(self._bot_token)
            .build()
        )

        # Store shared resources in bot_data
        self._app.bot_data.update(bot_data)

        # Commands
        self._app.add_handler(CommandHandler("start", cmd_start))
        self._app.add_handler(CommandHandler("help", cmd_help))
        self._app.add_handler(CommandHandler("predict", cmd_predict))
        self._app.add_handler(CommandHandler("stats", cmd_stats))
        self._app.add_handler(CommandHandler("recent", cmd_recent))

        # Callback queries (inline keyboard buttons)
        self._app.add_handler(
            CallbackQueryHandler(callback_pair, pattern=r"^pair:")
        )
        self._app.add_handler(
            CallbackQueryHandler(callback_duration, pattern=r"^dur:")
        )
        self._app.add_handler(
            CallbackQueryHandler(callback_result, pattern=r"^result:")
        )

        return self._app

    async def set_commands(self) -> None:
        """Set the bot command menu in Telegram."""
        if self._app:
            commands = [
                BotCommand("predict", "Get a trading prediction"),
                BotCommand("stats", "Your trading statistics"),
                BotCommand("recent", "Recent predictions"),
                BotCommand("help", "Show help"),
            ]
            await self._app.bot.set_my_commands(commands)

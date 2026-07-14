"""Telegram notification handler — subscribes to domain events and pushes updates."""
import asyncio
from typing import Callable

import structlog
from telegram import Bot

from domain.events.base import DomainEvent
from domain.events.trade_opened import TradeOpened
from domain.events.trade_expired import TradeExpired
from domain.events.balance_changed import BalanceChanged
from domain.events.broker_status import BrokerConnected, BrokerDisconnected, BrokerError
from domain.events.signal_generated import SignalGenerated

logger = structlog.get_logger()


class TelegramNotifier:
    def __init__(self, bot: Bot, admin_user_ids: list[int]) -> None:
        self._bot = bot
        self._admin_ids = admin_user_ids

    async def _send(self, text: str) -> None:
        for uid in self._admin_ids:
            try:
                await self._bot.send_message(chat_id=uid, text=text)
            except Exception:
                logger.exception("telegram_send_failed", user_id=uid)

    async def on_trade_opened(self, event: DomainEvent) -> None:
        assert isinstance(event, TradeOpened)
        emoji = "CALL" if event.direction.value == "call" else "PUT"
        text = (
            f"TRADE OPENED\n"
            f"{emoji} {event.symbol.code}\n"
            f"Amount: {event.amount}\n"
            f"Entry: {event.entry_price}"
        )
        await self._send(text)

    async def on_trade_expired(self, event: DomainEvent) -> None:
        assert isinstance(event, TradeExpired)
        result_map = {"win": "WIN", "loss": "LOSS", "draw": "DRAW"}
        result_emoji = result_map.get(event.result, "?")
        text = (
            f"TRADE CLOSED — {result_emoji}\n"
            f"{event.symbol.code}\n"
            f"Entry: {event.entry_price} → Exit: {event.exit_price}\n"
            f"P&L: {event.profit_loss.amount:+.2f}"
        )
        await self._send(text)

    async def on_balance_changed(self, event: DomainEvent) -> None:
        assert isinstance(event, BalanceChanged)
        text = f"BALANCE: {event.new_balance}"
        await self._send(text)

    async def on_broker_connected(self, event: DomainEvent) -> None:
        await self._send("BROKER CONNECTED")

    async def on_broker_disconnected(self, event: DomainEvent) -> None:
        assert isinstance(event, BrokerDisconnected)
        text = f"BROKER DISCONNECTED — reconnect in {event.next_attempt_in:.0f}s"
        await self._send(text)

    async def on_broker_error(self, event: DomainEvent) -> None:
        assert isinstance(event, BrokerError)
        text = f"BROKER ERROR: {event.error_code} — {event.message}"
        await self._send(text)

    async def on_signal_generated(self, event: DomainEvent) -> None:
        assert isinstance(event, SignalGenerated)
        emoji = "CALL" if event.direction.value == "call" else "PUT"
        text = (
            f"SIGNAL: {emoji} {event.symbol.code}\n"
            f"Confidence: {event.confidence.score:.0%}"
        )
        await self._send(text)

"""Trade tracker — monitors pending predictions and sends result request.

Runs as a background asyncio task. When a prediction expires, it sends
the user a message with Win / Tie / Loss buttons. The user must tap one
before any other bot actions are allowed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from apps.manual_trading.database import PredictionStore
from apps.manual_trading.keyboards import result_feedback_keyboard
from apps.manual_trading.messages import format_result_request

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5  # seconds between checks
RESOLVE_GRACE_SECONDS = 8


class TradeTracker:
    """Monitors pending predictions and requests user feedback on expiry."""

    def __init__(
        self,
        prediction_store: PredictionStore,
        get_price_fn,
        send_message_fn,
    ) -> None:
        self._store = prediction_store
        self._get_price = get_price_fn
        self._send_message = send_message_fn
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background tracker loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("trade_tracker_started")

    def stop(self) -> None:
        """Stop the background tracker loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("trade_tracker_stopped")

    async def _loop(self) -> None:
        """Main loop: check for expired predictions and request results."""
        while self._running:
            try:
                await self._check_pending()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("trade_tracker_error")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_pending(self) -> None:
        """Find expired pending predictions and send result-request buttons."""
        now = datetime.now(timezone.utc)
        pending = await self._store.get_pending()

        for row in pending:
            expiry_time = row["expiry_time"]
            if expiry_time.tzinfo is None:
                expiry_time = expiry_time.replace(tzinfo=timezone.utc)

            if now < expiry_time:
                continue

            grace_expiry = expiry_time + timedelta(seconds=RESOLVE_GRACE_SECONDS)
            if now < grace_expiry:
                continue

            prediction_id = str(row["id"])
            telegram_id = row["telegram_id"]
            symbol = row["symbol"]
            direction = row["direction"]
            entry_price = float(row["entry_price"])
            timeframe_sec = row["timeframe_sec"]

            # Build the result-request message with Win/Tie/Loss buttons
            msg_text = format_result_request(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                timeframe_sec=timeframe_sec,
            )
            keyboard = result_feedback_keyboard(prediction_id)

            try:
                await self._send_message(
                    telegram_id,
                    msg_text,
                    reply_markup=keyboard,
                )
                logger.info(
                    "result_request_sent prediction_id=%s symbol=%s telegram_id=%s",
                    prediction_id,
                    symbol,
                    telegram_id,
                )
            except Exception:
                logger.exception(
                    "result_request_failed prediction_id=%s telegram_id=%s",
                    prediction_id,
                    telegram_id,
                )

"""Trade tracker — monitors pending predictions and resolves them.

Runs as a background asyncio task. Periodically checks the broker for
current prices of symbols with pending predictions, and resolves them
when their expiry time has passed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from apps.manual_trading.database import PredictionStore
from apps.manual_trading.models import PredictionResult

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 5  # seconds between checks
# Wait this many seconds after expiry before resolving, to let the price settle
# at the broker's actual closing price rather than a stale live tick.
RESOLVE_GRACE_SECONDS = 8


class TradeTracker:
    """Monitors pending predictions and resolves them when they expire."""

    def __init__(
        self,
        prediction_store: PredictionStore,
        get_price_fn,
        notify_fn,
    ) -> None:
        self._store = prediction_store
        self._get_price = get_price_fn
        self._notify = notify_fn
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
        """Main loop: check for expired predictions and resolve them."""
        while self._running:
            try:
                await self._check_pending()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("trade_tracker_error")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_pending(self) -> None:
        """Find expired pending predictions and resolve them."""
        now = datetime.now(timezone.utc)
        pending = await self._store.get_pending()

        for row in pending:
            expiry_time = row["expiry_time"]
            if expiry_time.tzinfo is None:
                expiry_time = expiry_time.replace(tzinfo=timezone.utc)

            if now < expiry_time:
                continue

            # Add a grace period after expiry so the broker's closing price
            # has time to propagate to our price feed.
            grace_expiry = expiry_time + timedelta(seconds=RESOLVE_GRACE_SECONDS)
            if now < grace_expiry:
                continue

            # Get current price
            symbol = row["symbol"]
            try:
                current_price = await self._get_price(symbol)
            except Exception:
                logger.warning("price_fetch_failed symbol=%s", symbol)
                current_price = None

            if current_price is None or current_price == 0:
                # Cannot determine outcome — mark as tie
                result = PredictionResult.TIE.value
                exit_price = Decimal("0")
                logger.warning(
                    "could_not_resolve_price prediction_id=%s symbol=%s",
                    str(row["id"]),
                    symbol,
                )
            else:
                entry_price = Decimal(str(row["entry_price"]))
                exit_price = current_price
                direction = row["direction"]

                # Use a small tolerance to avoid false results from
                # tiny price fluctuations at the exact expiry moment.
                diff = exit_price - entry_price
                # Tolerance: 0.05% of entry price (generous for OTC)
                tolerance = entry_price * Decimal("0.0005")

                if diff > tolerance:
                    won = direction == "call"
                elif diff < -tolerance:
                    won = direction == "put"
                else:
                    won = None  # within tolerance → tie

                if won is True:
                    result = PredictionResult.WIN.value
                elif won is False:
                    result = PredictionResult.LOSS.value
                else:
                    result = PredictionResult.TIE.value

                logger.info(
                    "trade_resolved prediction_id=%s symbol=%s "
                    "direction=%s entry=%s exit=%s diff=%s "
                    "tolerance=%s result=%s",
                    str(row["id"]), symbol, direction,
                    entry_price, exit_price, diff, tolerance, result,
                )

            # Update database
            await self._store.resolve(
                prediction_id=row["id"],
                exit_price=exit_price,
                result=result,
            )

            # Notify user
            telegram_id = row["telegram_id"]
            symbol_display = symbol.replace("_otc", " (OTC)").replace("_", "/")
            direction_emoji = "CALL" if row["direction"] == "call" else "PUT"

            if result == PredictionResult.WIN.value:
                status_line = f"WIN {direction_emoji} {symbol_display}"
            elif result == PredictionResult.LOSS.value:
                status_line = f"LOSS {direction_emoji} {symbol_display}"
            else:
                status_line = f"TIE {direction_emoji} {symbol_display}"

            entry = float(row["entry_price"])
            exit_p = float(exit_price)
            msg = (
                f"Prediction Result\n\n"
                f"{status_line}\n"
                f"Entry: {entry:.5f}\n"
                f"Exit: {exit_p:.5f}\n"
                f"Confidence: {row.get('confidence', 0):.0%}"
            )

            try:
                await self._notify(telegram_id, msg)
            except Exception:
                logger.exception("notify_failed telegram_id=%s", telegram_id)

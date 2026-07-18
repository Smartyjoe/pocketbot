"""Telegram command handlers for manual trading mode."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pandas as pd
from telegram import Update, CallbackQuery, InputFile
from telegram.ext import ContextTypes

# Resolve the assets directory once at import time
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_SIGNAL_IMAGES = {
    "call": _ASSETS_DIR / "buy.jpg",
    "put": _ASSETS_DIR / "sell.jpg",
}

from apps.manual_trading.constants import (
    POPULAR_PAIRS,
    CANDLES_NEEDED,
    min_candles_for_timeframe,
)
from apps.manual_trading.database import PredictionStore
from apps.manual_trading.keyboards import (
    pair_selection_keyboard,
    duration_selection_keyboard,
    result_feedback_keyboard,
)
from apps.manual_trading.market_data import MarketDataCollector
from apps.manual_trading.messages import (
    format_signal,
    format_prediction_confirmed,
    format_result_recorded,
    format_stats,
    format_recent,
)
from apps.manual_trading.models import Prediction
from apps.manual_trading.signal_generator import generate_signal
from infrastructure.features.indicators.technical import TechnicalIndicators

logger = logging.getLogger(__name__)

# Maximum time to wait for candle data (seconds)
CANDLE_WAIT_TIMEOUT = 15
CANDLE_POLL_INTERVAL = 0.5


async def _has_pending_result(context: ContextTypes.DEFAULT_TYPE, telegram_id: int) -> bool:
    """Return True if the user has an unresolved trade result waiting."""
    pending: set[int] = context.bot_data.get("pending_results", set())
    return telegram_id in pending


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if await _has_pending_result(context, update.effective_user.id):
        await update.message.reply_text(
            "\u26a0\ufe0f Please report the result of your last trade first.\n"
            "Tap Win, Tie, or Loss below that message before continuing."
        )
        return

    await update.message.reply_text(
        "\U0001f916 Manual Trading Bot\n\n"
        "Get AI-powered predictions for Pocket Option pairs.\n"
        "No account connection needed.\n\n"
        "Commands:\n"
        "/predict - Get a prediction\n"
        "/stats - Your trading stats\n"
        "/recent - Recent predictions\n"
        "/help - Show this message"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if await _has_pending_result(context, update.effective_user.id):
        await update.message.reply_text(
            "\u26a0\ufe0f Please report the result of your last trade first.\n"
            "Tap Win, Tie, or Loss below that message before continuing."
        )
        return

    await update.message.reply_text(
        "How it works:\n\n"
        "1. /predict - Choose a pair\n"
        "2. Pick a duration (1min, 5min, or 15min)\n"
        "3. Get a signal with direction and reasoning\n"
        "4. When the trade expires, report the result (Win/Tie/Loss)\n\n"
        "Commands:\n"
        "/predict - Get a prediction\n"
        "/stats - Your trading stats\n"
        "/recent - Recent predictions\n"
        "/help - Show this message"
    )


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /predict command — show pair selection keyboard."""
    if await _has_pending_result(context, update.effective_user.id):
        await update.message.reply_text(
            "\u26a0\ufe0f Please report the result of your last trade first.\n"
            "Tap Win, Tie, or Loss below that message before continuing."
        )
        return

    await update.message.reply_text(
        "Choose a trading pair:",
        reply_markup=pair_selection_keyboard(),
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command — show win rate and performance."""
    if await _has_pending_result(context, update.effective_user.id):
        await update.message.reply_text(
            "\u26a0\ufe0f Please report the result of your last trade first.\n"
            "Tap Win, Tie, or Loss below that message before continuing."
        )
        return

    store: PredictionStore = context.bot_data["prediction_store"]
    telegram_id = update.effective_user.id

    try:
        stats = await store.get_user_stats(telegram_id)
        await update.message.reply_text(format_stats(stats))
    except Exception:
        logger.exception("stats_error")
        await update.message.reply_text("Error loading stats. Please try again.")


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recent command — show recent predictions."""
    if await _has_pending_result(context, update.effective_user.id):
        await update.message.reply_text(
            "\u26a0\ufe0f Please report the result of your last trade first.\n"
            "Tap Win, Tie, or Loss below that message before continuing."
        )
        return

    store: PredictionStore = context.bot_data["prediction_store"]
    telegram_id = update.effective_user.id

    try:
        recent = await store.get_recent(telegram_id, limit=10)
        await update.message.reply_text(format_recent(recent))
    except Exception:
        logger.exception("recent_error")
        await update.message.reply_text("Error loading recent predictions.")


async def callback_pair(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pair selection callback — show duration options."""
    query: CallbackQuery = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("pair:"):
        return

    symbol = data.split(":", 1)[1]
    display = symbol.replace("_otc", " (OTC)").replace("_", "/")

    await query.edit_message_text(
        f"Selected: {display}\n\nChoose duration:",
        reply_markup=duration_selection_keyboard(symbol),
    )


async def callback_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle duration selection callback — generate signal and save prediction."""
    query: CallbackQuery = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("dur:"):
        return

    parts = data.split(":")
    symbol = parts[1]
    timeframe_sec = int(parts[2])
    telegram_id = update.effective_user.id

    # Show loading message
    await query.edit_message_text("\u23f3 Analyzing market conditions...")

    try:
        broker = context.bot_data["broker"]
        collector: MarketDataCollector = context.bot_data["market_data"]

        # Check broker connection
        if not await broker.is_connected():
            logger.warning("predict_broker_disconnected symbol=%s", symbol)
            await query.edit_message_text(
                "Broker not connected. Please wait a moment and try again.\n"
                "The bot is attempting to reconnect in the background."
            )
            return

        # Request candle history from broker
        await collector.request_candles(broker, symbol, timeframe_sec)

        # Wait for candle data to arrive
        df = await _wait_for_candles(collector, symbol, timeframe_sec, CANDLE_WAIT_TIMEOUT)

        min_candles = min_candles_for_timeframe(timeframe_sec)
        if df is None or len(df) < min_candles:
            logger.warning(
                "insufficient_candle_data symbol=%s count=%d needed=%d timeframe=%d known=%s",
                symbol,
                len(df) if df is not None else 0,
                min_candles,
                timeframe_sec,
                list(collector.get_all_prices().keys())[:5],
            )
            await query.edit_message_text(
                f"Insufficient market data ({len(df) if df is not None else 0}/{min_candles} candles).\n"
                f"The pair may not be available right now.\n"
                f"Try again in a moment or pick a different pair."
            )
            return

        # Compute indicators
        ti = TechnicalIndicators()
        df_with_indicators = ti.compute(df)

        # Generate signal
        signal = generate_signal(df_with_indicators)

        # Get current price
        price = await collector.get_latest_price(symbol)
        if price is None:
            # Use last close from candles
            entry_price_float = float(df.iloc[-1]["close"])
        else:
            entry_price_float = float(price)

        # Format signal text and send as a photo with caption
        signal_msg = format_signal(symbol, signal, entry_price_float)
        image_path = _SIGNAL_IMAGES.get(signal.direction)
        photo_sent = False
        if image_path and image_path.exists():
            try:
                with open(image_path, "rb") as photo_file:
                    await query.message.delete()
                    await context.bot.send_photo(
                        chat_id=telegram_id,
                        photo=InputFile(photo_file),
                        caption=signal_msg,
                    )
                photo_sent = True
            except Exception:
                logger.warning("signal_photo_send_failed direction=%s", signal.direction, exc_info=True)
        if not photo_sent:
            await query.edit_message_text(signal_msg)

        # Save prediction to database
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=timeframe_sec)
        from uuid import uuid4

        prediction = Prediction(
            id=uuid4(),
            telegram_id=telegram_id,
            symbol=symbol,
            timeframe_sec=timeframe_sec,
            direction=signal.direction,
            confidence=signal.confidence,
            reasoning="\n".join(signal.reasoning),
            indicators=signal.indicators,
            entry_price=Decimal(str(entry_price_float)),
            entry_time=now,
            expiry_time=expiry,
            result=None,
        )

        store: PredictionStore = context.bot_data["prediction_store"]
        await store.insert(prediction)

        # Send confirmation
        confirmation = format_prediction_confirmed(prediction)
        await context.bot.send_message(chat_id=telegram_id, text=confirmation)

    except Exception:
        logger.exception("predict_error")
        await query.edit_message_text(
            "Error generating prediction. Please try again."
        )


async def _wait_for_candles(
    collector: MarketDataCollector,
    symbol: str,
    timeframe_sec: int,
    timeout: float,
) -> pd.DataFrame | None:
    """Wait for candle data to arrive, polling periodically."""
    min_needed = min_candles_for_timeframe(timeframe_sec)
    deadline = asyncio.get_event_loop().time() + timeout
    attempts = 0
    while asyncio.get_event_loop().time() < deadline:
        df = await collector.get_candles(symbol)
        if df is not None and len(df) >= min_needed:
            logger.info(
                "candles_ready symbol=%s count=%d attempts=%d",
                symbol, len(df), attempts,
            )
            return df
        attempts += 1
        await asyncio.sleep(CANDLE_POLL_INTERVAL)

    # Return whatever we have, even if less than 30 candles
    df = await collector.get_candles(symbol)
    logger.warning(
        "candles_wait_timeout symbol=%s got=%d attempts=%d known=%s",
        symbol,
        len(df) if df is not None else 0,
        attempts,
        list(collector.get_all_prices().keys())[:10],
    )
    return df


async def callback_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Win / Tie / Loss button press after trade expiry."""
    query: CallbackQuery = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("result:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        return

    prediction_id = parts[1]
    result = parts[2]

    if result not in ("win", "tie", "loss"):
        return

    telegram_id = update.effective_user.id
    pending: set[int] = context.bot_data.get("pending_results", set())

    store: PredictionStore = context.bot_data["prediction_store"]

    try:
        from uuid import UUID

        await store.resolve(
            prediction_id=UUID(prediction_id),
            exit_price=Decimal("0"),
            result=result,
        )

        # Remove from pending set
        pending.discard(telegram_id)

        # Confirm to user
        await query.edit_message_text(text=format_result_recorded(result))

        logger.info(
            "result_submitted prediction_id=%s result=%s telegram_id=%s",
            prediction_id,
            result,
            telegram_id,
        )
    except Exception:
        logger.exception("result_callback_error")
        await query.edit_message_text(
            "Error recording result. Please try again."
        )

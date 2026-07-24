"""Telegram inline keyboards for the manual trading bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from apps.manual_trading.models import DURATION_OPTIONS
from apps.manual_trading.constants import (
    POPULAR_PAIRS,
    MIN_ASSET_PAYOUT_PCT,
    MAX_ASSET_PAYOUT_PCT,
)


def _normalize_payout(value: float) -> float:
    """Normalize payout to percentage (0-100) from either fraction or percent."""
    if value <= 1.0:
        return value * 100.0
    return value


def filter_assets_by_payout(
    pairs: list[str],
    payouts: dict[str, float],
    min_payout: float = MIN_ASSET_PAYOUT_PCT,
    max_payout: float = MAX_ASSET_PAYOUT_PCT,
) -> list[str]:
    """Filter asset pairs by payout percentage range.

    Assets without payout data are included (fail-open).
    """
    filtered: list[str] = []
    for pair in pairs:
        payout = payouts.get(pair)
        if payout is None:
            filtered.append(pair)
        else:
            normalized = _normalize_payout(payout)
            if min_payout <= normalized <= max_payout:
                filtered.append(pair)
    return filtered


def trade_mode_keyboard() -> InlineKeyboardMarkup:
    """Show trade mode selection: Quick Trade or AI Analysis."""
    buttons = [
        [
            InlineKeyboardButton(
                text="\u26a1 Quick Trade",
                callback_data="mode:quick",
            ),
        ],
        [
            InlineKeyboardButton(
                text="\U0001f916 AI Analysis",
                callback_data="mode:ai",
            ),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def pair_selection_keyboard(
    pairs: list[str] | None = None,
) -> InlineKeyboardMarkup:
    """Show trading pairs for the user to pick from."""
    pairs = POPULAR_PAIRS if pairs is None else pairs
    buttons = []
    row: list[InlineKeyboardButton] = []
    for i, pair in enumerate(pairs):
        display = pair.replace("_otc", " (OTC)").replace("_", "/")
        row.append(InlineKeyboardButton(text=display, callback_data=f"pair:{pair}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def duration_selection_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Show duration options for a chosen symbol."""
    buttons = [
        [
            InlineKeyboardButton(
                text=opt.label,
                callback_data=f"dur:{symbol}:{opt.seconds}",
            )
        ]
        for opt in DURATION_OPTIONS
    ]
    return InlineKeyboardMarkup(buttons)


def result_feedback_keyboard(prediction_id: str) -> InlineKeyboardMarkup:
    """Show Win / Tie / Loss buttons for a completed trade."""
    buttons = [
        [
            InlineKeyboardButton(
                text="\U0001f3c6 Win",
                callback_data=f"result:{prediction_id}:win",
            ),
            InlineKeyboardButton(
                text="\U0001f504 Tie",
                callback_data=f"result:{prediction_id}:tie",
            ),
            InlineKeyboardButton(
                text="\U0001f4c9 Loss",
                callback_data=f"result:{prediction_id}:loss",
            ),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

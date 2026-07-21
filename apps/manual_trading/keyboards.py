"""Telegram inline keyboards for the manual trading bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from apps.manual_trading.models import DURATION_OPTIONS
from apps.manual_trading.constants import POPULAR_PAIRS


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


def pair_selection_keyboard() -> InlineKeyboardMarkup:
    """Show popular trading pairs for the user to pick from."""
    buttons = []
    row: list[InlineKeyboardButton] = []
    for i, pair in enumerate(POPULAR_PAIRS):
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

"""Telegram inline keyboards for the manual trading bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from apps.manual_trading.models import DURATION_OPTIONS
from apps.manual_trading.constants import POPULAR_PAIRS


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

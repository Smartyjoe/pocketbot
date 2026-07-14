"""Tests for Telegram keyboards."""
import pytest

from apps.manual_trading.keyboards import (
    pair_selection_keyboard,
    duration_selection_keyboard,
)


class TestKeyboards:
    def test_pair_keyboard_has_buttons(self) -> None:
        kb = pair_selection_keyboard()
        assert len(kb.inline_keyboard) > 0
        # Each row should have up to 3 buttons
        for row in kb.inline_keyboard:
            assert len(row) <= 3

    def test_pair_keyboard_callback_data(self) -> None:
        kb = pair_selection_keyboard()
        first_button = kb.inline_keyboard[0][0]
        assert first_button.callback_data.startswith("pair:")

    def test_duration_keyboard_has_3_options(self) -> None:
        kb = duration_selection_keyboard("EURUSD_otc")
        assert len(kb.inline_keyboard) == 3

    def test_duration_keyboard_callback_data(self) -> None:
        kb = duration_selection_keyboard("EURUSD_otc")
        first_button = kb.inline_keyboard[0][0]
        assert first_button.callback_data == "dur:EURUSD_otc:60"

    def test_duration_keyboard_labels(self) -> None:
        kb = duration_selection_keyboard("EURUSD_otc")
        labels = [row[0].text for row in kb.inline_keyboard]
        assert "1 min" in labels
        assert "5 min" in labels
        assert "15 min" in labels

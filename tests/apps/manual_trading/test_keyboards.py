"""Tests for Telegram keyboards."""

from apps.manual_trading.keyboards import (
    pair_selection_keyboard,
    duration_selection_keyboard,
    trade_mode_keyboard,
    result_feedback_keyboard,
)


class TestKeyboards:
    def test_pair_keyboard_has_buttons(self) -> None:
        kb = pair_selection_keyboard()
        assert len(kb.inline_keyboard) > 0
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


class TestTradeModeKeyboard:
    def test_has_two_rows(self) -> None:
        kb = trade_mode_keyboard()
        assert len(kb.inline_keyboard) == 2

    def test_quick_trade_button(self) -> None:
        kb = trade_mode_keyboard()
        quick_btn = kb.inline_keyboard[0][0]
        assert quick_btn.callback_data == "mode:quick"
        assert "Quick Trade" in quick_btn.text

    def test_ai_analysis_button(self) -> None:
        kb = trade_mode_keyboard()
        ai_btn = kb.inline_keyboard[1][0]
        assert ai_btn.callback_data == "mode:ai"
        assert "AI Analysis" in ai_btn.text


class TestResultFeedbackKeyboard:
    def test_has_three_buttons(self) -> None:
        kb = result_feedback_keyboard("pred-123")
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 3

    def test_win_button_callback_data(self) -> None:
        kb = result_feedback_keyboard("pred-123")
        win_btn = kb.inline_keyboard[0][0]
        assert win_btn.callback_data == "result:pred-123:win"

    def test_tie_button_callback_data(self) -> None:
        kb = result_feedback_keyboard("pred-123")
        tie_btn = kb.inline_keyboard[0][1]
        assert tie_btn.callback_data == "result:pred-123:tie"

    def test_loss_button_callback_data(self) -> None:
        kb = result_feedback_keyboard("pred-123")
        loss_btn = kb.inline_keyboard[0][2]
        assert loss_btn.callback_data == "result:pred-123:loss"

    def test_button_labels(self) -> None:
        kb = result_feedback_keyboard("pred-123")
        texts = [btn.text for btn in kb.inline_keyboard[0]]
        assert any("Win" in t for t in texts)
        assert any("Tie" in t for t in texts)
        assert any("Loss" in t for t in texts)

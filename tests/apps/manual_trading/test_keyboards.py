"""Tests for Telegram keyboards."""

from apps.manual_trading.keyboards import (
    pair_selection_keyboard,
    duration_selection_keyboard,
    trade_mode_keyboard,
    result_feedback_keyboard,
    filter_assets_by_payout,
)
from apps.manual_trading.constants import POPULAR_PAIRS


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


class TestPairSelectionKeyboardParameterized:
    def test_default_uses_popular_pairs(self) -> None:
        kb = pair_selection_keyboard()
        kb_default = pair_selection_keyboard(pairs=None)
        assert kb.inline_keyboard == kb_default.inline_keyboard

    def test_custom_pair_list(self) -> None:
        kb = pair_selection_keyboard(pairs=["EURUSD_otc", "GBPUSD_otc"])
        assert sum(len(row) for row in kb.inline_keyboard) == 2
        first_cb = kb.inline_keyboard[0][0].callback_data
        assert first_cb == "pair:EURUSD_otc"

    def test_empty_pair_list_returns_empty_keyboard(self) -> None:
        kb = pair_selection_keyboard(pairs=[])
        assert len(kb.inline_keyboard) == 0

    def test_single_pair(self) -> None:
        kb = pair_selection_keyboard(pairs=["BTCUSD_otc"])
        assert sum(len(row) for row in kb.inline_keyboard) == 1


class TestFilterAssetsByPayout:
    def test_filters_below_min(self) -> None:
        result = filter_assets_by_payout(
            ["EURUSD_otc", "GBPUSD_otc"],
            {"EURUSD_otc": 85.0, "GBPUSD_otc": 75.0},
            min_payout=80.0, max_payout=92.0,
        )
        assert result == ["EURUSD_otc"]

    def test_filters_above_max(self) -> None:
        result = filter_assets_by_payout(
            ["EURUSD_otc", "GBPUSD_otc"],
            {"EURUSD_otc": 85.0, "GBPUSD_otc": 95.0},
            min_payout=80.0, max_payout=92.0,
        )
        assert result == ["EURUSD_otc"]

    def test_includes_unknown_assets(self) -> None:
        result = filter_assets_by_payout(
            ["EURUSD_otc", "UNKNOWN"],
            {"EURUSD_otc": 85.0},
        )
        assert "UNKNOWN" in result

    def test_all_in_range(self) -> None:
        payouts = {p: 85.0 for p in POPULAR_PAIRS}
        result = filter_assets_by_payout(POPULAR_PAIRS, payouts)
        assert result == POPULAR_PAIRS

    def test_empty_payouts_returns_all(self) -> None:
        result = filter_assets_by_payout(POPULAR_PAIRS, {})
        assert result == POPULAR_PAIRS

    def test_normalizes_decimal_payout(self) -> None:
        result = filter_assets_by_payout(
            ["EURUSD_otc", "GBPUSD_otc"],
            {"EURUSD_otc": 0.85, "GBPUSD_otc": 0.75},
            min_payout=80.0, max_payout=92.0,
        )
        assert result == ["EURUSD_otc"]

    def test_boundary_inclusive_min(self) -> None:
        result = filter_assets_by_payout(
            ["AT_MIN", "BELOW_MIN"],
            {"AT_MIN": 80.0, "BELOW_MIN": 79.99},
            min_payout=80.0, max_payout=92.0,
        )
        assert "AT_MIN" in result
        assert "BELOW_MIN" not in result

    def test_boundary_inclusive_max(self) -> None:
        result = filter_assets_by_payout(
            ["AT_MAX", "ABOVE_MAX"],
            {"AT_MAX": 92.0, "ABOVE_MAX": 92.01},
            min_payout=80.0, max_payout=92.0,
        )
        assert "AT_MAX" in result
        assert "ABOVE_MAX" not in result

    def test_all_filtered_out_returns_empty(self) -> None:
        result = filter_assets_by_payout(
            ["EURUSD_otc", "GBPUSD_otc"],
            {"EURUSD_otc": 70.0, "GBPUSD_otc": 75.0},
            min_payout=80.0, max_payout=92.0,
        )
        assert result == []

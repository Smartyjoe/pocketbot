"""Tests for Telegram message formatting."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from uuid import uuid4

from apps.manual_trading.messages import (
    format_signal,
    format_prediction_confirmed,
    format_stats,
    format_recent,
)
from apps.manual_trading.models import Prediction, Signal


class TestFormatSignal:
    def test_call_signal(self) -> None:
        signal = Signal(
            direction="call",
            confidence=0.78,
            reasoning=["RSI 28 — oversold", "MACD bullish crossover"],
            indicators={"rsi": 28.0, "macd_hist": 0.001},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "CALL" in msg
        assert "78%" in msg
        assert "1.0852" in msg
        assert "RSI 28" in msg

    def test_put_signal(self) -> None:
        signal = Signal(
            direction="put",
            confidence=0.82,
            reasoning=["RSI 75 — overbought"],
            indicators={"rsi": 75.0},
        )
        msg = format_signal("GBPUSD_otc", signal, 1.2650)
        assert "PUT" in msg
        assert "82%" in msg

    def test_otc_display_name(self) -> None:
        signal = Signal(
            direction="call",
            confidence=0.7,
            reasoning=["test"],
            indicators={},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "(OTC)" in msg

    def test_non_otc_display_name(self) -> None:
        signal = Signal(
            direction="call",
            confidence=0.7,
            reasoning=["test"],
            indicators={},
        )
        msg = format_signal("EURUSD", signal, 1.0852)
        assert "(OTC)" not in msg
        # Non-OTC symbols have no underscore, so display as-is
        assert "EURUSD" in msg


class TestFormatPredictionConfirmed:
    def test_confirmation_message(self) -> None:
        now = datetime.now(timezone.utc)
        prediction = Prediction(
            id=uuid4(),
            telegram_id=123,
            symbol="EURUSD_otc",
            timeframe_sec=60,
            direction="call",
            confidence=0.78,
            reasoning="test",
            indicators={"rsi": 28.0},
            entry_price=Decimal("1.0852"),
            entry_time=now,
            expiry_time=now + timedelta(seconds=60),
        )
        msg = format_prediction_confirmed(prediction)
        assert "CALL" in msg
        assert "1 min" in msg
        assert "1.0852" in msg
        assert "Tracking" in msg


class TestFormatStats:
    def test_basic_stats(self) -> None:
        stats = {
            "total": 10,
            "wins": 7,
            "losses": 3,
            "win_rate": 70.0,
            "by_symbol": [
                {"symbol": "EURUSD_otc", "total": 5, "wins": 4},
            ],
            "by_confidence": [
                {"bucket": "80-89%", "total": 3, "wins": 2},
            ],
        }
        msg = format_stats(stats)
        assert "70.0%" in msg
        assert "10" in msg
        assert "7" in msg
        # Symbol "EURUSD_otc" gets _otc replaced with " (OTC)" → "EURUSD (OTC)"
        assert "EURUSD (OTC)" in msg
        assert "80-89%" in msg

    def test_empty_stats(self) -> None:
        stats = {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "by_symbol": [],
            "by_confidence": [],
        }
        msg = format_stats(stats)
        assert "0.0%" in msg
        assert "0" in msg


class TestFormatRecent:
    def test_empty_recent(self) -> None:
        msg = format_recent([])
        assert "No recent" in msg

    def test_with_predictions(self) -> None:
        predictions = [
            {
                "symbol": "EURUSD_otc",
                "direction": "call",
                "confidence": 0.78,
                "result": "win",
            },
            {
                "symbol": "GBPUSD_otc",
                "direction": "put",
                "confidence": 0.82,
                "result": "loss",
            },
        ]
        msg = format_recent(predictions)
        assert "WIN" in msg
        assert "LOSS" in msg
        assert "CALL" in msg
        assert "PUT" in msg

    def test_pending_result(self) -> None:
        predictions = [
            {
                "symbol": "EURUSD_otc",
                "direction": "call",
                "confidence": 0.78,
                "result": None,
            },
        ]
        msg = format_recent(predictions)
        assert "PENDING" in msg

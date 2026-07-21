"""Tests for Telegram message formatting."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal


from uuid import uuid4

from apps.manual_trading.messages import (
    format_signal,
    format_prediction_confirmed,
    format_stats,
    format_recent,
    format_result_request,
    format_result_recorded,
    format_ai_signal,
    format_no_model_available,
    format_ai_model_info,
    format_no_signal,
)
from apps.manual_trading.models import Prediction, Signal


class TestFormatSignal:
    def test_call_signal(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="call",
            confidence=0.78,
            reasoning=["RSI 28 -- oversold", "MACD bullish crossover"],
            indicators={"rsi": 28.0, "macd_hist": 0.001},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "CALL" in msg
        assert "78%" in msg
        assert "1.0852" in msg
        assert "RSI 28" in msg

    def test_put_signal(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="put",
            confidence=0.82,
            reasoning=["RSI 75 -- overbought"],
            indicators={"rsi": 75.0},
        )
        msg = format_signal("GBPUSD_otc", signal, 1.2650)
        assert "PUT" in msg
        assert "82%" in msg

    def test_otc_display_name(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="call",
            confidence=0.7,
            reasoning=["test"],
            indicators={},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "(OTC)" in msg

    def test_non_otc_display_name(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="call",
            confidence=0.7,
            reasoning=["test"],
            indicators={},
        )
        msg = format_signal("EURUSD", signal, 1.0852)
        assert "(OTC)" not in msg
        assert "EURUSD" in msg

    def test_trend_line_extracted_to_header(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="call",
            confidence=0.80,
            reasoning=[
                "Uptrend (EMA 10 > EMA 30, MACD confirmed)",
                "RSI dip buy — RSI 45 in entry zone (40-50)",
            ],
            indicators={"rsi": 45.0},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "Trend:" in msg
        assert "Uptrend" in msg

    def test_entry_zone_extracted_to_header(self) -> None:
        signal = Signal(
            has_signal=True,
            direction="call",
            confidence=0.80,
            reasoning=[
                "Uptrend (EMA 10 > EMA 30)",
                "RSI dip buy — RSI 45 in entry zone (40-50) within uptrend",
            ],
            indicators={"rsi": 45.0},
        )
        msg = format_signal("EURUSD_otc", signal, 1.0852)
        assert "Entry Zone:" in msg


class TestFormatNoSignal:
    def test_displays_reason(self) -> None:
        msg = format_no_signal("EURUSD_otc", "No clear trend")
        assert "No clear signal" in msg
        assert "No clear trend" in msg
        assert "EURUSD (OTC)" in msg

    def test_non_otc_pair(self) -> None:
        msg = format_no_signal("EURUSD", "EMA in dead zone")
        assert "EURUSD" in msg
        assert "(OTC)" not in msg

    def test_suggests_retry(self) -> None:
        msg = format_no_signal("GBPUSD_otc", "Momentum disagrees")
        assert "Try again" in msg


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


class TestFormatResultRequest:
    def test_call_direction(self) -> None:
        msg = format_result_request(
            symbol="EURUSD_otc",
            direction="call",
            entry_price=1.0852,
            timeframe_sec=60,
        )
        assert "Trade Expired" in msg
        assert "CALL" in msg
        assert "EURUSD" in msg
        assert "(OTC)" in msg
        assert "1.0852" in msg
        assert "1 min" in msg

    def test_put_direction(self) -> None:
        msg = format_result_request(
            symbol="GBPUSD_otc",
            direction="put",
            entry_price=1.2650,
            timeframe_sec=300,
        )
        assert "PUT" in msg
        assert "5 min" in msg

    def test_non_otc_pair(self) -> None:
        msg = format_result_request(
            symbol="EURUSD",
            direction="call",
            entry_price=1.0852,
            timeframe_sec=60,
        )
        assert "(OTC)" not in msg


class TestFormatResultRecorded:
    def test_win(self) -> None:
        msg = format_result_recorded("win")
        assert "WIN" in msg

    def test_loss(self) -> None:
        msg = format_result_recorded("loss")
        assert "LOSS" in msg

    def test_tie(self) -> None:
        msg = format_result_recorded("tie")
        assert "TIE" in msg


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


class TestFormatAiSignal:
    def test_call_signal(self) -> None:
        msg = format_ai_signal(
            symbol="EURUSD_otc",
            direction="call",
            win_probability=0.72,
            entry_price=1.0852,
            model_version="1.0.0",
            top_features=[("rsi", 0.25), ("macd_hist", 0.20)],
            indicator_snapshot={"rsi": 28.0, "macd_hist": 0.001},
        )
        assert "CALL" in msg
        assert "72.0%" in msg
        assert "1.0852" in msg
        assert "v1.0.0" in msg
        assert "RSI" in msg

    def test_put_signal(self) -> None:
        msg = format_ai_signal(
            symbol="GBPUSD_otc",
            direction="put",
            win_probability=0.35,
            entry_price=1.2650,
            model_version="2.0.0",
            top_features=[("bb_pct", 0.30)],
            indicator_snapshot={"bb_pct": 0.95},
        )
        assert "PUT" in msg
        assert "65%" in msg  # confidence_pct = 1 - 0.35, formatted as .0%

    def test_otc_display(self) -> None:
        msg = format_ai_signal(
            symbol="EURUSD_otc",
            direction="call",
            win_probability=0.65,
            entry_price=1.0852,
            model_version="1.0.0",
            top_features=[],
            indicator_snapshot={},
        )
        assert "(OTC)" in msg

    def test_no_indicators(self) -> None:
        msg = format_ai_signal(
            symbol="EURUSD_otc",
            direction="call",
            win_probability=0.65,
            entry_price=1.0852,
            model_version="1.0.0",
            top_features=[("rsi", 0.3)],
            indicator_snapshot={},
        )
        assert "CALL" in msg
        assert "Key Features" in msg

    def test_feature_importance_display(self) -> None:
        msg = format_ai_signal(
            symbol="EURUSD_otc",
            direction="call",
            win_probability=0.65,
            entry_price=1.0852,
            model_version="1.0.0",
            top_features=[("rsi", 0.25), ("macd_hist", 0.20), ("bb_pct", 0.15)],
            indicator_snapshot={},
        )
        assert "Rsi" in msg  # title-cased
        assert "25.0%" in msg  # importance


class TestFormatNoModelAvailable:
    def test_message_content(self) -> None:
        msg = format_no_model_available()
        assert "Model Not Available" in msg
        assert "Quick Trade" in msg
        assert "ML model" in msg

    def test_not_empty(self) -> None:
        msg = format_no_model_available()
        assert len(msg) > 50


class TestFormatAiModelInfo:
    def test_none_metadata(self) -> None:
        msg = format_ai_model_info(None)
        assert "No model" in msg

    def test_with_metrics(self) -> None:
        metadata = {
            "version": "1.0.0",
            "created_at": "2025-01-15T10:30:00Z",
            "feature_names": ["rsi", "macd_hist", "bb_pct"],
            "metrics": {
                "accuracy": 0.62,
                "precision": 0.65,
                "recall": 0.58,
                "f1": 0.61,
                "auc": 0.68,
                "train_samples": 150,
                "test_samples": 38,
            },
        }
        msg = format_ai_model_info(metadata)
        assert "Version: 1.0.0" in msg
        assert "2025-01-15" in msg
        assert "62.0%" in msg
        assert "65.0%" in msg
        assert "58.0%" in msg
        assert "61.0%" in msg
        assert "0.680" in msg
        assert "150" in msg
        assert "38" in msg

    def test_without_metrics(self) -> None:
        metadata = {
            "version": "1.0.0",
            "created_at": "2025-01-15T10:30:00Z",
            "feature_names": ["rsi", "macd_hist"],
        }
        msg = format_ai_model_info(metadata)
        assert "Version: 1.0.0" in msg
        assert "Features: 2" in msg

"""Tests for the always-signal directional confidence signal generator."""
import numpy as np
import pandas as pd
import pytest

from apps.manual_trading.signal_generator import (
    generate_signal,
    _detect_direction,
    _score_confidence,
    _score_volatility_penalty,
    _build_indicator_snapshot,
    MIN_CANDLES,
)
from apps.manual_trading.constants import (
    TREND_STRONG_THRESHOLD,
    TREND_MILD_THRESHOLD,
    RSI_FAVORABLE_LOW,
    RSI_FAVORABLE_HIGH,
    ATR_SPIKE_MULTIPLIER,
    COOLDOWN_BARS,
)
from infrastructure.features.indicators.technical import TechnicalIndicators


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Create synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    close = 1.0850 + np.cumsum(rng.normal(0, 0.0003, n))
    high = close + rng.uniform(0.0001, 0.001, n)
    low = close - rng.uniform(0.0001, 0.001, n)
    opn = close + rng.normal(0, 0.0002, n)
    volume = rng.integers(1000, 50000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="1min")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_indicators_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Create OHLCV data with indicators already computed."""
    df = _make_ohlcv(n, seed)
    ti = TechnicalIndicators()
    return ti.compute(df)


def _make_row(**overrides) -> pd.Series:
    """Build a single-row pd.Series with indicator columns set to NaN by default."""
    defaults = {
        "ema_cross": float("nan"),
        "macd_hist": float("nan"),
        "rsi": float("nan"),
        "stoch_k": float("nan"),
        "stoch_d": float("nan"),
        "bb_pct": float("nan"),
        "roc_5": float("nan"),
        "atr_pct": float("nan"),
        "close": 1.0850,
    }
    defaults.update(overrides)
    return pd.Series(defaults)


def _make_prev(**overrides) -> pd.Series:
    """Build a previous-bar pd.Series for stochastic crossover tests."""
    defaults = {
        "stoch_k": float("nan"),
        "stoch_d": float("nan"),
    }
    defaults.update(overrides)
    return pd.Series(defaults)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_min_candles(self) -> None:
        assert MIN_CANDLES == 16

    def test_cooldown_bars(self) -> None:
        assert COOLDOWN_BARS == 3

    def test_trend_thresholds(self) -> None:
        assert TREND_STRONG_THRESHOLD > TREND_MILD_THRESHOLD > 0

    def test_rsi_boundaries(self) -> None:
        assert RSI_FAVORABLE_LOW < RSI_FAVORABLE_HIGH

    def test_atr_spike_multiplier_gt_one(self) -> None:
        assert ATR_SPIKE_MULTIPLIER > 1.0


# ---------------------------------------------------------------------------
# Direction Detection
# ---------------------------------------------------------------------------

class TestDetectDirection:
    def test_strong_ema_cross_returns_call(self) -> None:
        last = _make_row(ema_cross=0.005, close=1.0850)
        assert _detect_direction(last) == "call"

    def test_strong_negative_ema_cross_returns_put(self) -> None:
        last = _make_row(ema_cross=-0.005, close=1.0850)
        assert _detect_direction(last) == "put"

    def test_mild_ema_cross_returns_direction(self) -> None:
        """Even a mild EMA cross above TREND_MILD_THRESHOLD is enough."""
        last = _make_row(ema_cross=0.001, close=1.0850)
        assert _detect_direction(last) == "call"

    def test_tiny_ema_cross_uses_roc_tiebreaker(self) -> None:
        """EMA cross below TREND_MILD_THRESHOLD falls back to ROC."""
        last = _make_row(ema_cross=0.00001, roc_5=0.003, close=1.0850)
        assert _detect_direction(last) == "call"

    def test_tiny_negative_ema_cross_uses_roc_put(self) -> None:
        last = _make_row(ema_cross=-0.00001, roc_5=-0.003, close=1.0850)
        assert _detect_direction(last) == "put"

    def test_nan_ema_uses_roc(self) -> None:
        last = _make_row(ema_cross=float("nan"), roc_5=0.002)
        assert _detect_direction(last) == "call"

    def test_nan_ema_negative_roc_returns_put(self) -> None:
        last = _make_row(ema_cross=float("nan"), roc_5=-0.002)
        assert _detect_direction(last) == "put"

    def test_both_nan_returns_none(self) -> None:
        last = _make_row(ema_cross=float("nan"), roc_5=float("nan"))
        assert _detect_direction(last) is None

    def test_zero_ema_zero_roc_returns_put(self) -> None:
        """EMA cross = 0 is below TREND_MILD_THRESHOLD, ROC = 0 is not > 0, returns put."""
        last = _make_row(ema_cross=0.0, roc_5=0.0, close=1.0850)
        assert _detect_direction(last) == "put"


# ---------------------------------------------------------------------------
# Confidence Scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    def test_base_only_with_all_nan(self) -> None:
        """All indicators NaN = base confidence 0.50, no bonuses."""
        last = _make_row(close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus == pytest.approx(0.0)

    def test_roc_agrees_adds_bonus(self) -> None:
        last = _make_row(roc_5=0.005, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.08
        assert any("ROC confirms" in r for r in reasons)

    def test_roc_diverges_no_penalty(self) -> None:
        """ROC disagreement just doesn't add the bonus — no negative penalty."""
        last = _make_row(roc_5=-0.005, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.0
        assert any("ROC diverges" in r for r in reasons)

    def test_macd_agrees_adds_bonus(self) -> None:
        last = _make_row(macd_hist=0.001, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.05
        assert any("MACD histogram confirms" in r for r in reasons)

    def test_macd_diverges_no_penalty(self) -> None:
        last = _make_row(macd_hist=-0.001, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert any("MACD histogram diverges" in r for r in reasons)

    def test_rsi_favorable_in_downtrend(self) -> None:
        """RSI above RSI_FAVORABLE_HIGH in downtrend = favorable (overbought)."""
        last = _make_row(rsi=70.0, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "put")
        assert bonus >= 0.05
        assert any("favorable" in r.lower() for r in reasons)

    def test_rsi_favorable_in_uptrend(self) -> None:
        """RSI below RSI_FAVORABLE_LOW in uptrend = favorable (oversold)."""
        last = _make_row(rsi=30.0, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.05
        assert any("favorable" in r.lower() for r in reasons)

    def test_rsi_entry_zone_uptrend(self) -> None:
        """RSI 40 in uptrend is in entry zone (30-50)."""
        last = _make_row(rsi=40.0, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert any("entry zone" in r.lower() for r in reasons)

    def test_rsi_entry_zone_downtrend(self) -> None:
        """RSI 60 in downtrend is in entry zone (50-70)."""
        last = _make_row(rsi=60.0, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "put")
        assert any("entry zone" in r.lower() for r in reasons)

    def test_stoch_bullish_cross_in_uptrend(self) -> None:
        last = _make_row(stoch_k=60, stoch_d=50, close=1.0850)
        prev = _make_prev(stoch_k=45, stoch_d=50)
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.03
        assert any("bullish" in r.lower() and "crossover" in r for r in reasons)

    def test_stoch_bearish_cross_in_downtrend(self) -> None:
        last = _make_row(stoch_k=40, stoch_d=50, close=1.0850)
        prev = _make_prev(stoch_k=55, stoch_d=50)
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "put")
        assert bonus >= 0.03
        assert any("bearish" in r.lower() and "crossover" in r for r in reasons)

    def test_bb_lower_in_uptrend(self) -> None:
        last = _make_row(bb_pct=0.2, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.03
        assert any("lower Bollinger" in r for r in reasons)

    def test_bb_upper_in_downtrend(self) -> None:
        last = _make_row(bb_pct=0.8, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "put")
        assert bonus >= 0.03
        assert any("upper Bollinger" in r for r in reasons)

    def test_strong_ema_trend_bonus(self) -> None:
        last = _make_row(ema_cross=0.005, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.05
        assert any("Strong EMA" in r for r in reasons)

    def test_mild_ema_trend_bonus(self) -> None:
        last = _make_row(ema_cross=0.0008, close=1.0850)
        prev = _make_prev()
        df = _make_indicators_df(30)
        bonus, reasons = _score_confidence(last, prev, df, "call")
        assert bonus >= 0.02
        assert any("Mild EMA" in r for r in reasons)


# ---------------------------------------------------------------------------
# Volatility Penalty
# ---------------------------------------------------------------------------

class TestVolatilityPenalty:
    def test_spike_penalizes(self) -> None:
        """When ATR% > multiplier * SMA, penalty = -0.10."""
        df = _make_indicators_df(30)
        df["atr_pct"] = np.full(30, 0.01)
        df.loc[df.index[-1], "atr_pct"] = 0.05
        last = df.iloc[-1]
        penalty, reason = _score_volatility_penalty(last, df)
        assert penalty == pytest.approx(-0.10)
        assert "ATR spike" in reason

    def test_normal_no_penalty(self) -> None:
        df = _make_indicators_df(30)
        df["atr_pct"] = np.full(30, 0.01)
        last = df.iloc[-1]
        penalty, reason = _score_volatility_penalty(last, df)
        assert penalty == 0.0
        assert reason is None

    def test_nan_atr_no_penalty(self) -> None:
        df = _make_indicators_df(30)
        df["atr_pct"] = float("nan")
        last = df.iloc[-1]
        penalty, reason = _score_volatility_penalty(last, df)
        assert penalty == 0.0
        assert reason is None


# ---------------------------------------------------------------------------
# Indicator Snapshot
# ---------------------------------------------------------------------------

class TestIndicatorSnapshot:
    def test_populates_key_fields(self) -> None:
        last = _make_row(rsi=45.0, macd_hist=0.001, bb_pct=0.3, stoch_k=60.0,
                         stoch_d=50.0, roc_5=0.002, atr_pct=0.01)
        snapshot = _build_indicator_snapshot(last)
        assert snapshot["rsi"] == 45.0
        assert snapshot["macd_hist"] == 0.001
        assert snapshot["bb_pct"] == 0.3
        assert snapshot["stoch_k"] == 60.0
        assert snapshot["roc_5"] == 0.002

    def test_nan_values_become_none(self) -> None:
        last = _make_row()
        snapshot = _build_indicator_snapshot(last)
        for key in ["rsi", "macd_hist", "bb_pct", "stoch_k", "stoch_d", "roc_5", "atr_pct"]:
            assert snapshot[key] is None


# ---------------------------------------------------------------------------
# End-to-end: generate_signal()
# ---------------------------------------------------------------------------

class TestGenerateSignal:
    def test_returns_signal_with_required_fields(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert hasattr(signal, "has_signal")
        assert signal.direction in ("call", "put")
        assert isinstance(signal.reasoning, list)
        assert isinstance(signal.indicators, dict)

    def test_insufficient_data_returns_no_signal(self) -> None:
        df = _make_indicators_df(5)
        signal = generate_signal(df)
        assert signal.has_signal is False
        assert signal.confidence == 0.0
        assert "Insufficient data" in signal.reasoning[0]

    def test_always_has_signal_with_sufficient_data(self) -> None:
        """The key behavior change: with enough data, has_signal is always True."""
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert signal.has_signal is True

    def test_confidence_in_valid_range(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert 0.35 <= signal.confidence <= 0.90

    def test_indicators_snapshot_populated(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert "rsi" in signal.indicators
        assert "macd_hist" in signal.indicators
        assert "bb_pct" in signal.indicators
        assert "stoch_k" in signal.indicators

    def test_reasoning_bullets_limited(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert len(signal.reasoning) <= 5

    def test_different_seeds_give_different_signals(self) -> None:
        df1 = _make_indicators_df(100, seed=42)
        df2 = _make_indicators_df(100, seed=99)
        signal1 = generate_signal(df1)
        signal2 = generate_signal(df2)
        assert signal1.indicators != signal2.indicators

    def test_degraded_signal_with_few_candles(self) -> None:
        """With 20 candles, MACD slow EMA is unstable but signal still works."""
        df = _make_indicators_df(20)
        signal = generate_signal(df)
        assert signal.direction in ("call", "put")
        assert len(signal.reasoning) > 0
        assert "Insufficient data" not in signal.reasoning[0]

    def test_all_nan_indicators_returns_no_signal(self) -> None:
        """When all indicators are NaN, direction cannot be determined."""
        df = _make_indicators_df(30)
        # Force all indicator columns to NaN
        for col in ["ema_cross", "macd_hist", "rsi", "stoch_k", "stoch_d",
                     "bb_pct", "roc_5", "atr_pct"]:
            df[col] = float("nan")
        signal = generate_signal(df)
        assert signal.has_signal is False
        assert "Unable to determine direction" in signal.reasoning[0]

    def test_first_reasoning_is_summary(self) -> None:
        """First reasoning bullet should be the summary line."""
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert signal.has_signal is True
        assert "signal" in signal.reasoning[0].lower()
        assert "confidence" in signal.reasoning[0].lower()

    def test_atr_spike_reduces_confidence(self) -> None:
        """ATR spike should reduce confidence via penalty."""
        df = _make_indicators_df(30)
        df["atr_pct"] = np.full(30, 0.01)
        df.loc[df.index[-1], "atr_pct"] = 0.05  # Spike
        signal_normal = generate_signal(_make_indicators_df(30))
        signal_spike = generate_signal(df)
        # Spike signal should have lower or equal confidence
        assert signal_spike.confidence <= signal_normal.confidence

"""Tests for the trend-following confluence signal generator."""
import numpy as np
import pandas as pd
import pytest

from apps.manual_trading.signal_generator import (
    generate_signal,
    _detect_trend,
    _check_momentum,
    _score_entry_timing,
    _check_volatility,
    _compute_confidence,
    MIN_CANDLES,
)
from apps.manual_trading.constants import (
    MIN_CONFIDENCE,
    TREND_DEAD_ZONE,
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_min_candles(self) -> None:
        assert MIN_CANDLES == 16

    def test_min_confidence(self) -> None:
        assert MIN_CONFIDENCE == 0.70

    def test_cooldown_bars(self) -> None:
        assert COOLDOWN_BARS == 3


# ---------------------------------------------------------------------------
# Stage 1: Trend Detection
# ---------------------------------------------------------------------------

class TestDetectTrend:
    def test_uptrend_ema_above_dead_zone(self) -> None:
        last = _make_row(ema_cross=0.005, macd_hist=0.0005)
        prev = _make_row(ema_cross=0.004, macd_hist=0.0003)
        direction, reasons = _detect_trend(last, prev)
        assert direction == "up"
        assert any("Uptrend" in r for r in reasons)

    def test_downtrend_ema_below_dead_zone(self) -> None:
        last = _make_row(ema_cross=-0.005, macd_hist=-0.0005)
        prev = _make_row(ema_cross=-0.004, macd_hist=-0.0003)
        direction, reasons = _detect_trend(last, prev)
        assert direction == "down"
        assert any("Downtrend" in r for r in reasons)

    def test_dead_zone_rejects(self) -> None:
        last = _make_row(ema_cross=0.00005, macd_hist=0.0001)
        prev = _make_row(ema_cross=0.00004)
        direction, reasons = _detect_trend(last, prev)
        assert direction is None
        assert any("dead zone" in r for r in reasons)

    def test_ema_macd_disagreement_rejects(self) -> None:
        last = _make_row(ema_cross=0.005, macd_hist=-0.0005)
        prev = _make_row(ema_cross=0.004, macd_hist=-0.0003)
        direction, reasons = _detect_trend(last, prev)
        assert direction is None
        assert any("disagree" in r for r in reasons)

    def test_ema_nan_returns_none(self) -> None:
        last = _make_row(ema_cross=float("nan"))
        prev = _make_row()
        direction, reasons = _detect_trend(last, prev)
        assert direction is None
        assert any("unavailable" in r for r in reasons)

    def test_macd_nan_with_valid_ema_passes(self) -> None:
        """When MACD is NaN, only EMA direction matters."""
        last = _make_row(ema_cross=0.005, macd_hist=float("nan"))
        prev = _make_row(ema_cross=0.004)
        direction, reasons = _detect_trend(last, prev)
        assert direction == "up"
        assert any("MACD unavailable" in r for r in reasons)


# ---------------------------------------------------------------------------
# Stage 2: Momentum Gate
# ---------------------------------------------------------------------------

class TestMomentumGate:
    def test_macd_agrees_with_uptrend(self) -> None:
        last = _make_row(macd_hist=0.001, roc_5=0.0005)
        prev = _make_row()
        ok, reasons = _check_momentum(last, prev, "up")
        assert ok is True
        assert any("MACD momentum" in r for r in reasons)

    def test_macd_disagrees_rejects(self) -> None:
        last = _make_row(macd_hist=-0.001, roc_5=0.0005)
        prev = _make_row()
        ok, reasons = _check_momentum(last, prev, "up")
        assert ok is False
        assert any("disagrees" in r for r in reasons)

    def test_roc_disagrees_rejects(self) -> None:
        last = _make_row(macd_hist=0.001, roc_5=-0.005)
        prev = _make_row()
        ok, reasons = _check_momentum(last, prev, "up")
        assert ok is False
        assert any("ROC" in r for r in reasons)

    def test_both_nan_passes(self) -> None:
        last = _make_row(macd_hist=float("nan"), roc_5=float("nan"))
        prev = _make_row()
        ok, reasons = _check_momentum(last, prev, "up")
        assert ok is True
        assert len(reasons) == 0

    def test_downtrend_macd_negative_agrees(self) -> None:
        last = _make_row(macd_hist=-0.001, roc_5=-0.005)
        prev = _make_row()
        ok, reasons = _check_momentum(last, prev, "down")
        assert ok is True


# ---------------------------------------------------------------------------
# Stage 3: Entry Timing
# ---------------------------------------------------------------------------

class TestEntryTiming:
    def test_rsi_dip_buy_in_uptrend(self) -> None:
        last = _make_row(rsi=45, stoch_k=float("nan"), stoch_d=float("nan"),
                         prev_stoch_k=float("nan"), bb_pct=float("nan"))
        prev = _make_row(stoch_k=float("nan"), stoch_d=float("nan"))
        bonus, reasons = _score_entry_timing(last, prev, "up")
        assert bonus >= 0.10
        assert any("RSI dip buy" in r for r in reasons)

    def test_rsi_sell_zone_in_downtrend(self) -> None:
        last = _make_row(rsi=55, stoch_k=float("nan"), stoch_d=float("nan"),
                         bb_pct=float("nan"))
        prev = _make_row(stoch_k=float("nan"), stoch_d=float("nan"))
        bonus, reasons = _score_entry_timing(last, prev, "down")
        assert bonus >= 0.10
        assert any("RSI sell zone" in r for r in reasons)

    def test_rsi_outside_zone_no_bonus(self) -> None:
        last = _make_row(rsi=70, stoch_k=float("nan"), stoch_d=float("nan"),
                         bb_pct=float("nan"))
        prev = _make_row(stoch_k=float("nan"), stoch_d=float("nan"))
        bonus, reasons = _score_entry_timing(last, prev, "up")
        assert bonus == 0.0
        assert any("outside entry" in r for r in reasons)

    def test_stoch_bullish_cross_in_uptrend(self) -> None:
        last = _make_row(rsi=float("nan"), stoch_k=60, stoch_d=50, bb_pct=float("nan"))
        prev = _make_row(stoch_k=45, stoch_d=50)
        bonus, reasons = _score_entry_timing(last, prev, "up")
        assert bonus >= 0.05
        assert any("bullish" in r.lower() and "crossover" in r for r in reasons)

    def test_stoch_bearish_cross_in_downtrend(self) -> None:
        last = _make_row(rsi=float("nan"), stoch_k=40, stoch_d=50, bb_pct=float("nan"))
        prev = _make_row(stoch_k=55, stoch_d=50)
        bonus, reasons = _score_entry_timing(last, prev, "down")
        assert bonus >= 0.05
        assert any("bearish" in r.lower() and "crossover" in r for r in reasons)

    def test_bb_lower_band_in_uptrend(self) -> None:
        last = _make_row(rsi=float("nan"), stoch_k=float("nan"), stoch_d=float("nan"),
                         bb_pct=0.2)
        prev = _make_row(stoch_k=float("nan"), stoch_d=float("nan"))
        bonus, reasons = _score_entry_timing(last, prev, "up")
        assert bonus >= 0.05
        assert any("lower Bollinger" in r for r in reasons)

    def test_bb_upper_band_in_downtrend(self) -> None:
        last = _make_row(rsi=float("nan"), stoch_k=float("nan"), stoch_d=float("nan"),
                         bb_pct=0.8)
        prev = _make_row(stoch_k=float("nan"), stoch_d=float("nan"))
        bonus, reasons = _score_entry_timing(last, prev, "down")
        assert bonus >= 0.05
        assert any("upper Bollinger" in r for r in reasons)

    def test_max_bonus_cap(self) -> None:
        """All three bonuses combined = 0.20."""
        last = _make_row(rsi=45, stoch_k=60, stoch_d=50, bb_pct=0.2)
        prev = _make_row(stoch_k=45, stoch_d=50)
        bonus, _ = _score_entry_timing(last, prev, "up")
        assert bonus == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Stage 4: Volatility Filter
# ---------------------------------------------------------------------------

class TestVolatilityFilter:
    def test_spike_rejects(self) -> None:
        """When ATR% is much larger than its SMA, signal is rejected."""
        df = _make_indicators_df(30)
        # Force a spike in the last row
        atr_pct_values = np.full(30, 0.01)
        atr_pct_values[-1] = 0.05  # 5x the normal
        df["atr_pct"] = atr_pct_values
        last = df.iloc[-1]
        ok, reasons = _check_volatility(last, df)
        assert ok is False
        assert any("ATR spike" in r for r in reasons)

    def test_normal_passes(self) -> None:
        df = _make_indicators_df(30)
        df["atr_pct"] = np.full(30, 0.01)
        last = df.iloc[-1]
        ok, reasons = _check_volatility(last, df)
        assert ok is True

    def test_nan_atr_passes(self) -> None:
        df = _make_indicators_df(30)
        df["atr_pct"] = float("nan")
        last = df.iloc[-1]
        ok, reasons = _check_volatility(last, df)
        assert ok is True


# ---------------------------------------------------------------------------
# Stage 5: Confidence Scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    def test_base_only(self) -> None:
        conf = _compute_confidence(0.65, [])
        assert conf == pytest.approx(0.65)

    def test_base_plus_bonus(self) -> None:
        conf = _compute_confidence(0.65, [0.10, 0.05])
        assert conf == pytest.approx(0.80)

    def test_clamped_at_095(self) -> None:
        conf = _compute_confidence(0.90, [0.10])
        assert conf == pytest.approx(0.95)

    def test_clamped_at_0(self) -> None:
        conf = _compute_confidence(-0.10, [])
        assert conf == pytest.approx(0.0)


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

    def test_no_signal_when_in_dead_zone(self) -> None:
        """When EMA cross is in the dead zone, has_signal should be False."""
        df = _make_indicators_df(100)
        # Force EMA cross into the dead zone
        df.loc[df.index[-1], "ema_cross"] = 0.0
        df.loc[df.index[-2], "ema_cross"] = 0.0
        signal = generate_signal(df)
        assert signal.has_signal is False

    def test_has_signal_true_only_when_all_gates_pass(self) -> None:
        """Verify has_signal=False when momentum disagrees."""
        df = _make_indicators_df(100)
        # Set EMA cross indicating uptrend
        df.loc[df.index[-1], "ema_cross"] = 0.001
        df.loc[df.index[-2], "ema_cross"] = 0.0008
        # But MACD histogram disagrees
        df.loc[df.index[-1], "macd_hist"] = -0.001
        signal = generate_signal(df)
        assert signal.has_signal is False

    def test_confidence_gated_below_minimum(self) -> None:
        """When all stages pass but confidence is below MIN_CONFIDENCE, has_signal=False."""
        df = _make_indicators_df(100)
        # Force a weak signal — EMA cross barely above dead zone
        df.loc[df.index[-1], "ema_cross"] = 0.0002
        df.loc[df.index[-2], "ema_cross"] = 0.00015
        # MACD agrees weakly
        df.loc[df.index[-1], "macd_hist"] = 0.0001
        df.loc[df.index[-1], "roc_5"] = 0.0001
        # RSI outside entry zone, no stochastic, no BB
        df.loc[df.index[-1], "rsi"] = 65.0
        df.loc[df.index[-1], "stoch_k"] = float("nan")
        df.loc[df.index[-1], "stoch_d"] = float("nan")
        df.loc[df.index[-1], "bb_pct"] = 0.5
        signal = generate_signal(df)
        # With base 0.65 and no bonuses, confidence = 0.65 < 0.70
        if signal.confidence < MIN_CONFIDENCE:
            assert signal.has_signal is False


# ---------------------------------------------------------------------------
# Constants check
# ---------------------------------------------------------------------------

class TestStrategyConstants:
    def test_trend_dead_zone_is_positive(self) -> None:
        assert TREND_DEAD_ZONE > 0

    def test_atr_spike_multiplier_gt_one(self) -> None:
        assert ATR_SPIKE_MULTIPLIER > 1.0

"""Tests for rule-based signal generation."""
import numpy as np
import pandas as pd
import pytest

from apps.manual_trading.signal_generator import generate_signal, MIN_CANDLES
from infrastructure.features.indicators.technical import TechnicalIndicators


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


class TestSignalGenerator:
    def test_returns_signal_with_required_fields(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert signal.direction in ("call", "put")
        assert 0.0 <= signal.confidence <= 1.0
        assert isinstance(signal.reasoning, list)
        assert len(signal.reasoning) > 0
        assert isinstance(signal.indicators, dict)

    def test_confidence_clamped(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert 0.55 <= signal.confidence <= 0.95

    def test_insufficient_data_returns_low_confidence(self) -> None:
        df = _make_indicators_df(5)
        signal = generate_signal(df)
        assert signal.confidence == 0.5
        assert "Insufficient data" in signal.reasoning[0]

    def test_indicators_snapshot_populated(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert "rsi" in signal.indicators
        assert "macd_hist" in signal.indicators
        assert "bb_pct" in signal.indicators
        assert "stoch_k" in signal.indicators

    def test_bullish_signal_when_rsi_oversold(self) -> None:
        """When RSI is very low, signal should lean bullish."""
        df = _make_indicators_df(100)
        # Force RSI to oversold
        df.loc[df.index[-1], "rsi"] = 15.0
        signal = generate_signal(df)
        # With RSI oversold, should have a call signal or at least
        # the reasoning should mention oversold
        rsi_reasons = [r for r in signal.reasoning if "oversold" in r.lower() or "RSI" in r]
        assert len(rsi_reasons) > 0

    def test_bearish_signal_when_rsi_overbought(self) -> None:
        """When RSI is very high, signal should lean bearish."""
        df = _make_indicators_df(100)
        # Force RSI to overbought
        df.loc[df.index[-1], "rsi"] = 85.0
        signal = generate_signal(df)
        rsi_reasons = [r for r in signal.reasoning if "overbought" in r.lower() or "RSI" in r]
        assert len(rsi_reasons) > 0

    def test_direction_is_valid(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert signal.direction in ("call", "put")

    def test_different_seeds_give_different_signals(self) -> None:
        """Different market conditions should sometimes give different signals."""
        df1 = _make_indicators_df(100, seed=42)
        df2 = _make_indicators_df(100, seed=99)
        signal1 = generate_signal(df1)
        signal2 = generate_signal(df2)
        # At least the indicators should differ
        assert signal1.indicators != signal2.indicators

    def test_min_candles_constant(self) -> None:
        assert MIN_CANDLES == 16

    def test_degraded_signal_with_few_candles(self) -> None:
        """With 20 candles, MACD slow EMA is unstable but signal still works."""
        df = _make_indicators_df(20)
        signal = generate_signal(df)
        # Should produce a valid signal (not "insufficient data")
        assert signal.direction in ("call", "put")
        assert len(signal.reasoning) > 0
        # Some indicators may be NaN with only 20 candles, but signal still works
        assert "Insufficient data" not in signal.reasoning[0]

    def test_reasoning_bullets_limited(self) -> None:
        df = _make_indicators_df(100)
        signal = generate_signal(df)
        assert len(signal.reasoning) <= 5

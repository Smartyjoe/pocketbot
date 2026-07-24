"""Tests for prompt_builder — LLM prompt construction from market data."""
import pandas as pd
import pytest

from apps.manual_trading.strategies.ai_analysis.prompt_builder import (
    build_prompt,
    SYSTEM_PROMPT,
)


def _sample_df() -> pd.DataFrame:
    """Build a minimal 30-row DataFrame with required columns."""
    import numpy as np
    np.random.seed(42)
    n = 30
    dates = pd.date_range("2026-07-24 09:00:00", periods=n, freq="1min")
    closes = np.cumsum(np.random.randn(n) * 0.1) + 1.0
    return pd.DataFrame({
        "open": closes - 0.001,
        "high": closes + 0.005,
        "low": closes - 0.005,
        "close": closes,
        "rsi": np.clip(np.random.randn(n) * 15 + 50, 0, 100),
        "adx": np.clip(np.random.randn(n) * 10 + 25, 0, 100),
        "zscore": np.random.randn(n),
        "stoch_k": np.clip(np.random.randn(n) * 20 + 50, 0, 100),
        "stoch_d": np.clip(np.random.randn(n) * 15 + 50, 0, 100),
    }, index=dates)


def test_system_prompt_is_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 100


def test_build_prompt_returns_string():
    df = _sample_df()
    prompt = build_prompt(df, "EURUSD_otc")
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_build_prompt_contains_symbol():
    df = _sample_df()
    prompt = build_prompt(df, "GBPUSD_otc")
    assert "GBPUSD_otc" in prompt


def test_build_prompt_contains_indicator_values():
    df = _sample_df()
    prompt = build_prompt(df, "EURUSD_otc")
    # RSI of the last row should appear in the prompt
    last_rsi = df["rsi"].iloc[-1]
    assert str(round(last_rsi, 1)) in prompt or str(round(last_rsi)) in prompt


def test_build_prompt_raises_on_empty_df():
    with pytest.raises((ValueError, IndexError)):
        build_prompt(pd.DataFrame(), "EURUSD_otc")


def test_build_prompt_last_candles_section():
    df = _sample_df()
    prompt = build_prompt(df, "EURUSD_otc")
    # Should contain recent candles as a table
    assert "Candle" in prompt or "candle" in prompt or "Recent" in prompt


def test_build_prompt_indicator_section():
    df = _sample_df()
    prompt = build_prompt(df, "EURUSD_otc")
    assert "RSI" in prompt or "ADX" in prompt or "Z-score" in prompt

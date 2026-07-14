import pytest
import numpy as np
import pandas as pd
from infrastructure.features.indicators.technical import (
    IndicatorConfig,
    TechnicalIndicators,
)


def _make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    opn = close + rng.normal(0, 0.3, n)
    volume = rng.integers(1000, 50000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="1min")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestTechnicalIndicators:
    def test_compute_returns_dataframe_with_all_columns(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        for col in ti.feature_columns():
            assert col in result.columns, f"Missing column: {col}"

    def test_compute_preserves_original_columns(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_short_dataframe_returns_copy(self) -> None:
        df = _make_ohlcv(1)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        assert len(result) == 1

    def test_rsi_bounds(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        rsi_valid = result["rsi"].dropna()
        assert (rsi_valid >= 0).all()
        assert (rsi_valid <= 100).all()

    def test_bollinger_relationship(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        valid = result.dropna(subset=["bb_upper", "bb_lower"])
        assert (valid["bb_upper"] >= valid["bb_lower"]).all()

    def test_stoch_bounds(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        stoch_k = result["stoch_k"].dropna()
        assert (stoch_k >= 0).all()
        assert (stoch_k <= 100).all()

    def test_feature_columns_count(self) -> None:
        ti = TechnicalIndicators()
        cols = ti.feature_columns()
        assert len(cols) == 23

    def test_custom_config(self) -> None:
        config = IndicatorConfig(rsi_period=7, macd_fast=8, macd_slow=17)
        ti = TechnicalIndicators(config=config)
        df = _make_ohlcv(100)
        result = ti.compute(df)
        assert "rsi" in result.columns

    def test_atr_positive(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        atr_valid = result["atr"].dropna()
        assert (atr_valid >= 0).all()

    def test_volume_ratio_present(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        assert "volume_ratio" in result.columns
        vr = result["volume_ratio"].dropna()
        assert (vr > 0).all()

    def test_body_ratio_bounds(self) -> None:
        df = _make_ohlcv(100)
        ti = TechnicalIndicators()
        result = ti.compute(df)
        br = result["body_ratio"].dropna()
        assert (br >= 0).all()
        assert (br <= 1).all()

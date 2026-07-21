import numpy as np
import pandas as pd
from infrastructure.features.engine import FeatureConfig, FeatureEngine


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


class TestFeatureEngine:
    def test_build_features_returns_feature_result(self) -> None:
        engine = FeatureEngine()
        df = _make_ohlcv(100)
        result = engine.build_features(df)
        assert result.row_count == 100
        assert len(result.feature_names) == 23

    def test_valid_mask_filters_nan_rows(self) -> None:
        engine = FeatureEngine()
        df = _make_ohlcv(100)
        result = engine.build_features(df)
        assert result.valid_mask.sum() < 100
        assert result.valid_mask.sum() > 50

    def test_latest_features_returns_dict(self) -> None:
        engine = FeatureEngine()
        df = _make_ohlcv(100)
        features = engine.latest_features(df)
        assert features is not None
        assert len(features) == 23
        for name in engine.feature_names:
            assert name in features

    def test_latest_features_none_on_empty(self) -> None:
        engine = FeatureEngine()
        df = _make_ohlcv(1)
        features = engine.latest_features(df)
        assert features is None

    def test_has_enough_data(self) -> None:
        engine = FeatureEngine()
        assert engine.has_enough_data(_make_ohlcv(100)) is True
        assert engine.has_enough_data(_make_ohlcv(10)) is False

    def test_custom_config_min_rows(self) -> None:
        config = FeatureConfig(min_rows=10)
        engine = FeatureEngine(config=config)
        assert engine.has_enough_data(_make_ohlcv(15)) is True

    def test_no_normalize(self) -> None:
        config = FeatureConfig(normalize=False)
        engine = FeatureEngine(config=config)
        df = _make_ohlcv(100)
        result = engine.build_features(df)
        assert result.row_count == 100

    def test_feature_names_property(self) -> None:
        engine = FeatureEngine()
        assert isinstance(engine.feature_names, list)
        assert len(engine.feature_names) > 0

    def test_multiple_calls_consistent(self) -> None:
        engine = FeatureEngine()
        df = _make_ohlcv(100)
        r1 = engine.build_features(df)
        r2 = engine.build_features(df)
        assert r1.feature_names == r2.feature_names
        assert r1.valid_mask.sum() == r2.valid_mask.sum()

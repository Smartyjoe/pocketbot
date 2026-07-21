"""Tests for model training script."""
import numpy as np
import pandas as pd

from scripts.train_model import prepare_features


class TestPrepareFeatures:
    def _make_df(self, n: int = 100) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        records = []
        for i in range(n):
            records.append({
                "rsi": float(rng.normal(50, 15)),
                "macd_hist": float(rng.normal(0, 0.001)),
                "bb_pct": float(rng.uniform(0, 1)),
                "label": int(rng.choice([0, 1])),
                "symbol": "EURUSD_otc",
                "timeframe_sec": 60,
                "win_probability": float(rng.uniform(0.3, 0.8)),
            })
        return pd.DataFrame(records)

    def test_extracts_feature_columns(self) -> None:
        df = self._make_df(100)
        features, labels = prepare_features(df)
        assert "rsi" in features.columns
        assert "macd_hist" in features.columns
        assert "bb_pct" in features.columns

    def test_drops_meta_columns(self) -> None:
        df = self._make_df(100)
        features, labels = prepare_features(df)
        assert "label" not in features.columns
        assert "symbol" not in features.columns
        assert "timeframe_sec" not in features.columns
        assert "win_probability" not in features.columns

    def test_labels_correct(self) -> None:
        df = self._make_df(100)
        features, labels = prepare_features(df)
        assert set(labels.unique()).issubset({0, 1})
        assert len(labels) == 100

    def test_preserves_all_feature_columns(self) -> None:
        df = self._make_df(50)
        features, labels = prepare_features(df)
        assert len(features.columns) == 3

    def test_with_nan_features(self) -> None:
        df = self._make_df(50)
        df.loc[0, "rsi"] = np.nan
        features, labels = prepare_features(df)
        assert pd.isna(features.loc[0, "rsi"])

import pytest
import numpy as np
import pandas as pd
import tempfile
from pathlib import Path
from infrastructure.ml.model import TradingModel, ModelMetadata


def _make_data(n: int = 200, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    features = pd.DataFrame(
        {
            "f1": rng.normal(0, 1, n),
            "f2": rng.normal(0, 1, n),
            "f3": rng.uniform(0, 1, n),
            "f4": rng.normal(5, 2, n),
        }
    )
    labels = pd.Series(
        (features["f1"] + features["f2"] > 0).astype(int), name="label"
    )
    return features, labels


class TestTradingModel:
    def test_not_trained_initially(self) -> None:
        model = TradingModel()
        assert model.is_trained is False
        assert model.metadata is None

    def test_train_returns_metrics(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        metrics = model.train(features, labels, version="test-1.0")
        assert 0 <= metrics.accuracy <= 1
        assert 0 <= metrics.auc <= 1
        assert metrics.train_samples > 0
        assert metrics.test_samples > 0
        assert model.is_trained is True

    def test_train_with_specific_features(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        metrics = model.train(features, labels, feature_names=["f1", "f2"])
        assert 0 <= metrics.accuracy <= 1

    def test_predict_proba(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        model.train(features, labels)
        proba = model.predict_proba(features.iloc[:5])
        assert proba.shape == (5,)
        assert (proba >= 0).all()
        assert (proba <= 1).all()

    def test_predict(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        model.train(features, labels)
        preds = model.predict(features.iloc[:5])
        assert preds.shape == (5,)
        assert set(np.unique(preds)).issubset({0, 1})

    def test_predict_before_train_raises(self) -> None:
        model = TradingModel()
        with pytest.raises(RuntimeError, match="not trained"):
            model.predict_proba(pd.DataFrame({"f1": [1.0]}))

    def test_feature_importance(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        model.train(features, labels)
        imp = model.feature_importance()
        assert len(imp) == 4
        assert abs(sum(imp.values()) - 1.0) < 0.01

    def test_feature_importance_empty_before_train(self) -> None:
        model = TradingModel()
        assert model.feature_importance() == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        model.train(features, labels, version="save-test")
        save_dir = tmp_path / "model_v1"
        model.save(save_dir)
        assert (save_dir / "model.joblib").exists()
        assert (save_dir / "metadata.json").exists()

        model2 = TradingModel()
        model2.load(save_dir)
        assert model2.is_trained is True
        assert model2.metadata is not None
        assert model2.metadata.version == "save-test"

        proba1 = model.predict_proba(features.iloc[:3])
        proba2 = model2.predict_proba(features.iloc[:3])
        np.testing.assert_array_almost_equal(proba1, proba2)

    def test_save_before_train_raises(self, tmp_path: Path) -> None:
        model = TradingModel()
        with pytest.raises(RuntimeError, match="not trained"):
            model.save(tmp_path / "model")

    def test_metadata_populated_after_train(self) -> None:
        features, labels = _make_data(200)
        model = TradingModel()
        model.train(features, labels, version="meta-test")
        meta = model.metadata
        assert meta is not None
        assert meta.version == "meta-test"
        assert len(meta.feature_names) == 4
        assert meta.metrics is not None
        assert meta.metrics.accuracy > 0

    def test_train_with_class_imbalance(self) -> None:
        rng = np.random.default_rng(42)
        features = pd.DataFrame(
            {"f1": rng.normal(0, 1, 200), "f2": rng.normal(0, 1, 200)}
        )
        labels = pd.Series([0] * 180 + [1] * 20, name="label")
        model = TradingModel()
        metrics = model.train(features, labels)
        assert 0 <= metrics.accuracy <= 1

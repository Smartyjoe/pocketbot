import numpy as np
import pandas as pd
from pathlib import Path
from infrastructure.ml.trainer import Trainer, TrainingConfig


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
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


class TestTrainer:
    def test_prepare_labels(self) -> None:
        trainer = Trainer()
        df = _make_ohlcv(200)
        labels = trainer.prepare_labels(df)
        assert len(labels) == 200
        assert set(labels.dropna().unique()).issubset({0.0, 1.0})
        assert labels.isna().sum() == 3

    def test_train_returns_result(self) -> None:
        trainer = Trainer()
        df = _make_ohlcv(200)
        result = trainer.train(df)
        assert 0 <= result.metrics.accuracy <= 1
        assert result.model_version == "1.0.0"
        assert result.labeled_rows > 0
        assert result.total_rows == 200

    def test_train_and_save(self, tmp_path: Path) -> None:
        trainer = Trainer()
        df = _make_ohlcv(200)
        result = trainer.train_and_save(df, tmp_path / "model")
        assert (tmp_path / "model" / "model.joblib").exists()
        assert (tmp_path / "model" / "metadata.json").exists()

    def test_load_model(self, tmp_path: Path) -> None:
        trainer1 = Trainer()
        df = _make_ohlcv(200)
        trainer1.train_and_save(df, tmp_path / "model")

        trainer2 = Trainer()
        trainer2.load_model(tmp_path / "model")
        assert trainer2.model.is_trained is True

    def test_custom_config(self) -> None:
        config = TrainingConfig(
            forward_bars=5,
            model_version="custom-2.0",
            test_ratio=0.3,
        )
        trainer = Trainer(config=config)
        df = _make_ohlcv(200)
        result = trainer.train(df)
        assert result.model_version == "custom-2.0"

    def test_model_accessible(self) -> None:
        trainer = Trainer()
        assert trainer.model.is_trained is False
        df = _make_ohlcv(200)
        trainer.train(df)
        assert trainer.model.is_trained is True

    def test_train_with_minimal_data(self) -> None:
        config = TrainingConfig(features__min_rows=20)
        trainer = Trainer(config=config)
        df = _make_ohlcv(60)
        result = trainer.train(df)
        assert 0 <= result.metrics.accuracy <= 1

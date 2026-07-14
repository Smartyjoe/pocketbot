"""Model training pipeline — OHLCV data → labeled features → trained model."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog
from pydantic import BaseModel, ConfigDict

from infrastructure.features.engine import FeatureConfig, FeatureEngine
from infrastructure.ml.model import ModelMetrics, TradingModel

logger = structlog.get_logger()


class TrainingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    features: FeatureConfig = FeatureConfig()
    forward_bars: int = 3
    min_label_ratio: float = 0.3
    model_version: str = "1.0.0"
    test_ratio: float = 0.2
    lgb_params: dict[str, Any] | None = None


class TrainingResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    metrics: ModelMetrics
    model_version: str
    feature_names: list[str]
    labeled_rows: int
    total_rows: int


class Trainer:
    def __init__(self, config: TrainingConfig | None = None) -> None:
        self._config = config or TrainingConfig()
        self._feature_engine = FeatureEngine(self._config.features)
        self._model = TradingModel()

    @property
    def model(self) -> TradingModel:
        return self._model

    def prepare_labels(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        future_return = close.shift(-self._config.forward_bars) / close - 1
        labels = pd.Series(np.nan, index=df.index, name="label")
        valid = future_return.notna()
        labels[valid] = (future_return[valid] > 0).astype(float)
        return labels

    def train(self, df: pd.DataFrame) -> TrainingResult:
        labels = self.prepare_labels(df)
        feature_result = self._feature_engine.build_features(df)

        valid = feature_result.valid_mask & labels.notna()
        features = feature_result.features.loc[valid]
        labels = labels.loc[valid]

        pos_ratio = labels.mean()
        if pos_ratio < self._config.min_label_ratio or pos_ratio > (
            1 - self._config.min_label_ratio
        ):
            logger.warning(
                "class_imbalance",
                positive_ratio=f"{pos_ratio:.2%}",
            )

        metrics = self._model.train(
            features=features,
            labels=labels,
            feature_names=self._feature_engine.feature_names,
            version=self._config.model_version,
            test_ratio=self._config.test_ratio,
            params=self._config.lgb_params,
        )

        logger.info(
            "training_complete",
            version=self._config.model_version,
            accuracy=f"{metrics.accuracy:.3f}",
            auc=f"{metrics.auc:.3f}",
        )

        return TrainingResult(
            metrics=metrics,
            model_version=self._config.model_version,
            feature_names=self._feature_engine.feature_names,
            labeled_rows=len(labels),
            total_rows=feature_result.row_count,
        )

    def train_and_save(self, df: pd.DataFrame, model_dir: Path) -> TrainingResult:
        result = self.train(df)
        self._model.save(model_dir)
        return result

    def load_model(self, model_dir: Path) -> None:
        self._model.load(model_dir)

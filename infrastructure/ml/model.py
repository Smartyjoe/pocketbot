"""LightGBM classifier wrapper for binary direction prediction."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import structlog
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger()


class ModelMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    accuracy: float
    precision: float
    recall: float
    f1: float
    auc: float
    train_samples: int
    test_samples: int
    feature_importance: dict[str, float]


class ModelMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    created_at: str
    feature_names: list[str]
    best_params: dict[str, Any]
    metrics: ModelMetrics | None = None


class TradingModel:
    def __init__(self) -> None:
        self._model: lgb.LGBMClassifier | None = None
        self._metadata: ModelMetadata | None = None

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    @property
    def metadata(self) -> ModelMetadata | None:
        return self._metadata

    def train(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        feature_names: list[str] | None = None,
        version: str = "1.0.0",
        test_ratio: float = 0.2,
        params: dict[str, Any] | None = None,
    ) -> ModelMetrics:
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import train_test_split

        clean_features = features[feature_names].copy() if feature_names else features.copy()
        clean_labels = labels.copy()

        valid_mask = clean_features.notna().all(axis=1) & clean_labels.notna()
        clean_features = clean_features.loc[valid_mask]
        clean_labels = clean_labels.loc[valid_mask].astype(int)

        X_train, X_test, y_train, y_test = train_test_split(
            clean_features, clean_labels, test_size=test_ratio, shuffle=False
        )

        train_classes = set(y_train.unique())
        test_classes = set(y_test.unique())
        if len(train_classes) < 2 or train_classes != test_classes:
            X_train, X_test, y_train, y_test = train_test_split(
                clean_features, clean_labels, test_size=test_ratio,
                shuffle=True, random_state=42,
                stratify=clean_labels if len(clean_labels.unique()) > 1 else None,
            )

        default_params = {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "max_depth": 6,
            "num_leaves": 31,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "random_state": 42,
            "verbose": -1,
            "n_jobs": -1,
        }
        if params:
            default_params.update(params)

        self._model = lgb.LGBMClassifier(**default_params)
        self._model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.log_evaluation(0)],
        )

        y_pred = self._model.predict(X_test)
        y_proba = self._model.predict_proba(X_test)[:, 1]

        feature_importance = dict(zip(
            clean_features.columns,
            self._model.feature_importances_.tolist(),
        ))
        total_imp = sum(feature_importance.values()) or 1
        feature_importance = {k: v / total_imp for k, v in feature_importance.items()}

        metrics = ModelMetrics(
            accuracy=accuracy_score(y_test, y_pred),
            precision=precision_score(y_test, y_pred, zero_division=0),
            recall=recall_score(y_test, y_pred, zero_division=0),
            f1=f1_score(y_test, y_pred, zero_division=0),
            auc=roc_auc_score(y_test, y_proba) if len(y_test.unique()) > 1 else 0.5,
            train_samples=len(X_train),
            test_samples=len(X_test),
            feature_importance=feature_importance,
        )

        self._metadata = ModelMetadata(
            version=version,
            created_at=datetime.now(timezone.utc).isoformat(),
            feature_names=clean_features.columns.tolist(),
            best_params={k: v for k, v in default_params.items() if k != "random_state"},
            metrics=metrics,
        )

        logger.info(
            "model_trained",
            version=version,
            accuracy=f"{metrics.accuracy:.3f}",
            auc=f"{metrics.auc:.3f}",
            train_samples=metrics.train_samples,
            test_samples=metrics.test_samples,
        )

        return metrics

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict_proba(features)[:, 1]

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self._model.predict(features)

    def feature_importance(self) -> dict[str, float]:
        if not self.is_trained or self._metadata is None:
            return {}
        if self._metadata.metrics is not None:
            return self._metadata.metrics.feature_importance
        return {}

    def save(self, path: Path) -> None:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, path / "model.joblib")
        meta_path = path / "metadata.json"
        meta_path.write_text(self._metadata.model_dump_json(indent=2))
        logger.info("model_saved", path=str(path), version=self._metadata.version)

    def load(self, path: Path) -> None:
        self._model = joblib.load(path / "model.joblib")
        meta_path = path / "metadata.json"
        if meta_path.exists():
            self._metadata = ModelMetadata.model_validate_json(meta_path.read_text())
        logger.info("model_loaded", path=str(path))

"""Feature engineering pipeline for ML signal generation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
import numpy as np
import pandas as pd
import structlog

from infrastructure.features.indicators.technical import (
    IndicatorConfig,
    TechnicalIndicators,
)

logger = structlog.get_logger()


class FeatureConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicators: IndicatorConfig = IndicatorConfig()
    lookback: int = 100
    min_rows: int = 50
    normalize: bool = True


class FeatureResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    features: pd.DataFrame
    feature_names: list[str]
    valid_mask: pd.Series
    row_count: int


class FeatureEngine:
    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or FeatureConfig()
        self._indicators = TechnicalIndicators(self._config.indicators)
        self._feature_names = self._indicators.feature_columns()

    @property
    def feature_names(self) -> list[str]:
        return list(self._feature_names)

    def build_features(self, df: pd.DataFrame) -> FeatureResult:
        with_indicators = self._indicators.compute(df)
        available = [c for c in self._feature_names if c in with_indicators.columns]
        missing = [c for c in self._feature_names if c not in with_indicators.columns]
        if missing:
            logger.warning("missing_indicator_columns", missing=missing)
        features = with_indicators[available].copy()
        for col in missing:
            features[col] = np.nan

        if self._config.normalize:
            features = self._normalize(features)

        valid_mask = features.notna().all(axis=1)

        logger.debug(
            "features_built",
            total_rows=len(features),
            valid_rows=int(valid_mask.sum()),
            feature_count=len(self._feature_names),
        )

        return FeatureResult(
            features=features,
            feature_names=list(self._feature_names),
            valid_mask=valid_mask,
            row_count=len(features),
        )

    def latest_features(self, df: pd.DataFrame) -> dict[str, float] | None:
        result = self.build_features(df)
        if result.row_count == 0 or not result.valid_mask.any():
            return None

        last_valid_idx = result.valid_mask[::-1].idxmax()
        row = result.features.loc[last_valid_idx]

        if not result.valid_mask.loc[last_valid_idx]:
            return None

        return {col: float(row[col]) for col in result.feature_names}

    def has_enough_data(self, df: pd.DataFrame) -> bool:
        return len(df) >= self._config.min_rows

    def _normalize(self, features: pd.DataFrame) -> pd.DataFrame:
        out = features.copy()
        for col in out.columns:
            series = out[col]
            if series.notna().sum() < 2:
                continue
            mean = series.mean()
            std = series.std()
            if std > 0:
                out[col] = (series - mean) / std
            else:
                out[col] = 0.0
        return out

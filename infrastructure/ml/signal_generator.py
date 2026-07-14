"""Signal generator — OHLCV candles → ML prediction → Signal entity."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pandas as pd
import structlog
from pydantic import BaseModel, ConfigDict

from domain.entities.signal import Signal
from domain.value_objects.confidence import Confidence
from domain.value_objects.direction import Direction
from domain.value_objects.symbol import Symbol
from infrastructure.features.engine import FeatureEngine, FeatureConfig
from infrastructure.ml.model import TradingModel

logger = structlog.get_logger()


class SignalConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    features: FeatureConfig = FeatureConfig()
    confidence_threshold: float = 0.55
    max_spread: float = 0.02


class SignalGenerator:
    def __init__(self, config: SignalConfig | None = None) -> None:
        self._config = config or SignalConfig()
        self._feature_engine = FeatureEngine(self._config.features)
        self._model = TradingModel()

    @property
    def is_ready(self) -> bool:
        return self._model.is_trained

    def load_model(self, model_dir: Path) -> None:
        self._model.load(model_dir)

    def generate(
        self,
        candles: pd.DataFrame,
        strategy_id: UUID,
        symbol: Symbol,
    ) -> Signal | None:
        if not self.is_ready:
            logger.warning("signal_generator_not_ready")
            return None

        if not self._feature_engine.has_enough_data(candles):
            logger.warning("insufficient_candle_data", rows=len(candles))
            return None

        feature_result = self._feature_engine.build_features(candles)
        last_idx = len(feature_result.features) - 1

        if not feature_result.valid_mask.iloc[last_idx]:
            logger.warning("latest_row_has_nan_features")
            return None

        feature_row = feature_result.features.iloc[last_idx:last_idx + 1]
        feature_dict = {
            col: float(feature_row[col].iloc[0])
            for col in feature_result.feature_names
        }

        win_probability = float(self._model.predict_proba(feature_row)[0])

        if win_probability >= self._config.confidence_threshold:
            direction = Direction.CALL
            confidence_score = win_probability
        elif win_probability <= (1 - self._config.confidence_threshold):
            direction = Direction.PUT
            confidence_score = 1 - win_probability
        else:
            logger.debug(
                "signal_below_threshold",
                win_prob=f"{win_probability:.3f}",
                threshold=self._config.confidence_threshold,
            )
            return None

        model_version = (
            self._model.metadata.version if self._model.metadata else ""
        )

        candle_ts = candles.index[-1] if isinstance(candles.index, pd.DatetimeIndex) else datetime.now(timezone.utc)
        if isinstance(candle_ts, pd.Timestamp):
            candle_ts = candle_ts.to_pydatetime()
        if candle_ts.tzinfo is None:
            candle_ts = candle_ts.replace(tzinfo=timezone.utc)

        signal = Signal.create(
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            confidence=Confidence(score=confidence_score),
            candle_timestamp=candle_ts,
            feature_values=feature_dict,
            model_version=model_version,
        )

        logger.info(
            "signal_generated",
            signal_id=str(signal.signal_id),
            direction=direction.value,
            confidence=f"{confidence_score:.3f}",
            win_prob=f"{win_probability:.3f}",
            symbol=symbol.code,
        )

        return signal

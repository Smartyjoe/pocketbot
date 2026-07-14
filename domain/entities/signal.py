from uuid import UUID, uuid4
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence


@dataclass
class Signal:
    signal_id: UUID
    strategy_id: UUID
    symbol: Symbol
    direction: Direction
    confidence: Confidence
    feature_values: dict[str, float]
    candle_timestamp: datetime
    created_at: datetime
    model_version: str
    is_approved: bool = False
    rejection_reason: str = ""

    @classmethod
    def create(
        cls,
        strategy_id: UUID,
        symbol: Symbol,
        direction: Direction,
        confidence: Confidence,
        candle_timestamp: datetime,
        feature_values: dict[str, float] | None = None,
        model_version: str = "",
    ) -> "Signal":
        return cls(
            signal_id=uuid4(),
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            feature_values=feature_values or {},
            candle_timestamp=candle_timestamp,
            created_at=datetime.now(timezone.utc),
            model_version=model_version,
        )

    def approve(self) -> None:
        self.is_approved = True
        self.rejection_reason = ""

    def reject(self, reason: str) -> None:
        self.is_approved = False
        self.rejection_reason = reason

from uuid import UUID
from datetime import datetime

from pydantic import Field

from domain.events.base import DomainEvent
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence


class SignalGenerated(DomainEvent):
    signal_id: UUID
    strategy_id: UUID
    symbol: Symbol
    direction: Direction
    confidence: Confidence
    feature_values: dict[str, float] = Field(default_factory=dict)
    candle_timestamp: datetime
    model_version: str = ""

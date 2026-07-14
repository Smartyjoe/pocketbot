from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class ConfidenceLabel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float

    @field_validator("score")
    @classmethod
    def _validate_score(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {v}")
        return v

    @property
    def label(self) -> ConfidenceLabel:
        if self.score >= 0.8:
            return ConfidenceLabel.HIGH
        if self.score >= 0.6:
            return ConfidenceLabel.MEDIUM
        return ConfidenceLabel.LOW

    def __bool__(self) -> bool:
        return self.score > 0.5

    def __str__(self) -> str:
        return f"{self.score:.0%}"

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, field_validator


class Timeframe(BaseModel):
    model_config = ConfigDict(frozen=True)

    seconds: int

    TF_60: int = 60
    TF_300: int = 300

    @field_validator("seconds")
    @classmethod
    def _validate_seconds(cls, v: int) -> int:
        allowed = {1, 5, 15, 30, 60, 300, 600, 900, 1800, 3600}
        if v not in allowed:
            raise ValueError(
                f"Timeframe {v}s is not supported. Allowed: {sorted(allowed)}"
            )
        return v

    def to_timedelta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    def __str__(self) -> str:
        if self.seconds < 60:
            return f"{self.seconds}s"
        return f"{self.seconds // 60}m"

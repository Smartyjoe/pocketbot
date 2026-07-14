from enum import Enum


class Direction(Enum):
    CALL = "call"
    PUT = "put"
    INVALID = "invalid"

    @classmethod
    def from_str(cls, s: str) -> "Direction":
        normalized = s.strip().lower()
        if normalized in ("call", "c"):
            return cls.CALL
        if normalized in ("put", "p"):
            return cls.PUT
        return cls.INVALID

    @property
    def opposite(self) -> "Direction":
        if self == Direction.CALL:
            return Direction.PUT
        if self == Direction.PUT:
            return Direction.CALL
        return Direction.INVALID

    @property
    def emoji(self) -> str:
        if self == Direction.CALL:
            return "\U0001f7e2"
        if self == Direction.PUT:
            return "\U0001f534"
        return "\u26ab"

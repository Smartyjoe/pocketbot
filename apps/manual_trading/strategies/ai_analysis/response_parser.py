"""Fail-closed JSON response parser for AI signals."""
from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("ai_analysis.parser")


class AIDirection(Enum):
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


@dataclass
class AISignal:
    direction: AIDirection
    confidence: float
    reasoning: str
    raw_response: str


_VALID_DIRECTIONS = {"UP", "DOWN", "NONE"}


def parse_ai_response(raw: str | None) -> AISignal:
    """Never raises. Any failure mode returns a NONE/0.0 signal."""
    if raw is None or not raw.strip():
        return AISignal(AIDirection.NONE, 0.0, "empty response", raw or "")

    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning(f"Unparseable AI response: {text[:200]}")
            return AISignal(AIDirection.NONE, 0.0, "unparseable response", raw)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning(f"Unparseable AI response (after extraction): {text[:200]}")
            return AISignal(AIDirection.NONE, 0.0, "unparseable response", raw)

    direction_raw = str(data.get("direction", "")).strip().upper()
    if direction_raw not in _VALID_DIRECTIONS:
        logger.warning(f"Invalid direction in AI response: {direction_raw!r}")
        return AISignal(AIDirection.NONE, 0.0, "invalid direction field", raw)

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return AISignal(AIDirection.NONE, 0.0, "invalid confidence field", raw)

    if not (0.0 <= confidence <= 1.0):
        confidence = max(0.0, min(1.0, confidence))

    reasoning = str(data.get("reasoning", "")).strip()[:300]

    direction = AIDirection(direction_raw)
    if direction == AIDirection.NONE:
        confidence = min(confidence, 0.0) if confidence > 0 else confidence

    return AISignal(direction, confidence, reasoning, raw)

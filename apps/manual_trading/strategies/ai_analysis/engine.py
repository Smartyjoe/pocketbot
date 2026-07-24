"""AI Analysis Engine — OpenRouter LLM strategy for the AI Analysis menu branch."""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from uuid import UUID

import pandas as pd

from .openrouter_client import OpenRouterClient
from .prompt_builder import build_prompt, SYSTEM_PROMPT
from .response_parser import parse_ai_response, AIDirection

logger = logging.getLogger("ai_analysis.engine")

AI_SHADOW_MODE = os.environ.get("AI_SHADOW_MODE", "false").lower() == "true"
AI_CONFIDENCE_THRESHOLD = float(os.environ.get("AI_CONFIDENCE_THRESHOLD", "0.7"))

CIRCUIT_BREAKER_FAILURE_LIMIT = 5
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 15 * 60


@dataclass
class AIAnalysisResult:
    has_signal: bool
    direction: str
    confidence: float
    reasoning: str
    shadow_mode: bool
    symbol: str
    timestamp: str
    model_response_raw: str


class _CircuitBreaker:
    def __init__(self, failure_limit: int, cooldown_seconds: int):
        self.failure_limit = failure_limit
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._open_until: float = 0.0

    def is_open(self) -> bool:
        return time.time() < self._open_until

    def record_success(self):
        self._consecutive_failures = 0

    def record_failure(self):
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_limit:
            self._open_until = time.time() + self.cooldown_seconds
            logger.error(
                f"AI circuit breaker OPEN — {self._consecutive_failures} consecutive "
                f"failures, disabling for {self.cooldown_seconds}s"
            )


class AIAnalysisEngine:
    def __init__(self, signal_store=None):
        self.client = OpenRouterClient()
        self.circuit_breaker = _CircuitBreaker(
            CIRCUIT_BREAKER_FAILURE_LIMIT, CIRCUIT_BREAKER_COOLDOWN_SECONDS
        )
        self.signal_store = signal_store

    async def analyze(
        self, df: pd.DataFrame, symbol: str, prediction_id: UUID | None = None
    ) -> AIAnalysisResult:
        now_iso = datetime.now(timezone.utc).isoformat()

        if self.circuit_breaker.is_open():
            logger.info("AI circuit breaker open — skipping")
            return self._no_signal_result(symbol, now_iso, "circuit breaker open")

        if len(df) < 20:
            return self._no_signal_result(symbol, now_iso, "insufficient candle history")

        prompt = build_prompt(df, symbol)
        raw_response = await self.client.complete(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        if raw_response is None:
            self.circuit_breaker.record_failure()
            return self._no_signal_result(symbol, now_iso, "no API response")

        self.circuit_breaker.record_success()

        ai_signal = parse_ai_response(raw_response)
        result = self._build_result(ai_signal, symbol, now_iso, raw_response)

        await self._log_to_store(result, prediction_id)

        return result

    def _build_result(
        self, ai_signal, symbol: str, timestamp: str, raw_response: str
    ) -> AIAnalysisResult:
        meets_threshold = (
            ai_signal.direction != AIDirection.NONE
            and ai_signal.confidence >= AI_CONFIDENCE_THRESHOLD
        )

        direction_map = {
            AIDirection.UP: "call",
            AIDirection.DOWN: "put",
            AIDirection.NONE: "none",
        }

        return AIAnalysisResult(
            has_signal=meets_threshold,
            direction=direction_map[ai_signal.direction],
            confidence=ai_signal.confidence,
            reasoning=ai_signal.reasoning,
            shadow_mode=AI_SHADOW_MODE,
            symbol=symbol,
            timestamp=timestamp,
            model_response_raw=raw_response,
        )

    def _no_signal_result(
        self, symbol: str, timestamp: str, reason: str
    ) -> AIAnalysisResult:
        result = AIAnalysisResult(
            has_signal=False,
            direction="none",
            confidence=0.0,
            reasoning=reason,
            shadow_mode=AI_SHADOW_MODE,
            symbol=symbol,
            timestamp=timestamp,
            model_response_raw="",
        )
        return result

    async def _log_to_store(
        self, result: AIAnalysisResult, prediction_id: UUID | None = None
    ):
        if self.signal_store is None:
            return
        try:
            await self.signal_store.insert(
                symbol=result.symbol,
                has_signal=result.has_signal,
                direction=result.direction,
                confidence=result.confidence,
                reasoning=result.reasoning,
                shadow_mode=result.shadow_mode,
                model_response_raw=result.model_response_raw,
                prediction_id=prediction_id,
            )
        except Exception as e:
            logger.error(f"Failed to log AI signal: {e}")

    async def close(self):
        await self.client.close()

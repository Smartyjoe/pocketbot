"""Async OpenRouter client with free-model discovery and fallback chain."""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("ai_analysis.openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_CACHE_TTL_SECONDS = 3 * 60 * 60


@dataclass
class ModelInfo:
    id: str
    context_length: int
    name: str


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        request_timeout: float = 15.0,
        max_retries: int = 3,
    ):
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self._api_key:
            logger.warning("OPENROUTER_API_KEY not set — AI analysis unavailable")

        self._request_timeout = request_timeout
        self._max_retries = max_retries

        self._client = httpx.AsyncClient(
            base_url=OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.environ.get("APP_URL", "https://localhost"),
                "X-Title": "PocketOption-AI-Signals",
            },
            timeout=request_timeout,
        )

        self._free_models_cache: list[ModelInfo] = []
        self._cache_timestamp: float = 0.0

    async def _refresh_free_models(self) -> list[ModelInfo]:
        resp = await self._client.get("/models")
        resp.raise_for_status()
        data = resp.json().get("data", [])

        free_models = []
        for m in data:
            pricing = m.get("pricing", {})
            prompt_cost = float(pricing.get("prompt", "1") or "1")
            completion_cost = float(pricing.get("completion", "1") or "1")
            if prompt_cost == 0.0 and completion_cost == 0.0:
                free_models.append(
                    ModelInfo(
                        id=m["id"],
                        context_length=m.get("context_length", 0),
                        name=m.get("name", m["id"]),
                    )
                )

        free_models.sort(key=lambda m: m.context_length, reverse=True)

        if not free_models:
            logger.warning("No free models found on OpenRouter")

        self._free_models_cache = free_models
        self._cache_timestamp = time.time()
        return free_models

    async def get_free_models(self, force_refresh: bool = False) -> list[ModelInfo]:
        cache_stale = (time.time() - self._cache_timestamp) > MODELS_CACHE_TTL_SECONDS
        if force_refresh or cache_stale or not self._free_models_cache:
            try:
                return await self._refresh_free_models()
            except Exception as e:
                logger.error(f"Failed to refresh free model list: {e}")
                return self._free_models_cache
        return self._free_models_cache

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 300,
        temperature: float = 0.2,
    ) -> Optional[str]:
        if not self._api_key:
            return None

        models = await self.get_free_models()
        if not models:
            logger.error("No free models available")
            return None

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        attempts = 0
        for model in models:
            if attempts >= self._max_retries:
                break
            attempts += 1
            try:
                resp = await self._client.post(
                    "/chat/completions",
                    json={
                        "model": model.id,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 429:
                    logger.warning(f"{model.id} rate-limited, trying next")
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                logger.info(f"AI response from {model.id}")
                return content
            except httpx.TimeoutException:
                logger.warning(f"{model.id} timed out, trying next")
                continue
            except Exception as e:
                logger.warning(f"{model.id} failed: {e}, trying next")
                continue

        logger.error("All free model attempts failed")
        return None

    async def close(self):
        await self._client.aclose()

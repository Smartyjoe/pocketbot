"""Tests for AIAnalysisEngine with mocked OpenRouterClient."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pandas as pd
import numpy as np
import pytest

from apps.manual_trading.strategies.ai_analysis.engine import (
    AIAnalysisEngine,
    AIAnalysisResult,
)


def _sample_df() -> pd.DataFrame:
    np.random.seed(1)
    n = 30
    dates = pd.date_range("2026-07-24 09:00:00", periods=n, freq="1min")
    closes = np.cumsum(np.random.randn(n) * 0.1) + 1.0
    return pd.DataFrame({
        "open": closes - 0.001,
        "high": closes + 0.005,
        "low": closes - 0.005,
        "close": closes,
        "rsi": np.clip(np.random.randn(n) * 15 + 50, 0, 100),
        "adx": np.clip(np.random.randn(n) * 10 + 25, 0, 100),
        "zscore": np.random.randn(n),
        "stoch_k": np.clip(np.random.randn(n) * 20 + 50, 0, 100),
        "stoch_d": np.clip(np.random.randn(n) * 15 + 50, 0, 100),
    }, index=dates)


@pytest.fixture
def engine():
    return AIAnalysisEngine()


@pytest.fixture
def engine_with_store():
    store = AsyncMock()
    store.insert = AsyncMock()
    return AIAnalysisEngine(signal_store=store), store


@pytest.mark.asyncio
async def test_analyze_circuit_breaker_returns_no_signal(engine):
    engine.circuit_breaker._consecutive_failures = 5
    engine.circuit_breaker._open_until = 10**10
    result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is False
    assert result.reasoning == "circuit breaker open"


@pytest.mark.asyncio
async def test_analyze_insufficient_data(engine):
    df = pd.DataFrame({"close": [1.0, 2.0]})
    result = await engine.analyze(df, "EURUSD_otc")
    assert result.has_signal is False
    assert "insufficient" in result.reasoning


@pytest.mark.asyncio
async def test_analyze_client_unavailable_returns_no_signal(engine):
    with patch.object(engine.client, "complete", return_value=None):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is False
    assert result.reasoning == "no API response"


@pytest.mark.asyncio
async def test_analyze_valid_signal(engine):
    valid_json = (
        '{"direction": "up", "confidence": 0.85, "reasoning": "strong uptrend"}'
    )
    with patch.object(engine.client, "complete", return_value=valid_json):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is True
    assert result.direction == "call"
    assert result.confidence >= 0.7
    assert result.reasoning == "strong uptrend"
    assert result.symbol == "EURUSD_otc"


@pytest.mark.asyncio
async def test_analyze_low_confidence_rejected(engine):
    valid_json = (
        '{"direction": "up", "confidence": 0.4, "reasoning": "weak signal"}'
    )
    with patch.object(engine.client, "complete", return_value=valid_json):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is False
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_analyze_put_signal(engine):
    valid_json = (
        '{"direction": "down", "confidence": 0.78, "reasoning": "bearish setup"}'
    )
    with patch.object(engine.client, "complete", return_value=valid_json):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is True
    assert result.direction == "put"
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_analyze_with_prediction_id(engine_with_store):
    engine, store = engine_with_store
    valid_json = (
        '{"direction": "up", "confidence": 0.85, "reasoning": "strong uptrend"}'
    )
    pid = uuid4()
    with patch.object(engine.client, "complete", return_value=valid_json):
        result = await engine.analyze(_sample_df(), "EURUSD_otc", prediction_id=pid)
    assert result.has_signal is True
    store.insert.assert_awaited_once()
    call_kwargs = store.insert.await_args[1]
    assert call_kwargs["prediction_id"] == pid


@pytest.mark.asyncio
async def test_signal_store_logged_on_failure(engine_with_store):
    engine, store = engine_with_store
    # Parsed response with NONE direction — still logs
    with patch.object(engine.client, "complete", return_value='{"direction": "none", "confidence": 0.0, "reasoning": "no signal"}'):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert result.has_signal is False
    store.insert.assert_awaited_once()
    call_kwargs = store.insert.await_args[1]
    assert call_kwargs["has_signal"] is False
    assert call_kwargs["symbol"] == "EURUSD_otc"


@pytest.mark.asyncio
async def test_result_is_always_an_alanalysis_result(engine):
    with patch.object(engine.client, "complete", return_value=None):
        result = await engine.analyze(_sample_df(), "EURUSD_otc")
    assert isinstance(result, AIAnalysisResult)


@pytest.mark.asyncio
async def test_close_does_not_raise(engine):
    with patch.object(engine.client, "close", return_value=None):
        await engine.close()

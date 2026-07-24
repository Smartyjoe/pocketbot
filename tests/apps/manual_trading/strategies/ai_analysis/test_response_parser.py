"""Tests for response_parser — AISignal parsing from LLM output."""
import json

from apps.manual_trading.strategies.ai_analysis.response_parser import (
    parse_ai_response,
    AISignal,
    AIDirection,
)


def test_parse_valid_call_signal():
    raw = json.dumps({
        "direction": "up",
        "confidence": 0.85,
        "reasoning": "Strong uptrend with RSI support",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.UP
    assert result.confidence == 0.85
    assert result.reasoning == "Strong uptrend with RSI support"


def test_parse_valid_put_signal():
    raw = json.dumps({
        "direction": "down",
        "confidence": 0.72,
        "reasoning": "Bearish divergence detected",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.DOWN
    assert result.confidence == 0.72
    assert result.reasoning == "Bearish divergence detected"


def test_parse_no_signal():
    raw = json.dumps({
        "direction": "none",
        "confidence": 0.0,
        "reasoning": "Market conditions are unclear",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.NONE
    assert result.confidence == 0.0


def test_parse_case_insensitive_direction():
    raw = json.dumps({
        "direction": "UP",
        "confidence": 0.9,
        "reasoning": "Clear signal",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.UP


def test_parse_invalid_json_returns_safe_default():
    result = parse_ai_response("not json at all")
    assert result.direction == AIDirection.NONE
    assert result.confidence == 0.0
    assert result.reasoning == "unparseable response"


def test_parse_empty_string():
    result = parse_ai_response("")
    assert result.direction == AIDirection.NONE
    assert result.confidence == 0.0


def test_parse_none_input():
    result = parse_ai_response(None)
    assert result.direction == AIDirection.NONE


def test_parse_with_code_fence():
    raw = "```json\n{\"direction\": \"up\", \"confidence\": 0.8, \"reasoning\": \"test\"}\n```"
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.UP
    assert result.confidence == 0.8


def test_parse_with_extra_text():
    raw = "Here is my analysis:\n\n{\"direction\": \"down\", \"confidence\": 0.75, \"reasoning\": \"bearish\"}\n\nGood luck!"
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.DOWN
    assert result.confidence == 0.75


def test_parse_missing_direction():
    raw = json.dumps({"confidence": 0.8, "reasoning": "test"})
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.NONE


def test_parse_missing_confidence_defaults_zero():
    raw = json.dumps({"direction": "up", "reasoning": "test"})
    result = parse_ai_response(raw)
    assert result.confidence == 0.0


def test_parse_confidence_string():
    raw = json.dumps({
        "direction": "up",
        "confidence": "0.75",
        "reasoning": "test",
    })
    result = parse_ai_response(raw)
    assert result.confidence == 0.75


def test_parse_confidence_below_zero_clamped():
    raw = json.dumps({
        "direction": "up",
        "confidence": -0.5,
        "reasoning": "test",
    })
    result = parse_ai_response(raw)
    assert result.confidence == 0.0


def test_parse_confidence_above_one_clamped():
    raw = json.dumps({
        "direction": "up",
        "confidence": 1.5,
        "reasoning": "test",
    })
    result = parse_ai_response(raw)
    assert result.confidence == 1.0


def test_parse_none_direction_forces_confidence_to_zero():
    raw = json.dumps({
        "direction": "none",
        "confidence": 0.9,
        "reasoning": "test",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.NONE
    assert result.confidence == 0.0


def test_parse_extra_fields_ignored():
    raw = json.dumps({
        "direction": "down",
        "confidence": 0.65,
        "reasoning": "test",
        "extra": "ignored",
    })
    result = parse_ai_response(raw)
    assert result.direction == AIDirection.DOWN
    assert result.confidence == 0.65
    assert result.reasoning == "test"

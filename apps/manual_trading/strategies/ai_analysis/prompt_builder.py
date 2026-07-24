"""Build AI prompts from pre-computed indicators and candle data."""
from __future__ import annotations

import pandas as pd

SYSTEM_PROMPT = """You are a quantitative market analyst evaluating short-term \
(5-minute) price direction for a binary options context. You will be given \
recent candle data and pre-computed technical indicators.

Respond with ONLY a JSON object, no other text, no markdown formatting:
{"direction": "UP", "confidence": 0.75, "reasoning": "one short sentence"}

direction must be one of: "UP", "DOWN", "NONE"
confidence must be a float between 0.0 and 1.0
Use "NONE" with low confidence if signals are mixed or unclear — do not \
guess a direction just to have an answer."""


def build_prompt(df: pd.DataFrame, symbol: str, lookback: int = 15) -> str:
    """Build the user prompt from the most recent candle+indicator data."""
    recent = df.tail(lookback)

    candle_lines = []
    for ts, row in recent.iterrows():
        candle_lines.append(
            f"{ts.strftime('%H:%M')} O:{row['open']:.5f} H:{row['high']:.5f} "
            f"L:{row['low']:.5f} C:{row['close']:.5f}"
        )
    candles_block = "\n".join(candle_lines)

    last = df.iloc[-1]
    indicators_block = (
        f"RSI(14): {last.get('rsi', float('nan')):.1f}\n"
        f"ADX(14): {last.get('adx', float('nan')):.1f}\n"
        f"Z-score(20): {last.get('zscore', float('nan')):.2f}\n"
        f"Stochastic %K/%D: {last.get('stoch_k', float('nan')):.1f} / "
        f"{last.get('stoch_d', float('nan')):.1f}\n"
    )

    prompt = f"""Asset: {symbol}
Timeframe: 5 minute expiry
Recent candles (most recent last):
{candles_block}

Current indicator readings:
{indicators_block}

Based on this data, what is the most likely direction for the next 5-minute \
candle? Respond with the JSON format specified."""

    return prompt

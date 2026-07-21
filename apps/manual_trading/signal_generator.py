"""Rule-based signal generation from technical indicators.

Scoring system:
- Each indicator votes CALL or PUT with a weight
- Final direction = majority vote weighted by strength
- Confidence = agreement ratio among indicators

Indicators used:
- RSI (oversold/overbought)
- MACD (histogram direction + crossover)
- EMA cross (fast vs slow)
- Bollinger Band position (%b)
- Stochastic (K/D crossover)
- Price momentum (ROC)
- ATR volatility filter
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from apps.manual_trading.models import Signal

logger = logging.getLogger(__name__)

# Minimum candles needed for signal generation.
# With <26 candles, MACD slow EMA is unstable but still produces values.
# The signal scorer skips indicators with NaN, so degraded data still works.
MIN_CANDLES = 16


def generate_signal(df_with_indicators: pd.DataFrame) -> Signal:
    """Generate a trading signal from a DataFrame that already has indicators computed.

    Args:
        df_with_indicators: DataFrame with columns from TechnicalIndicators.compute()

    Returns:
        Signal with direction, confidence, and reasoning bullets.
    """
    if len(df_with_indicators) < MIN_CANDLES:
        return Signal(
            direction="call",
            confidence=0.5,
            reasoning=["Insufficient data for analysis"],
            indicators={},
        )

    last = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]

    votes: list[tuple[str, float]] = []
    reasoning: list[str] = []
    indicator_snapshot: dict[str, float] = {}

    # --- RSI ---
    rsi = _safe(last, "rsi")
    indicator_snapshot["rsi"] = rsi
    if not np.isnan(rsi):
        if rsi < 30:
            votes.append(("call", 0.8))
            reasoning.append(f"RSI {rsi:.0f} — oversold, bullish reversal likely")
        elif rsi > 70:
            votes.append(("put", 0.8))
            reasoning.append(f"RSI {rsi:.0f} — overbought, bearish reversal likely")
        elif rsi < 40:
            votes.append(("call", 0.6))
            reasoning.append(f"RSI {rsi:.0f} — leaning oversold")
        elif rsi > 60:
            votes.append(("put", 0.6))
            reasoning.append(f"RSI {rsi:.0f} — leaning overbought")
        else:
            votes.append(("call", 0.5))
            reasoning.append(f"RSI {rsi:.0f} — neutral zone")

    # --- MACD ---
    macd_hist = _safe(last, "macd_hist")
    prev_macd_hist = _safe(prev, "macd_hist")
    indicator_snapshot["macd_hist"] = macd_hist
    if not np.isnan(macd_hist) and not np.isnan(prev_macd_hist):
        if macd_hist > 0 and prev_macd_hist <= 0:
            votes.append(("call", 0.85))
            reasoning.append("MACD bullish crossover — momentum shifting up")
        elif macd_hist < 0 and prev_macd_hist >= 0:
            votes.append(("put", 0.85))
            reasoning.append("MACD bearish crossover — momentum shifting down")
        elif macd_hist > 0:
            votes.append(("call", 0.6))
            reasoning.append("MACD histogram positive — bullish momentum")
        else:
            votes.append(("put", 0.6))
            reasoning.append("MACD histogram negative — bearish momentum")

    # --- EMA Cross ---
    ema_cross = _safe(last, "ema_cross")
    indicator_snapshot["ema_cross"] = ema_cross
    if not np.isnan(ema_cross):
        if ema_cross > 0.0005:
            votes.append(("call", 0.7))
            reasoning.append("Fast EMA above slow EMA — uptrend")
        elif ema_cross < -0.0005:
            votes.append(("put", 0.7))
            reasoning.append("Fast EMA below slow EMA — downtrend")
        else:
            reasoning.append("EMAs intertwined — no clear trend")

    # --- Bollinger Band %b ---
    bb_pct = _safe(last, "bb_pct")
    indicator_snapshot["bb_pct"] = bb_pct
    if not np.isnan(bb_pct):
        if bb_pct < 0.05:
            votes.append(("call", 0.75))
            reasoning.append(f"Price at lower Bollinger band ({bb_pct:.2f}) — bounce expected")
        elif bb_pct > 0.95:
            votes.append(("put", 0.75))
            reasoning.append(f"Price at upper Bollinger band ({bb_pct:.2f}) — pullback expected")
        elif bb_pct < 0.2:
            votes.append(("call", 0.6))
            reasoning.append(f"Price near lower band ({bb_pct:.2f})")
        elif bb_pct > 0.8:
            votes.append(("put", 0.6))
            reasoning.append(f"Price near upper band ({bb_pct:.2f})")

    # --- Stochastic ---
    stoch_k = _safe(last, "stoch_k")
    stoch_d = _safe(last, "stoch_d")
    prev_stoch_k = _safe(prev, "stoch_k")
    prev_stoch_d = _safe(prev, "stoch_d")
    indicator_snapshot["stoch_k"] = stoch_k
    indicator_snapshot["stoch_d"] = stoch_d
    if not any(np.isnan(x) for x in [stoch_k, stoch_d, prev_stoch_k, prev_stoch_d]):
        if stoch_k > stoch_d and prev_stoch_k <= prev_stoch_d and stoch_k < 30:
            votes.append(("call", 0.8))
            reasoning.append("Stochastic bullish crossover in oversold zone")
        elif stoch_k < stoch_d and prev_stoch_k >= prev_stoch_d and stoch_k > 70:
            votes.append(("put", 0.8))
            reasoning.append("Stochastic bearish crossover in overbought zone")
        elif stoch_k < 20:
            votes.append(("call", 0.6))
            reasoning.append(f"Stochastic oversold ({stoch_k:.0f})")
        elif stoch_k > 80:
            votes.append(("put", 0.6))
            reasoning.append(f"Stochastic overbought ({stoch_k:.0f})")

    # --- ROC (momentum) ---
    roc = _safe(last, "roc_5")
    indicator_snapshot["roc_5"] = roc
    if not np.isnan(roc):
        if roc > 0.002:
            votes.append(("call", 0.6))
            reasoning.append(f"Price rising ({roc:.3%} over 5 bars)")
        elif roc < -0.002:
            votes.append(("put", 0.6))
            reasoning.append(f"Price falling ({roc:.3%} over 5 bars)")

    # --- ATR volatility filter ---
    atr_pct = _safe(last, "atr_pct")
    indicator_snapshot["atr_pct"] = atr_pct

    # --- Compute final signal ---
    if not votes:
        return Signal(
            direction="call",
            confidence=0.5,
            reasoning=["No clear signal from indicators"],
            indicators=indicator_snapshot,
        )

    call_weight = sum(w for d, w in votes if d == "call")
    put_weight = sum(w for d, w in votes if d == "put")
    total_weight = call_weight + put_weight

    if call_weight > put_weight:
        direction = "call"
        confidence = call_weight / total_weight
    elif put_weight > call_weight:
        direction = "put"
        confidence = put_weight / total_weight
    else:
        direction = "call"
        confidence = 0.5

    # Clamp confidence to [0.55, 0.95]
    confidence = max(0.55, min(0.95, confidence))

    # Add summary bullet
    summary = f"{'Bullish' if direction == 'call' else 'Bearish'} consensus from {len(votes)} indicators"
    reasoning.insert(0, summary)

    return Signal(
        direction=direction,
        confidence=round(confidence, 2),
        reasoning=reasoning[:5],
        indicators=_clean_nan(indicator_snapshot),
    )


def _clean_nan(d: dict[str, float]) -> dict[str, float | None]:
    """Replace NaN/Inf float values with None for JSON safety.

    PostgreSQL JSON columns reject ``NaN`` tokens.  Converting them
    to ``None`` ensures ``json.dumps`` emits ``null`` instead.
    """
    return {
        k: (None if isinstance(v, float) and (np.isnan(v) or np.isinf(v)) else v)
        for k, v in d.items()
    }


def _safe(row: pd.Series, col: str) -> float:
    """Safely extract a float from a row, returning NaN if missing."""
    val = row.get(col)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return float("nan")
    return float(val)

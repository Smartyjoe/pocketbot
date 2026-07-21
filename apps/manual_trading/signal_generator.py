"""Rule-based signal generation — always-signal directional confidence scoring.

Strategy:
  Always produce a signal with has_signal=True (except insufficient data).
  Confidence reflects how strongly indicators agree on the direction.

Direction detection:
  - Primary: EMA 10/30 cross sign determines call/put.
  - ROC breaks ties when EMA cross is negligible (mild trend).
  - Falls back to "call" if both EMA cross and ROC are NaN.

Confidence scoring (base 0.50):
  +0.05  Strong EMA trend (|cross| > 0.2% of close)
  +0.02  Mild EMA trend (|cross| > 0.05% of close)
  +0.08  ROC agrees with direction
  +0.05  MACD histogram agrees with direction
  +0.05  RSI favorable zone (oversold in downtrend / overbought in uptrend)
  +0.03  RSI entry zone (RSI dip buy / sell zone)
  +0.03  Stochastic crossover confirms direction
  +0.03  Bollinger position confirms direction
  -0.10  ATR spike (extreme volatility penalty)

Final confidence clamped to [0.35, 0.90].
has_signal=True always (safety fallback only).

Indicators reused from TechnicalIndicators:
- EMA 10/30 cross (trend direction)
- MACD (12/26/9) histogram (trend confirmation)
- RSI (14) — favorability + entry timing
- Stochastic (14/3) — crossover confirmation
- Bollinger %b (20/2) — position confirmation
- ROC (5-bar) — momentum direction
- ATR (14) — volatility penalty
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from apps.manual_trading.constants import (
    TREND_STRONG_THRESHOLD,
    TREND_MILD_THRESHOLD,
    RSI_FAVORABLE_LOW,
    RSI_FAVORABLE_HIGH,
    ATR_SPIKE_MULTIPLIER,
    ATR_SMA_WINDOW,
)
from apps.manual_trading.models import Signal

logger = logging.getLogger(__name__)

MIN_CANDLES = 16


def generate_signal(df_with_indicators: pd.DataFrame) -> Signal:
    """Generate a directional signal with confidence from indicator confluence.

    Always returns has_signal=True when data is sufficient.
    Confidence reflects the strength of indicator agreement on direction.

    Args:
        df_with_indicators: DataFrame with columns from TechnicalIndicators.compute()

    Returns:
        Signal with has_signal, direction, confidence, reasoning, indicators.
    """
    if len(df_with_indicators) < MIN_CANDLES:
        return Signal(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=["Insufficient data for analysis"],
            indicators={},
        )

    last = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]

    indicator_snapshot = _build_indicator_snapshot(last)

    # --- Direction detection ---
    direction = _detect_direction(last)
    if direction is None:
        return Signal(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=["Unable to determine direction — insufficient indicator data"],
            indicators=indicator_snapshot,
        )

    # --- Confidence scoring ---
    base = 0.50
    bonuses, scoring_reasons = _score_confidence(last, prev, df_with_indicators, direction)

    confidence = base + bonuses
    confidence = max(0.35, min(0.90, confidence))
    confidence = round(confidence, 2)

    # Build reasoning
    direction_label = "Uptrend" if direction == "call" else "Downtrend"
    summary = f"{direction_label} signal — {confidence:.0%} confidence"
    all_reasons = [summary] + scoring_reasons

    return Signal(
        has_signal=True,
        direction=direction,
        confidence=confidence,
        reasoning=all_reasons[:5],
        indicators=indicator_snapshot,
    )


# ---------------------------------------------------------------------------
# Direction Detection
# ---------------------------------------------------------------------------

def _detect_direction(last: pd.Series) -> str | None:
    """Determine trade direction using EMA cross sign and ROC tiebreaker.

    Returns:
        'call' (up), 'put' (down), or None if both EMA and ROC are NaN.
    """
    ema_cross = _safe(last, "ema_cross")
    roc = _safe(last, "roc_5")

    # EMA cross sign determines direction
    if not np.isnan(ema_cross):
        if abs(ema_cross) > TREND_MILD_THRESHOLD:
            return "call" if ema_cross > 0 else "put"

    # EMA cross is NaN or too small — use ROC as tiebreaker
    if not np.isnan(roc):
        return "call" if roc > 0 else "put"

    # Both NaN — cannot determine direction
    return None


# ---------------------------------------------------------------------------
# Confidence Scoring
# ---------------------------------------------------------------------------

def _score_confidence(
    last: pd.Series, prev: pd.Series, df: pd.DataFrame, direction: str
) -> tuple[float, list[str]]:
    """Score confidence from indicator agreement with the determined direction.

    Returns:
        (total_bonus, reasoning_list). Bonus ranges roughly -0.10 to +0.29.
    """
    total_bonus = 0.0
    reasoning: list[str] = []
    is_up = direction == "call"

    # --- EMA trend strength bonus ---
    ema_cross = _safe(last, "ema_cross")
    close = _safe(last, "close")
    if not np.isnan(ema_cross) and not np.isnan(close) and close > 0:
        normalized = abs(ema_cross) / close
        if normalized > TREND_STRONG_THRESHOLD:
            total_bonus += 0.05
            reasoning.append(
                f"Strong EMA trend (cross {ema_cross:.6f}, {normalized:.4%} of price)"
            )
        elif normalized > TREND_MILD_THRESHOLD:
            total_bonus += 0.02
            reasoning.append(
                f"Mild EMA trend (cross {ema_cross:.6f}, {normalized:.4%} of price)"
            )

    # --- ROC direction bonus ---
    roc = _safe(last, "roc_5")
    if not np.isnan(roc):
        roc_agrees = (roc > 0) == is_up
        if roc_agrees:
            total_bonus += 0.08
            reasoning.append(f"ROC confirms {direction} ({roc:+.4%})")
        else:
            reasoning.append(f"ROC diverges ({roc:+.4%})")

    # --- MACD histogram bonus ---
    macd_hist = _safe(last, "macd_hist")
    if not np.isnan(macd_hist):
        macd_agrees = (macd_hist > 0) == is_up
        if macd_agrees:
            total_bonus += 0.05
            reasoning.append(f"MACD histogram confirms {direction}")
        else:
            reasoning.append(f"MACD histogram diverges")

    # --- RSI favorability bonus ---
    rsi = _safe(last, "rsi")
    if not np.isnan(rsi):
        # Favorable zone: oversold in downtrend, overbought in uptrend
        rsi_favorable = (
            (is_up and rsi < RSI_FAVORABLE_LOW)
            or (not is_up and rsi > RSI_FAVORABLE_HIGH)
        )
        if rsi_favorable:
            total_bonus += 0.05
            reasoning.append(
                f"RSI {rsi:.0f} favorable for {direction} "
                f"({'oversold' if is_up else 'overbought'} zone)"
            )
        # Entry zone bonus (separate from favorability)
        entry_zone = (
            (is_up and 30 <= rsi <= 50)
            or (not is_up and 50 <= rsi <= 70)
        )
        if entry_zone:
            total_bonus += 0.03
            reasoning.append(f"RSI {rsi:.0f} in entry zone")

    # --- Stochastic crossover bonus ---
    stoch_k = _safe(last, "stoch_k")
    stoch_d = _safe(last, "stoch_d")
    prev_stoch_k = _safe(prev, "stoch_k")
    prev_stoch_d = _safe(prev, "stoch_d")
    if not any(np.isnan(x) for x in [stoch_k, stoch_d, prev_stoch_k, prev_stoch_d]):
        bullish_cross = stoch_k > stoch_d and prev_stoch_k <= prev_stoch_d
        bearish_cross = stoch_k < stoch_d and prev_stoch_k >= prev_stoch_d
        if (is_up and bullish_cross) or (not is_up and bearish_cross):
            total_bonus += 0.03
            reasoning.append(
                f"Stochastic {'bullish' if is_up else 'bearish'} crossover "
                f"(K={stoch_k:.0f}, D={stoch_d:.0f})"
            )

    # --- Bollinger position bonus ---
    bb_pct = _safe(last, "bb_pct")
    if not np.isnan(bb_pct):
        bb_confirms = (is_up and bb_pct < 0.3) or (not is_up and bb_pct > 0.7)
        if bb_confirms:
            total_bonus += 0.03
            band = "lower" if is_up else "upper"
            reasoning.append(f"Price near {band} Bollinger band ({bb_pct:.2f})")

    # --- ATR volatility penalty ---
    atr_penalty, atr_reason = _score_volatility_penalty(last, df)
    total_bonus += atr_penalty
    if atr_reason:
        reasoning.append(atr_reason)

    return total_bonus, reasoning


def _score_volatility_penalty(
    last: pd.Series, df: pd.DataFrame
) -> tuple[float, str | None]:
    """Return ATR volatility penalty and optional reason string.

    Penalizes confidence when ATR% spikes above its SMA — extreme volatility.
    """
    atr_pct = _safe(last, "atr_pct")
    if np.isnan(atr_pct):
        return 0.0, None

    window = min(ATR_SMA_WINDOW, len(df))
    if window < 3:
        return 0.0, None

    atr_pct_series = df["atr_pct"].dropna()
    if len(atr_pct_series) < window:
        return 0.0, None

    atr_sma = atr_pct_series.iloc[-window:].mean()
    if np.isnan(atr_sma) or atr_sma == 0:
        return 0.0, None

    if atr_pct > ATR_SPIKE_MULTIPLIER * atr_sma:
        return -0.10, (
            f"ATR spike — high volatility "
            f"(ATR% {atr_pct:.4f} > {ATR_SPIKE_MULTIPLIER}x SMA {atr_sma:.4f})"
        )

    return 0.0, None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _build_indicator_snapshot(last: pd.Series) -> dict[str, float | None]:
    """Extract key indicator values for the signal snapshot."""
    keys = ["rsi", "macd_hist", "bb_pct", "stoch_k", "stoch_d", "roc_5", "atr_pct"]
    snapshot: dict[str, float | None] = {}
    for k in keys:
        val = _safe(last, k)
        snapshot[k] = None if np.isnan(val) else val
    return snapshot


def _clean_nan(d: dict[str, float]) -> dict[str, float | None]:
    """Replace NaN/Inf float values with None for JSON safety."""
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

"""Rule-based signal generation — trend-following confluence pipeline.

Stages:
1. TREND DETECTION — EMA cross dead zone + MACD confirmation
2. MOMENTUM GATE — MACD histogram + ROC must agree with trend
3. ENTRY TIMING — RSI zone, Stochastic cross, Bollinger position
4. VOLATILITY FILTER — ATR spike rejection
5. CONFIDENCE SCORING — base + bonuses, clamped, gated by MIN_CONFIDENCE

Indicators reused from TechnicalIndicators:
- EMA 10/30 cross (trend direction)
- MACD (12/26/9) histogram (trend confirmation + momentum)
- RSI (14) — entry timing zone
- Stochastic (14/3) — crossover confirmation
- Bollinger %b (20/2) — edge confirmation
- ROC (5-bar) — momentum agreement
- ATR (14) — volatility filter
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from apps.manual_trading.constants import (
    MIN_CONFIDENCE,
    TREND_DEAD_ZONE,
    RSI_ENTRY_LOW,
    RSI_ENTRY_HIGH,
    RSI_ENTRY_LOW_DOWN,
    RSI_ENTRY_HIGH_DOWN,
    ATR_SPIKE_MULTIPLIER,
    ATR_SMA_WINDOW,
)
from apps.manual_trading.models import Signal

logger = logging.getLogger(__name__)

MIN_CANDLES = 16


def generate_signal(df_with_indicators: pd.DataFrame) -> Signal:
    """Generate a trading signal from a DataFrame that already has indicators.

    Pipeline: trend → momentum → entry timing → volatility → confidence.
    Returns a Signal with has_signal=True only when all gates pass and
    confidence >= MIN_CONFIDENCE.

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

    # --- Stage 1: Trend Detection ---
    trend, trend_reasons = _detect_trend(last, prev)
    if trend is None:
        return Signal(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=trend_reasons,
            indicators=indicator_snapshot,
        )

    # --- Stage 2: Momentum Gate ---
    momentum_ok, momentum_reasons = _check_momentum(last, prev, trend)
    if not momentum_ok:
        return Signal(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=trend_reasons + momentum_reasons,
            indicators=indicator_snapshot,
        )

    # --- Stage 3: Entry Timing ---
    entry_score, entry_reasons = _score_entry_timing(last, prev, trend)

    # --- Stage 4: Volatility Filter ---
    volatility_ok, volatility_reasons = _check_volatility(last, df_with_indicators)
    if not volatility_ok:
        return Signal(
            has_signal=False,
            direction="call",
            confidence=0.0,
            reasoning=trend_reasons + momentum_reasons + entry_reasons + volatility_reasons,
            indicators=indicator_snapshot,
        )

    # --- Stage 5: Confidence Scoring ---
    base = 0.65
    confidence = _compute_confidence(base, [entry_score])

    direction = "call" if trend == "up" else "put"
    all_reasons = trend_reasons + momentum_reasons + entry_reasons

    if confidence < MIN_CONFIDENCE:
        return Signal(
            has_signal=False,
            direction=direction,
            confidence=0.0,
            reasoning=all_reasons + [f"Confluence below minimum confidence ({confidence:.0%} < {MIN_CONFIDENCE:.0%})"],
            indicators=indicator_snapshot,
        )

    # Clamp to [MIN_CONFIDENCE, 0.95]
    confidence = max(MIN_CONFIDENCE, min(0.95, confidence))

    # Prepend summary
    summary = (
        f"{'Bullish' if direction == 'call' else 'Bearish'} "
        f"trend confluence — {confidence:.0%} confidence"
    )
    all_reasons.insert(0, summary)

    return Signal(
        has_signal=True,
        direction=direction,
        confidence=round(confidence, 2),
        reasoning=all_reasons[:5],
        indicators=indicator_snapshot,
    )


# ---------------------------------------------------------------------------
# Stage 1: Trend Detection
# ---------------------------------------------------------------------------

def _detect_trend(last: pd.Series, prev: pd.Series) -> tuple[str | None, list[str]]:
    """Detect trend direction using EMA cross dead zone + MACD confirmation.

    Returns:
        (direction, reasoning) where direction is 'up', 'down', or None.
    """
    ema_cross = _safe(last, "ema_cross")
    macd_hist = _safe(last, "macd_hist")
    reasoning: list[str] = []

    if np.isnan(ema_cross):
        return None, ["EMA cross data unavailable"]

    # Dead zone check
    if abs(ema_cross) <= TREND_DEAD_ZONE:
        return None, [
            f"No clear trend — EMA cross within dead zone "
            f"(|{ema_cross:.6f}| <= {TREND_DEAD_ZONE})"
        ]

    # EMA cross indicates direction
    ema_direction = "up" if ema_cross > 0 else "down"

    # Confirm with MACD histogram (directional only — not precise at this candle count)
    if not np.isnan(macd_hist):
        macd_direction = "up" if macd_hist > 0 else "down"
        if macd_direction != ema_direction:
            return None, [
                f"EMA and MACD disagree — EMA cross {'above' if ema_direction == 'up' else 'below'} dead zone "
                f"but MACD histogram {'positive' if macd_direction == 'up' else 'negative'}"
            ]
        reasoning.append(
            f"{'Uptrend' if ema_direction == 'up' else 'Downtrend'} "
            f"(EMA 10 {'>' if ema_direction == 'up' else '<'} EMA 30, MACD confirmed)"
        )
    else:
        reasoning.append(
            f"{'Uptrend' if ema_direction == 'up' else 'Downtrend'} "
            f"(EMA cross {ema_cross:.6f}, MACD unavailable)"
        )

    return ema_direction, reasoning


# ---------------------------------------------------------------------------
# Stage 2: Momentum Gate
# ---------------------------------------------------------------------------

def _check_momentum(
    last: pd.Series, prev: pd.Series, trend: str
) -> tuple[bool, list[str]]:
    """Verify MACD histogram and ROC agree with trend direction.

    Both must agree. Either disagreeing = no signal.
    """
    reasoning: list[str] = []

    macd_hist = _safe(last, "macd_hist")
    roc = _safe(last, "roc_5")

    # MACD histogram direction
    if not np.isnan(macd_hist):
        macd_agrees = (macd_hist > 0) == (trend == "up")
        if not macd_agrees:
            return False, [
                f"Momentum disagrees — MACD histogram {'positive' if macd_hist > 0 else 'negative'} "
                f"in {'downtrend' if trend == 'down' else 'uptrend'}"
            ]
        reasoning.append(
            f"MACD momentum {'confirmed' if macd_agrees else 'pending'} "
            f"(histogram {macd_hist:.6f})"
        )

    # ROC direction
    if not np.isnan(roc):
        roc_agrees = (roc > 0) == (trend == "up")
        if not roc_agrees:
            return False, [
                f"Momentum disagrees — ROC {roc:.4%} "
                f"{'rising' if roc > 0 else 'falling'} in "
                f"{'downtrend' if trend == 'down' else 'uptrend'}"
            ]
        reasoning.append(f"ROC momentum confirmed ({roc:.4%} over 5 bars)")

    # If both are NaN, we can't reject on momentum — let it pass
    return True, reasoning


# ---------------------------------------------------------------------------
# Stage 3: Entry Timing
# ---------------------------------------------------------------------------

def _score_entry_timing(
    last: pd.Series, prev: pd.Series, trend: str
) -> tuple[float, list[str]]:
    """Score entry timing bonuses from RSI, Stochastic, and Bollinger.

    Returns (bonus_score, reasoning). Bonus ranges from 0.0 to 0.20.
    """
    bonus = 0.0
    reasoning: list[str] = []

    # --- RSI entry zone ---
    rsi = _safe(last, "rsi")
    if not np.isnan(rsi):
        if trend == "up" and RSI_ENTRY_LOW <= rsi <= RSI_ENTRY_HIGH:
            bonus += 0.10
            reasoning.append(
                f"RSI dip buy — RSI {rsi:.0f} in entry zone "
                f"({RSI_ENTRY_LOW:.0f}-{RSI_ENTRY_HIGH:.0f}) within uptrend"
            )
        elif trend == "down" and RSI_ENTRY_LOW_DOWN <= rsi <= RSI_ENTRY_HIGH_DOWN:
            bonus += 0.10
            reasoning.append(
                f"RSI sell zone — RSI {rsi:.0f} in entry zone "
                f"({RSI_ENTRY_LOW_DOWN:.0f}-{RSI_ENTRY_HIGH_DOWN:.0f}) within downtrend"
            )
        else:
            reasoning.append(f"RSI {rsi:.0f} — outside entry timing zone")

    # --- Stochastic crossover in trend direction ---
    stoch_k = _safe(last, "stoch_k")
    stoch_d = _safe(last, "stoch_d")
    prev_stoch_k = _safe(prev, "stoch_k")
    prev_stoch_d = _safe(prev, "stoch_d")
    if not any(np.isnan(x) for x in [stoch_k, stoch_d, prev_stoch_k, prev_stoch_d]):
        bullish_cross = stoch_k > stoch_d and prev_stoch_k <= prev_stoch_d
        bearish_cross = stoch_k < stoch_d and prev_stoch_k >= prev_stoch_d

        if (trend == "up" and bullish_cross) or (trend == "down" and bearish_cross):
            bonus += 0.05
            reasoning.append(
                f"Stochastic {'bullish' if trend == 'up' else 'bearish'} crossover "
                f"confirmed (K={stoch_k:.0f}, D={stoch_d:.0f})"
            )
        else:
            reasoning.append(
                f"Stochastic K={stoch_k:.0f} — no crossover confirmation"
            )

    # --- Bollinger Band position in trend direction ---
    bb_pct = _safe(last, "bb_pct")
    if not np.isnan(bb_pct):
        if trend == "up" and bb_pct < 0.3:
            bonus += 0.05
            reasoning.append(
                f"Price near lower Bollinger band ({bb_pct:.2f}) — bounce zone in uptrend"
            )
        elif trend == "down" and bb_pct > 0.7:
            bonus += 0.05
            reasoning.append(
                f"Price near upper Bollinger band ({bb_pct:.2f}) — pullback zone in downtrend"
            )
        else:
            reasoning.append(f"Bollinger %b {bb_pct:.2f} — not at trend edge")

    return bonus, reasoning


# ---------------------------------------------------------------------------
# Stage 4: Volatility Filter
# ---------------------------------------------------------------------------

def _check_volatility(
    last: pd.Series, df: pd.DataFrame
) -> tuple[bool, list[str]]:
    """Reject signals when ATR% spikes above its SMA — extreme volatility.

    Uses the longest feasible SMA window given available candle count.
    """
    atr_pct = _safe(last, "atr_pct")
    if np.isnan(atr_pct):
        # ATR not available — cannot filter, let it pass
        return True, []

    # Compute SMA of ATR% over available window
    window = min(ATR_SMA_WINDOW, len(df))
    if window < 3:
        return True, []

    atr_pct_series = df["atr_pct"].dropna()
    if len(atr_pct_series) < window:
        return True, []

    atr_sma = atr_pct_series.iloc[-window:].mean()
    if np.isnan(atr_sma) or atr_sma == 0:
        return True, []

    if atr_pct > ATR_SPIKE_MULTIPLIER * atr_sma:
        return False, [
            f"ATR spike — volatility too high "
            f"(ATR% {atr_pct:.4f} > {ATR_SPIKE_MULTIPLIER}x SMA {atr_sma:.4f})"
        ]

    return True, []


# ---------------------------------------------------------------------------
# Stage 5: Confidence Scoring
# ---------------------------------------------------------------------------

def _compute_confidence(base: float, bonuses: list[float]) -> float:
    """Sum base + bonuses, clamp to [0.0, 0.95]."""
    total = base + sum(bonuses)
    return max(0.0, min(0.95, total))


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

"""Mean-reversion strategy engine for OTC synthetic pairs (5-min).

OTC pairs exhibit bounded, range-bound behavior ideal for mean-reversion.
This engine fires signals only when MULTIPLE independent conditions agree
on direction (confluence), gated by an ADX trend filter.

Weights:
  - Bollinger Band extreme touch      : 0.25
  - RSI extreme                       : 0.20
  - Z-score deviation from mean       : 0.20
  - Reversal candle pattern           : 0.20
  - Stochastic extreme confirmation   : 0.15
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from apps.manual_trading.models import Signal
from infrastructure.features.indicators.technical import TechnicalIndicators

logger = logging.getLogger(__name__)


class MeanReversionEngine:
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_overbought: float = 75,
        rsi_oversold: float = 25,
        zscore_window: int = 20,
        zscore_threshold: float = 1.8,
        adx_period: int = 14,
        adx_trend_cutoff: float = 25,
        confidence_threshold: float = 0.7,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.zscore_window = zscore_window
        self.zscore_threshold = zscore_threshold
        self.adx_period = adx_period
        self.adx_trend_cutoff = adx_trend_cutoff
        self.confidence_threshold = confidence_threshold

        self._weights = {
            "bollinger": 0.25,
            "rsi": 0.20,
            "zscore": 0.20,
            "candle_pattern": 0.20,
            "stochastic": 0.15,
        }

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Augment a OHLCV DataFrame with all indicators needed by this engine.

        Delegates Bollinger, RSI, and Stochastic to TechnicalIndicators,
        then adds Z-score and ADX inline (pandas-only, no extra deps).

        Expected columns: open, high, low, close (sorted ascending).
        """
        ti = TechnicalIndicators()
        out = ti.compute(df)

        out["zscore"] = self._zscore(out["close"], self.zscore_window)

        adx_df = self._adx(out["high"], out["low"], out["close"], self.adx_period)
        out = out.join(adx_df)

        return out

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Generate a mean-reversion signal from raw OHLCV data.

        Returns a standard Signal model compatible with the rest of the
        manual_trading pipeline.
        """
        df = self.compute_indicators(df)
        last = df.iloc[-1]
        reasons: list[str] = []

        # --- Trend filter: gate everything ---
        adx_val = last.get("adx", 0)
        if pd.notna(adx_val) and adx_val >= self.adx_trend_cutoff:
            return Signal(
                has_signal=False,
                direction="call",
                confidence=0.0,
                reasoning=[
                    f"ADX {adx_val:.1f} >= {self.adx_trend_cutoff} "
                    f"trending, skip mean-reversion"
                ],
                indicators=_snapshot(last),
            )

        up_score = 0.0
        down_score = 0.0

        # --- Bollinger Bands ---
        bb_lower = last.get("bb_lower")
        bb_upper = last.get("bb_upper")
        close = last["close"]
        if pd.notna(bb_lower) and close <= bb_lower:
            up_score += self._weights["bollinger"]
            reasons.append("Price at/below lower Bollinger Band")
        elif pd.notna(bb_upper) and close >= bb_upper:
            down_score += self._weights["bollinger"]
            reasons.append("Price at/above upper Bollinger Band")

        # --- RSI ---
        rsi = last.get("rsi")
        if pd.notna(rsi):
            if rsi <= self.rsi_oversold:
                up_score += self._weights["rsi"]
                reasons.append(f"RSI oversold ({rsi:.1f})")
            elif rsi >= self.rsi_overbought:
                down_score += self._weights["rsi"]
                reasons.append(f"RSI overbought ({rsi:.1f})")

        # --- Z-score ---
        z = last.get("zscore")
        if pd.notna(z):
            if z <= -self.zscore_threshold:
                up_score += self._weights["zscore"]
                reasons.append(f"Z-score {z:.2f} (undervalued)")
            elif z >= self.zscore_threshold:
                down_score += self._weights["zscore"]
                reasons.append(f"Z-score {z:.2f} (overvalued)")

        # --- Reversal candle ---
        candle_dir = self._detect_reversal_candle(df)
        if candle_dir == "up":
            up_score += self._weights["candle_pattern"]
            reasons.append("Bullish reversal candle pattern")
        elif candle_dir == "down":
            down_score += self._weights["candle_pattern"]
            reasons.append("Bearish reversal candle pattern")

        # --- Stochastic ---
        stoch_k = last.get("stoch_k")
        stoch_d = last.get("stoch_d")
        if pd.notna(stoch_k) and pd.notna(stoch_d):
            if stoch_k <= 20 and stoch_k > stoch_d:
                up_score += self._weights["stochastic"]
                reasons.append("Stochastic oversold + turning up")
            elif stoch_k >= 80 and stoch_k < stoch_d:
                down_score += self._weights["stochastic"]
                reasons.append("Stochastic overbought + turning down")

        # --- Decide direction ---
        if up_score >= self.confidence_threshold and up_score > down_score:
            return Signal(
                has_signal=True,
                direction="call",
                confidence=round(up_score, 2),
                reasoning=reasons,
                indicators=_snapshot(last),
            )
        if down_score >= self.confidence_threshold and down_score > up_score:
            return Signal(
                has_signal=True,
                direction="put",
                confidence=round(down_score, 2),
                reasoning=reasons,
                indicators=_snapshot(last),
            )

        return Signal(
            has_signal=False,
            direction="call",
            confidence=round(max(up_score, down_score), 2),
            reasoning=reasons or ["No confluence met threshold"],
            indicators=_snapshot(last),
        )

    # ------------------------------------------------------------------
    # Reversal candle pattern detection
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_reversal_candle(df: pd.DataFrame) -> str:
        """Return 'up', 'down', or 'none' based on the last two candles."""
        if len(df) < 2:
            return "none"
        last = df.iloc[-1]
        prev = df.iloc[-2]

        body = abs(last["close"] - last["open"])
        candle_range = last["high"] - last["low"]
        if candle_range == 0:
            return "none"

        upper_wick = last["high"] - max(last["close"], last["open"])
        lower_wick = min(last["close"], last["open"]) - last["low"]

        # Bullish pin bar: long lower wick, small body near top
        if lower_wick > body * 2 and lower_wick > candle_range * 0.5:
            return "up"

        # Bearish pin bar: long upper wick, small body near bottom
        if upper_wick > body * 2 and upper_wick > candle_range * 0.5:
            return "down"

        # Bullish engulfing
        if (
            prev["close"] < prev["open"]
            and last["close"] > last["open"]
            and last["close"] > prev["open"]
            and last["open"] < prev["close"]
        ):
            return "up"

        # Bearish engulfing
        if (
            prev["close"] > prev["open"]
            and last["close"] < last["open"]
            and last["close"] < prev["open"]
            and last["open"] > prev["close"]
        ):
            return "down"

        return "none"

    # ------------------------------------------------------------------
    # Indicator computations (pandas-only)
    # ------------------------------------------------------------------
    @staticmethod
    def _zscore(close: pd.Series, window: int) -> pd.Series:
        roll_mean = close.rolling(window).mean()
        roll_std = close.rolling(window).std()
        return (close - roll_mean) / roll_std.replace(0, np.nan)

    @staticmethod
    def _adx(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int,
    ) -> pd.DataFrame:
        """Compute ADX, +DI, -DI using Wilder's smoothing."""
        prev_high = high.shift(1)
        prev_low = low.shift(1)
        prev_close = close.shift(1)

        # True Range
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Directional movements
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm = pd.Series(
            np.where(
                (up_move > down_move) & (up_move > 0),
                up_move,
                0.0,
            ),
            index=high.index,
        )
        minus_dm = pd.Series(
            np.where(
                (down_move > up_move) & (down_move > 0),
                down_move,
                0.0,
            ),
            index=high.index,
        )

        # Wilder's smoothing (EMA with alpha=1/period)
        alpha = 1.0 / period
        tr_smooth = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        # +DI / -DI
        tr_div = tr_smooth.replace(0, np.nan)
        plus_di = 100.0 * plus_dm_smooth / tr_div
        minus_di = 100.0 * minus_dm_smooth / tr_div

        # DX then ADX
        di_sum = plus_di + minus_di
        dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
        adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        return pd.DataFrame(
            {"adx": adx, "plus_di": plus_di, "minus_di": minus_di, "tr": tr_smooth}
        )


def _snapshot(row: pd.Series) -> dict:
    """Extract a clean indicator snapshot from the last row, dropping NaN."""
    snap = {}
    for col in [
        "rsi",
        "bb_upper",
        "bb_lower",
        "bb_pct",
        "stoch_k",
        "stoch_d",
        "zscore",
        "adx",
        "plus_di",
        "minus_di",
    ]:
        val = row.get(col)
        if val is not None and pd.notna(val):
            snap[col] = round(float(val), 4)
    return snap

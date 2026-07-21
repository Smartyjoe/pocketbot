"""Trading constants — supported pairs and timeframes."""
from __future__ import annotations

POPULAR_PAIRS: list[str] = [
    "EURUSD_otc",
    "GBPUSD_otc",
    "USDJPY_otc",
    "AUDUSD_otc",
    "USDCAD_otc",
    "EURGBP_otc",
    "EURJPY_otc",
    "GBPJPY_otc",
    "BTCUSD_otc",
    "ETHUSD_otc",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
]

ASSET_DISPLAY_NAMES: dict[str, str] = {
    "EURUSD_otc": "EUR/USD (OTC)",
    "GBPUSD_otc": "GBP/USD (OTC)",
    "USDJPY_otc": "USD/JPY (OTC)",
    "AUDUSD_otc": "AUD/USD (OTC)",
    "USDCAD_otc": "USD/CAD (OTC)",
    "EURGBP_otc": "EUR/GBP (OTC)",
    "EURJPY_otc": "EUR/JPY (OTC)",
    "GBPJPY_otc": "GBP/JPY (OTC)",
    "BTCUSD_otc": "BTC/USD (OTC)",
    "ETHUSD_otc": "ETH/USD (OTC)",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
}

# Candle timeframes available for subscription
CANDLE_TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}

# Base number of candles to fetch for indicator computation.
# MACD(12,26,9) needs ~26 candles for stable slow EMA; with fewer,
# indicators degrade gracefully (NaN → skipped in signal scoring).
CANDLES_NEEDED = 30

# Minimum candles required per timeframe for signal generation.
# Higher timeframes have fewer candles available from the server,
# so we relax the requirement proportionally.
MIN_CANDLES_BY_TIMEFRAME: dict[int, int] = {
    60: 16,   # 1m — server returns plenty
    300: 10,  # 5m — server returns ~10-15 with scaled offset
    900: 8,   # 15m — server returns very few; indicators degrade gracefully
}


def min_candles_for_timeframe(timeframe_sec: int) -> int:
    """Return the minimum candles needed for a given timeframe."""
    return MIN_CANDLES_BY_TIMEFRAME.get(timeframe_sec, 10)


# --- Trend-Following Confluence Strategy Constants ---

# Trend detection: EMA cross must exceed this dead zone to count as a trend.
# Value is relative to ema_cross magnitude (which is (ema_fast - ema_slow) / close).
# Instrument from real data before deploying live.
TREND_DEAD_ZONE: float = 0.001

# Confidence gate: signals below this are rejected as no-signal.
MIN_CONFIDENCE: float = 0.70

# RSI entry timing zones (uptrend = buy the dip, downtrend = sell the rip).
RSI_ENTRY_LOW: float = 40.0
RSI_ENTRY_HIGH: float = 50.0
RSI_ENTRY_LOW_DOWN: float = 50.0
RSI_ENTRY_HIGH_DOWN: float = 60.0

# ATR volatility filter: reject signals when ATR% > multiplier * SMA(ATR%, window).
ATR_SPIKE_MULTIPLIER: float = 2.0
ATR_SMA_WINDOW: int = 10  # longest feasible with 16-30 candles

# Cooldown: minimum bars between signals for the same pair (handler-layer).
COOLDOWN_BARS: int = 3

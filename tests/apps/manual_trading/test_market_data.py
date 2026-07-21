"""Tests for market data collector."""
import json

import pytest

from apps.manual_trading.market_data import MarketDataCollector


@pytest.fixture
def collector() -> MarketDataCollector:
    return MarketDataCollector()


class TestMarketDataCollector:
    @pytest.mark.asyncio
    async def test_initial_state_empty(self, collector: MarketDataCollector) -> None:
        df = await collector.get_candles("EURUSD_otc")
        assert df is None

    @pytest.mark.asyncio
    async def test_latest_price_initially_none(self, collector: MarketDataCollector) -> None:
        price = await collector.get_latest_price("EURUSD_otc")
        assert price is None

    @pytest.mark.asyncio
    async def test_parse_update_stream(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        msg = '42["updateStream",{"asset":"EURUSD_otc","price":1.0852}]'
        await handler(msg)
        price = await collector.get_latest_price("EURUSD_otc")
        assert price is not None
        assert float(price) == 1.0852

    @pytest.mark.asyncio
    async def test_parse_price_event(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        msg = '42["price",{"asset":"GBPUSD_otc","price":1.2650}]'
        await handler(msg)
        price = await collector.get_latest_price("GBPUSD_otc")
        assert price is not None
        assert float(price) == 1.2650

    @pytest.mark.asyncio
    async def test_parse_candle_history_dict(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        candle_data = {
            "asset": "EURUSD_otc",
            "candles": [
                {"t": 1700000000, "o": 1.085, "h": 1.086, "l": 1.084, "c": 1.0855, "v": 1000},
                {"t": 1700000060, "o": 1.0855, "h": 1.087, "l": 1.085, "c": 1.0865, "v": 1200},
            ],
        }
        msg = f'42["loadHistoryPeriod",{json.dumps(candle_data)}]'
        await handler(msg)
        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        assert len(df) == 2
        assert "close" in df.columns

    @pytest.mark.asyncio
    async def test_parse_candle_history_list(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        candle_data = [
            "EURUSD_otc",
            [
                {"t": 1700000000, "o": 1.085, "h": 1.086, "l": 1.084, "c": 1.0855, "v": 1000},
            ],
        ]
        msg = f'42["loadHistoryPeriod",{json.dumps(candle_data)}]'
        await handler(msg)
        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_ignores_engineio_ping(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        await handler("2")  # EIO ping
        price = await collector.get_latest_price("EURUSD_otc")
        assert price is None

    @pytest.mark.asyncio
    async def test_ignores_engineio_pong(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        await handler("3")  # EIO pong
        price = await collector.get_latest_price("EURUSD_otc")
        assert price is None

    @pytest.mark.asyncio
    async def test_ignores_bytes_messages(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        await handler(b"some binary data")
        price = await collector.get_latest_price("EURUSD_otc")
        assert price is None

    @pytest.mark.asyncio
    async def test_candles_sorted_by_timestamp(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        candle_data = {
            "asset": "EURUSD_otc",
            "candles": [
                {"t": 1700000060, "o": 1.0855, "h": 1.087, "l": 1.085, "c": 1.0865, "v": 1200},
                {"t": 1700000000, "o": 1.085, "h": 1.086, "l": 1.084, "c": 1.0855, "v": 1000},
            ],
        }
        msg = f'42["loadHistoryPeriod",{json.dumps(candle_data)}]'
        await handler(msg)
        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        # Should be sorted by timestamp
        assert df.iloc[0]["close"] == 1.0855
        assert df.iloc[1]["close"] == 1.0865

    @pytest.mark.asyncio
    async def test_candles_capped_at_200(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        # Send 250 candles
        candles = [
            {"t": 1700000000 + i * 60, "o": 1.085, "h": 1.086, "l": 1.084, "c": 1.0855, "v": 1000}
            for i in range(250)
        ]
        candle_data = {"asset": "EURUSD_otc", "candles": candles}
        msg = f'42["loadHistoryPeriod",{json.dumps(candle_data)}]'
        await handler(msg)
        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        assert len(df) == 200

    @pytest.mark.asyncio
    async def test_get_all_prices(self, collector: MarketDataCollector) -> None:
        handler = collector.make_message_handler()
        await handler('42["price",{"asset":"EURUSD_otc","price":1.0852}]')
        await handler('42["price",{"asset":"GBPUSD_otc","price":1.2650}]')
        prices = collector.get_all_prices()
        assert "EURUSD_otc" in prices
        assert "GBPUSD_otc" in prices

    @pytest.mark.asyncio
    async def test_candle_builder_builds_ohlc_from_ticks(
        self, collector: MarketDataCollector
    ) -> None:
        """After request_candles, live ticks should be aggregated into candles."""
        import time as _time

        broker = _mock_broker(connected=True)
        await collector.request_candles(broker, "EURUSD_otc", timeframe_sec=60)

        builder = collector._builders["EURUSD_otc"]
        base = _time.time()
        # All ticks within the same 60-second window
        builder.add_tick(1.080, base)
        builder.add_tick(1.085, base + 10)
        builder.add_tick(1.079, base + 20)
        builder.add_tick(1.083, base + 30)

        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["open"] == 1.080
        assert df.iloc[0]["high"] == 1.085
        assert df.iloc[0]["low"] == 1.079
        assert df.iloc[0]["close"] == 1.083

    @pytest.mark.asyncio
    async def test_candle_builder_new_window_after_timeframe(
        self, collector: MarketDataCollector
    ) -> None:
        """Ticks spanning two time windows produce two candles."""
        import time as _time

        broker = _mock_broker(connected=True)
        await collector.request_candles(broker, "EURUSD_otc", timeframe_sec=60)

        builder = collector._builders["EURUSD_otc"]
        base = _time.time()

        # First candle window: ticks within [base, base+60)
        builder.add_tick(1.080, base)
        builder.add_tick(1.085, base + 10)

        # Second candle window: tick at base+61 triggers new window (>60s gap)
        builder.add_tick(1.082, base + 61)
        builder.add_tick(1.084, base + 70)

        df = await collector.get_candles("EURUSD_otc")
        assert df is not None
        assert len(df) == 2
        assert df.iloc[0]["close"] == 1.085
        assert df.iloc[1]["open"] == 1.082

    @pytest.mark.asyncio
    async def test_request_candles_no_broker_crash(self, collector: MarketDataCollector) -> None:
        """request_candles with disconnected broker does not crash."""
        broker = _mock_broker(connected=False)
        await collector.request_candles(broker, "EURUSD_otc", timeframe_sec=60)
        # No builder created, no crash
        assert "EURUSD_otc" not in collector._builders

    @pytest.mark.asyncio
    async def test_stream_tick_feeds_builder(self, collector: MarketDataCollector) -> None:
        """updateStream ticks feed into the candle builder when subscribed."""
        import time as _time

        broker = _mock_broker(connected=True)
        await collector.request_candles(broker, "EURUSD_otc", timeframe_sec=60)

        builder = collector._builders["EURUSD_otc"]
        base = _time.time()
        builder._current_start = base - 100

        handler = collector.make_message_handler()
        # These ticks should update both latest_price AND the builder
        await handler('42["updateStream",{"asset":"EURUSD_otc","price":1.080}]')
        await handler('42["updateStream",{"asset":"EURUSD_otc","price":1.085}]')

        price = await collector.get_latest_price("EURUSD_otc")
        assert price is not None
        assert float(price) == 1.085
        assert len(builder.candles) == 0  # not finalised yet
        assert builder._current_close == 1.085


def _mock_broker(connected: bool = True):
    """Create a minimal broker mock for request_candles tests."""
    from unittest.mock import AsyncMock

    broker = AsyncMock()
    broker.is_connected = AsyncMock(return_value=connected)
    return broker

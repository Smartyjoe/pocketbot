"""Pocket Option broker using raw Socket.IO over WebSocket.

Protocol notes (from reverse-engineering the Pocket Option client):
- Engine.IO v4 transport over WebSocket
- Socket.IO events prefixed with ``42``
- Binary events prefixed with ``451-`` (Socket.IO BINARY_EVENT type 5)
  → must NOT be ACK'd; just parse the JSON payload
- Balance data arrives as **bytes** containing JSON with a ``balance`` key
- Server event names: ``successauth``, ``successupdateBalance``,
  ``successopenOrder``, ``successcloseOrder``, ``updateStream``,
  ``loadHistoryPeriod``
- Client ping: ``42["ps"]`` every 20 s
- EIO ping ``2`` → pong ``3`` handled automatically by the server
"""
import asyncio
import json
import random
import ssl
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

import structlog
from websockets.legacy.client import connect, WebSocketClientProtocol

from config.settings import BrokerConfig
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money

logger = structlog.get_logger()


def _random_index() -> int:
    """Random u64 index matching the Rust ``get_index()`` helper."""
    return random.randint(0, 2**64 - 1)

DEMO_URL = "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket"
LIVE_URLS: dict[str, str] = {
    "eu": "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket",
    "us": "wss://api-us-north.po.market/socket.io/?EIO=4&transport=websocket",
    "hk": "wss://api-hk.po.market/socket.io/?EIO=4&transport=websocket",
}

DEMO_BALANCE = Decimal("10000.00")
_RECV_TIMEOUT = 30  # seconds


def _build_auth_ssid(
    session: str, is_demo: bool, uid: int, platform: int = 1
) -> str:
    """Build the Socket.IO auth message string."""
    demo_val = 1 if is_demo else 0
    payload = {
        "session": session,
        "isDemo": demo_val,
        "uid": uid,
        "platform": platform,
        "isFastHistory": True,
    }
    return f'42["auth",{json.dumps(payload)}]'


class PocketOptionBroker:
    """WebSocket broker with a single recv loop feeding an internal queue.

    All public methods that need to read messages from the socket consume
    from ``_msg_queue`` instead of calling ``ws.recv()`` directly, which
    eliminates the ``cannot call recv while another coroutine is already
    waiting`` race condition.
    """

    def __init__(self, config: BrokerConfig) -> None:
        self._raw_ssid = config.ssid
        self._is_demo = True
        self._session = ""
        self._uid = 0
        self._platform = 1
        self._region = getattr(config, "region", "eu")
        self._connection_timeout = config.connection_timeout
        self._reconnect_delay = config.reconnect_delay
        self._max_subscriptions = config.max_subscriptions

        self._ws: Optional[WebSocketClientProtocol] = None
        self._connected = False
        self._authenticated = False
        self._balance: Optional[Decimal] = None
        self._last_prices: dict[str, Decimal] = {}
        self._payouts: dict[str, float] = {}
        self._message_handlers: list[Callable] = []

        self._msg_queue: asyncio.Queue[str | bytes] = asyncio.Queue()
        self._recv_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

        # Server time cache (from 42["time"] event)
        self._server_time: Optional[int] = None

        # Diagnostic: track changeSymbol sends for debugging
        self._last_change_symbol_at: float = 0.0
        self._msgs_since_change: int = 0

        # Socket.IO binary event reassembly
        # When we see {"_placeholder": true, "num": N}, the N-th argument
        # is binary data arriving in the next bytes message.
        self._pending_binary_event: Optional[list] = None
        self._pending_binary_count: int = 0
        self._pending_binary_args: list = []

        self._parse_ssid(config.ssid)

    # ------------------------------------------------------------------
    # SSID parsing
    # ------------------------------------------------------------------

    def _parse_ssid(self, ssid: str) -> None:
        try:
            if ssid.startswith('42["auth",'):
                data = json.loads(ssid[2:])
                payload = data[1]
                # Support both old format ("session") and new format ("sessionToken")
                self._session = payload.get("sessionToken") or payload.get("session", "")
                self._is_demo = bool(payload.get("isDemo", 1))
                self._uid = int(payload.get("uid", 0))
                self._platform = int(payload.get("platform", 1))
            else:
                self._session = ssid
        except (json.JSONDecodeError, IndexError, KeyError):
            self._session = ssid

    def _get_url(self) -> str:
        if self._is_demo:
            return DEMO_URL
        return LIVE_URLS.get(self._region, LIVE_URLS["eu"])

    # ------------------------------------------------------------------
    # Public callback registration
    # ------------------------------------------------------------------

    def on_message(self, handler: Callable) -> None:
        self._message_handlers.append(handler)

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        url = self._get_url()
        logger.info("broker_connecting", is_demo=self._is_demo)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        self._ws = await asyncio.wait_for(
            connect(
                url,
                ssl=ssl_ctx,
                extra_headers={
                    "Origin": "https://pocketoption.com",
                    "Cache-Control": "no-cache",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36",
                },
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10,
            ),
            timeout=self._connection_timeout,
        )

        self._msg_queue = asyncio.Queue()

        try:
            # --- Engine.IO handshake ---
            eio_msg = await asyncio.wait_for(self._ws.recv(), timeout=10)
            logger.debug("eio_handshake", msg=str(eio_msg)[:80])

            await self._ws.send("40")
            sio_msg = await asyncio.wait_for(self._ws.recv(), timeout=10)
            logger.debug("sio_connect", msg=str(sio_msg)[:80])

            # --- Socket.IO auth ---
            # Send the raw SSID as-is — the server validates all fields
            # exactly, so we must not rebuild or modify the payload.
            await self._ws.send(self._raw_ssid)
            logger.debug("auth_sent")

            self._connected = True

            # Start the single reader loop *now* so all subsequent
            # _consume_one calls read from the same queue.
            self._recv_task = asyncio.create_task(self._recv_loop())

            # Consume initial server push (updateAssets binary, etc.)
            await self._drain_until_idle(timeout=5)

            # Request balance
            await self._ws.send('42["getBalance"]')
            await self._wait_for_balance(timeout=10)

            self._authenticated = True

            # Request server time — used in loadHistoryPeriod
            await self._ws.send('42["time"]')
            await self._consume_until(
                predicate=lambda: self._server_time is not None,
                timeout=5,
            )
            if self._server_time is not None:
                logger.info("server_time_synced time=%d", self._server_time)
            else:
                logger.warning("server_time_sync_failed_using_local")

            if self._balance is None:
                self._balance = DEMO_BALANCE
                logger.info(
                    "broker_connected",
                    balance=str(self._balance),
                    note="using_default_demo_balance",
                )
            else:
                logger.info("broker_connected", balance=str(self._balance))

            self._ping_task = asyncio.create_task(self._ping_loop())

        except Exception:
            logger.exception("broker_connect_failed")
            self._connected = False
            if self._recv_task and not self._recv_task.done():
                self._recv_task.cancel()
            if self._ws:
                await self._ws.close()
                self._ws = None
            raise

    async def disconnect(self) -> None:
        self._connected = False
        self._authenticated = False

        for task in (self._recv_task, self._ping_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Unblock any consumers waiting on the queue
        await self._msg_queue.put(None)  # type: ignore[arg-type]
        logger.info("broker_disconnected")

    async def is_connected(self) -> bool:
        if not self._connected or not self._ws:
            return False
        return not self._ws.closed

    # ------------------------------------------------------------------
    # Single recv loop — the only coroutine that calls ws.recv()
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        """Read from the websocket and push every message into ``_msg_queue``."""
        try:
            while self._connected and self._ws:
                msg = await asyncio.wait_for(
                    self._ws.recv(), timeout=_RECV_TIMEOUT
                )
                await self._msg_queue.put(msg)

                # --- DIAGNOSTIC: log EVERY message after changeSymbol ---
                if self._last_change_symbol_at > 0:
                    self._msgs_since_change += 1
                    msg_type = "bytes" if isinstance(msg, bytes) else "str"
                    preview = ""
                    if isinstance(msg, str):
                        preview = msg[:200]
                    elif isinstance(msg, bytes):
                        try:
                            preview = msg.decode("utf-8", errors="replace")[:200]
                        except Exception:
                            preview = "<binary>"
                    logger.warning(
                        "PO_MSG_after_changeSymbol msg_num=%d type=%s preview=%s",
                        self._msgs_since_change, msg_type, preview,
                    )

                # Process inline (balance, price, etc.)
                await self._process_message(msg)

                # Forward to external handlers
                for handler in self._message_handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(msg)
                        else:
                            handler(msg)
                    except Exception:
                        pass
        except asyncio.TimeoutError:
            logger.warning("recv_loop_timeout")
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning("recv_loop_error", exc_info=True)
        finally:
            self._connected = False

    # ------------------------------------------------------------------
    # Queue helpers
    # ------------------------------------------------------------------

    async def _drain_until_idle(self, timeout: float = 5) -> None:
        """Consume all queued messages for *timeout* seconds (handshake)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                msg = await asyncio.wait_for(
                    self._msg_queue.get(), timeout=min(remaining, 0.5)
                )
                if msg is None:
                    break
                await self._process_message(msg)
            except asyncio.TimeoutError:
                break

    async def _wait_for_balance(self, timeout: float = 10) -> None:
        """Consume messages until balance is known or *timeout* elapses."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline and self._balance is None:
            try:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                msg = await asyncio.wait_for(
                    self._msg_queue.get(), timeout=min(remaining, 0.5)
                )
                if msg is None:
                    break
                await self._process_message(msg)
            except asyncio.TimeoutError:
                continue

    async def _consume_until(
        self,
        predicate: Callable[[], bool],
        timeout: float,
    ) -> None:
        """Consume messages from the queue until *predicate()* returns True."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if predicate():
                return
            try:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                msg = await asyncio.wait_for(
                    self._msg_queue.get(), timeout=min(remaining, 0.5)
                )
                if msg is None:
                    break
                await self._process_message(msg)
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------
    # Binary event reassembly
    # ------------------------------------------------------------------

    async def _reassemble_binary_event(self) -> None:
        """Replace binary placeholders in a pending event and process it."""
        event = self._pending_binary_event
        args = self._pending_binary_args
        self._pending_binary_event = None
        self._pending_binary_count = 0
        self._pending_binary_args = []

        if not event:
            return

        event_name = event[0]

        # Replace each {"_placeholder": true, "num": N} with the N-th binary arg
        reassembled = [event_name]
        for i in range(1, len(event)):
            item = event[i]
            if isinstance(item, dict) and item.get("_placeholder"):
                num = item.get("num", 0)
                if num < len(args):
                    binary_data = args[num]
                    # Try to decode as JSON first (most PO events are JSON-in-binary)
                    try:
                        decoded = json.loads(binary_data.decode("utf-8"))
                        reassembled.append(decoded)
                        logger.warning(
                            "binary_reassembled event=%s arg_num=%d decoded=json len=%d",
                            event_name, num, len(binary_data),
                        )
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Keep raw bytes if not JSON
                        reassembled.append(binary_data)
                        logger.warning(
                            "binary_reassembled event=%s arg_num=%d raw_bytes len=%d",
                            event_name, num, len(binary_data),
                        )
                else:
                    reassembled.append(item)
                    logger.warning(
                        "binary_placeholder_miss event=%s arg_num=%d available=%d",
                        event_name, num, len(args),
                    )
            else:
                reassembled.append(item)

        # Process the fully reassembled event
        await self._handle_sio_event(reassembled)

        # Forward reassembled event to external handlers as a synthetic
        # Socket.IO EVENT string so they see the actual data (not the
        # raw placeholder message).
        sio_msg = f'42{json.dumps(reassembled)}'
        for handler in self._message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(sio_msg)
                else:
                    handler(sio_msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Message processing
    # ------------------------------------------------------------------

    async def _process_message(self, msg: str | bytes) -> None:  # noqa: C901
        """Process a single incoming message (text or bytes).

        Protocol rules:
        - ``2`` → Engine.IO ping → reply ``3`` (pong)
        - ``3`` → Engine.IO pong → ignore
        - Bytes → decode as JSON; if contains ``balance`` key → update balance
        - ``451-[...`` → Socket.IO BINARY_EVENT → parse JSON, do NOT ACK
        - ``42[...`` → Socket.IO EVENT → parse JSON, dispatch by event name
        """
        # ---- Engine.IO control frames ----
        if msg == "2":
            # Engine.IO ping — respond with pong
            if self._ws and not self._ws.closed:
                await self._ws.send("3")
            return

        if msg == "3":
            return  # Engine.IO pong — nothing to do

        # ---- Bytes messages (binary Socket.IO data, balance data, etc.) ----
        if isinstance(msg, bytes):
            # Socket.IO binary event reassembly: if we have a pending event
            # with placeholder(s), this bytes message is the binary argument.
            if self._pending_binary_event is not None:
                self._pending_binary_args.append(msg)
                logger.warning(
                    "binary_arg_received pending=%d got=%d total_needed=%d",
                    len(self._pending_binary_args) - 1,
                    len(self._pending_binary_args),
                    self._pending_binary_count,
                )
                if len(self._pending_binary_args) >= self._pending_binary_count:
                    # All binary args received — reassemble and process
                    await self._reassemble_binary_event()
                return

            # Otherwise, try to parse as JSON (balance data, payout data)
            try:
                decoded = msg.decode("utf-8")
                json_data = json.loads(decoded)
                # Balance data arrives as bytes JSON with a "balance" key
                if isinstance(json_data, dict) and "balance" in json_data:
                    bal = json_data.get("balance", 0)
                    self._balance = Decimal(str(bal))
                    logger.debug("balance_from_bytes", balance=str(self._balance))
                elif isinstance(json_data, list):
                    # Asset payout data arrives as [[5, ...]]
                    self._handle_payout_data(json_data)
            except (json.JSONDecodeError, UnicodeDecodeError, InvalidOperation):
                logger.warning("binary_unparseable len=%d preview=%s", len(msg), msg[:50])
            return

        # ---- String messages below this point ----
        if not isinstance(msg, str):
            return

        # Socket.IO BINARY_EVENT: ``451-[<json>]``
        # This is an event with binary placeholders — parse but do NOT ACK.
        if msg.startswith("451-["):
            try:
                json_part = msg.split("-", 1)[1]  # strip the ``451`` prefix
                data = json.loads(json_part)

                # Check for binary placeholders: {"_placeholder": true, "num": N}
                if isinstance(data, list) and len(data) > 1:
                    event_data = data[1] if len(data) > 1 else None
                    if isinstance(event_data, dict) and event_data.get("_placeholder"):
                        # This event has binary args — save for reassembly
                        self._pending_binary_event = data
                        self._pending_binary_count = event_data.get("num", 0) + 1
                        self._pending_binary_args = []
                        logger.warning(
                            "binary_event_pending event_name=%s placeholders=%d",
                            data[0], self._pending_binary_count,
                        )
                        return

                await self._handle_sio_event(data)
            except (json.JSONDecodeError, IndexError):
                pass
            return

        # Socket.IO EVENT: ``42[<json>]``
        if msg.startswith("42"):
            try:
                data = json.loads(msg[2:])
                await self._handle_sio_event(data)
            except (json.JSONDecodeError, IndexError):
                pass
            return

        # Anything else — log at warning level (was debug, too quiet)
        logger.warning("unhandled_msg", msg=msg[:200])

    async def _handle_sio_event(self, data: list) -> None:
        """Dispatch a parsed Socket.IO event."""
        if not data or not isinstance(data, list):
            return

        event_name = data[0]
        event_data = data[1] if len(data) > 1 else None

        logger.warning("sio_event_dispatch name=%s data_preview=%s", event_name, str(event_data)[:150])

        if event_name == "successauth":
            logger.info("auth_success")

        elif event_name in (
            "successupdateBalance",
            "balance",
            "balance_data",
            "balance_updated",
        ):
            self._update_balance(event_data)

        elif event_name == "successopenOrder":
            logger.info("order_opened", data=str(event_data)[:200])

        elif event_name == "successcloseOrder":
            logger.info("order_closed", data=str(event_data)[:200])

        elif event_name == "updateStream":
            self._handle_stream_update(event_data)

        elif event_name == "loadHistoryPeriod":
            logger.debug("candles_received", data=str(event_data)[:200])

        elif event_name == "loadHistoryPeriodFast":
            logger.debug("candles_received_fast", data=str(event_data)[:200])

        elif event_name == "candles":
            logger.warning(
                "candles_event_received data_type=%s data_preview=%s",
                type(event_data).__name__,
                str(event_data)[:300] if event_data is not None else "None",
            )

        elif event_name == "time":
            if isinstance(event_data, (int, float)):
                self._server_time = int(event_data)
                logger.warning("server_time_received time=%d", self._server_time)
            elif isinstance(event_data, list) and len(event_data) > 0:
                # Some servers send [timestamp, ...] as event_data
                ts = event_data[0] if event_data else None
                if isinstance(ts, (int, float)):
                    self._server_time = int(ts)
                    logger.warning("server_time_received time=%d", self._server_time)

        elif event_name == "updateAssets":
            logger.debug("assets_update_received")

        elif event_name == "updateCharts":
            logger.warning(
                "updateCharts_received data_type=%s data_preview=%s",
                type(event_data).__name__,
                str(event_data)[:300] if event_data is not None else "None",
            )

        elif event_name == "price":
            if isinstance(event_data, dict):
                asset = event_data.get("asset", "")
                price = event_data.get("price")
                if asset and price is not None:
                    self._last_prices[asset] = Decimal(str(price))

        elif event_name in ("order_opened", "order_result", "deal"):
            logger.info("order_event", sio_event=event_name, data=str(event_data)[:200])

    def _update_balance(self, event_data: Any) -> None:
        """Extract balance from various event data formats.

        The ``successupdateBalance`` event sends ``0`` as a placeholder;
        the authoritative balance arrives as a **bytes** JSON message.
        Only update from event data when the value is a positive number
        or a dict with a ``balance`` key — never from placeholder ``0``.
        """
        try:
            if isinstance(event_data, dict):
                bal = event_data.get("balance") or event_data.get("amount")
                if bal is not None:
                    self._balance = Decimal(str(bal))
            elif isinstance(event_data, (int, float)) and event_data > 0:
                self._balance = Decimal(str(event_data))
            logger.debug("balance_received", balance=str(self._balance))
        except (InvalidOperation, TypeError, ValueError):
            pass

    def _handle_stream_update(self, event_data: Any) -> None:
        """Handle real-time price stream updates.

        ``updateStream`` payload from the server:
        ``{"asset": "...", "time": <unix>, "data": [[ts,o,c,h,l],...], "history": <bool>}``

        The ``data`` field is an array of candle arrays:
        ``[timestamp, open, close, high, low]`` (note: close before high/low).
        """
        if not isinstance(event_data, dict):
            return

        asset = event_data.get("asset", "")
        if not asset:
            return

        candle_data = event_data.get("data")
        if isinstance(candle_data, list) and candle_data:
            # Extract close price from last candle in the array
            last_candle = candle_data[-1]
            if isinstance(last_candle, list) and len(last_candle) >= 3:
                close = last_candle[2]  # [ts, open, close, high, low]
                try:
                    self._last_prices[asset] = Decimal(str(close))
                except (InvalidOperation, TypeError, ValueError):
                    pass
            return

        # Fallback: direct price field (legacy format)
        price = event_data.get("price") or event_data.get("close")
        if price is not None:
            try:
                self._last_prices[asset] = Decimal(str(price))
            except (InvalidOperation, TypeError, ValueError):
                pass

    def _handle_payout_data(self, data: list) -> None:
        """Parse asset payout data arriving as ``[[5, ...]]``."""
        if not isinstance(data, list):
            return
        for asset_row in data:
            if (
                isinstance(asset_row, list)
                and len(asset_row) > 5
            ):
                symbol = str(asset_row[1]) if len(asset_row) > 1 else ""
                payout = asset_row[5]
                if symbol:
                    self._payouts[symbol] = float(payout)
                    logger.debug(
                        "payout_info", symbol=symbol, payout=payout
                    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_balance(self) -> Money:
        if not self._connected or not self._ws:
            raise ConnectionError("Not connected to broker")

        await self._ws.send('42["getBalance"]')

        await self._consume_until(
            predicate=lambda: self._balance is not None,
            timeout=10,
        )

        if self._balance is not None:
            return Money(amount=str(self._balance))

        self._balance = DEMO_BALANCE
        return Money(amount=str(self._balance))

    def get_payout(self, symbol: str) -> float | None:
        """Return cached payout percentage for a symbol, or None."""
        return self._payouts.get(symbol)

    def get_payouts(self) -> dict[str, float]:
        """Return all cached payout data keyed by symbol."""
        return dict(self._payouts)

    async def place_trade(
        self,
        symbol: Symbol,
        direction: Direction,
        amount: Money,
        duration_seconds: int,
    ) -> str:
        if not self._connected or not self._ws:
            raise ConnectionError("Not connected to broker")

        order_id = (
            f"order_{symbol.code}_{direction.value}_"
            f"{int(datetime.now(timezone.utc).timestamp())}"
        )
        payload = {
            "asset": symbol.code,
            "amount": float(amount.amount),
            "action": direction.value,
            "isDemo": 1 if self._is_demo else 0,
            "requestId": order_id,
            "optionType": 100,
            "time": duration_seconds,
        }
        await self._ws.send(f'42["openOrder",{json.dumps(payload)}]')

        # Wait briefly for order confirmation via _process_message
        await asyncio.sleep(2)

        return order_id

    async def get_current_price(self, symbol: Symbol) -> Decimal:
        if symbol.code in self._last_prices:
            return self._last_prices[symbol.code]

        if self._connected and self._ws:
            import time as _time
            period_minutes = 1
            payload = {
                "asset": symbol.code,
                "period": period_minutes,
                "isDemo": 1 if self._is_demo else 0,
                "platform": self._platform,
                "requestId": f"price_{symbol.code}_{int(_time.time())}",
                "isFastHistory": True,
            }
            msg = f'42["changeSymbol",{json.dumps(payload)}]'
            await self._ws.send(msg)
            self._last_change_symbol_at = _time.time()
            self._msgs_since_change = 0

            await self._consume_until(
                predicate=lambda: symbol.code in self._last_prices,
                timeout=10,
            )

            if symbol.code in self._last_prices:
                return self._last_prices[symbol.code]

        return Decimal("0")

    async def subscribe_candles(
        self,
        symbol: Symbol,
        timeframe_seconds: int,
    ) -> None:
        """Request historical candle data via ``loadHistoryPeriod``.

        Protocol (from BinaryOptionsToolsV2 reverse-engineering):
        Send ``loadHistoryPeriod`` with server time. Server responds with
        candle data in the same event name. For live streaming, use
        ``subscribeSymbol`` + ``changeSymbol`` AFTER historical data is loaded.
        """
        if self._connected and self._ws:
            import time as _time

            # Normalize symbol: lowercase _otc suffix
            asset = symbol.code
            if asset.endswith("_OTC"):
                asset = asset[:-4] + "_otc"

            # Use server time if available, fallback to local time
            now = self._server_time or int(_time.time())

            # loadHistoryPeriod — historical candle backfill
            # Scale offset proportionally to timeframe so we always get
            # enough candles regardless of the interval.
            # For 60s candles: offset=1000 → ~16 candles
            # For 300s candles: offset=15000 → ~50 candles
            # For 900s candles: offset=45000 → ~50 candles
            scaled_offset = max(1000, timeframe_seconds * 50)
            history_payload = {
                "asset": asset,
                "period": timeframe_seconds,
                "time": now,
                "index": _random_index(),
                "offset": scaled_offset,
            }
            msg_hist = f'42["loadHistoryPeriod",{json.dumps(history_payload)}]'
            await self._ws.send(msg_hist)
            logger.warning(
                "loadHistoryPeriod_SENT asset=%s period=%d server_time=%d raw=%s",
                asset, timeframe_seconds, now, msg_hist,
            )

            # Diagnostic: mark when we subscribed
            self._last_change_symbol_at = _time.time()
            self._msgs_since_change = 0

    async def get_available_assets(self) -> list[Symbol]:
        """Return available assets from cached payout data."""
        # Assets are populated during the updateAssets binary push
        return [Symbol(code=s) for s in self._last_prices.keys()]

    # ------------------------------------------------------------------
    # Ping loop — sends ``42["ps"]`` every 20 s
    # ------------------------------------------------------------------

    async def _ping_loop(self) -> None:
        while self._connected and self._ws:
            try:
                await asyncio.sleep(20)
                if self._connected and self._ws and not self._ws.closed:
                    await self._ws.send('42["ps"]')
            except Exception:
                logger.warning("ping_failed")
                break

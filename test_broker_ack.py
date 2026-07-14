"""Debug script: test broker with proper Socket.IO ACK handling."""
import asyncio
import json
import ssl
import time

from websockets.legacy.client import connect


async def test():
    url = "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket"
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    print("Connecting...", flush=True)
    ws = await connect(
        url,
        ssl=ssl_ctx,
        extra_headers={
            "Origin": "https://pocketoption.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        ping_interval=None,
        ping_timeout=None,
    )
    print(f"Connected!", flush=True)

    start = time.time()
    pending_acks: dict[int, asyncio.Event] = {}
    pending_ack_data: dict[int, list] = {}

    async def recv_loop():
        """Properly handle all message types including binary."""
        try:
            while not ws.closed:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                elapsed = time.time() - start
                if isinstance(msg, bytes):
                    print(f"  [{elapsed:.1f}s] RECV BIN: {msg[:100]}...", flush=True)
                    continue

                print(f"  [{elapsed:.1f}s] RECV: {msg[:200]}", flush=True)

                # Engine.IO ping -> respond with pong
                if msg == "2":
                    await ws.send("3")
                    print(f"  [{elapsed:.1f}s] SENT pong", flush=True)
                    continue

                # Engine.IO pong - ignore
                if msg == "3":
                    continue

                # Socket.IO messages
                if msg.startswith("4"):
                    sio_part = msg[1:]  # strip the "4" (EIO message type)

                    # Check for ACK: format is "3<id>-[...]"
                    if sio_part.startswith("3"):
                        # ACK from server
                        ack_str = sio_part[1:]
                        dash_idx = ack_str.find("-")
                        if dash_idx >= 0:
                            ack_id = int(ack_str[:dash_idx])
                            print(f"  [{elapsed:.1f}s] ACK from server id={ack_id}", flush=True)
                            if ack_id in pending_acks:
                                pending_acks[ack_id].set()
                        continue

                    # BINARY_EVENT: type 5 -> "5<id>-[...]"
                    # CONNECT: "0"
                    # EVENT: "2<id>-[...]"  or "2[...]"
                    # ACK (client): "3<id>-[...]"
                    if sio_part.startswith("0"):
                        # CONNECT ack
                        connect_data = sio_part[1:]
                        if connect_data.startswith("{"):
                            pass  # SID etc.
                        continue

                    # Check for BINARY_EVENT (type 5)
                    if sio_part.startswith("5"):
                        # Extract ack id
                        rest = sio_part[1:]
                        dash_idx = rest.find("-")
                        if dash_idx >= 0:
                            try:
                                ack_id = int(rest[:dash_idx])
                                json_str = rest[dash_idx+1:]
                                event_data = json.loads(json_str)
                                event_name = event_data[0] if event_data else "unknown"
                                print(f"  [{elapsed:.1f}s] BINARY_EVENT name={event_name} ack_id={ack_id}", flush=True)

                                # Send ACK back
                                ack_msg = f"43{ack_id}-[true]"
                                await ws.send(ack_msg)
                                print(f"  [{elapsed:.1f}s] SENT ack id={ack_id}", flush=True)
                            except (json.JSONDecodeError, ValueError) as e:
                                print(f"  [{elapsed:.1f}s] parse error: {e}", flush=True)
                        continue

                    # Regular EVENT: "2[...]" or "2<n>-[...]"
                    if sio_part.startswith("2"):
                        rest = sio_part[1:]
                        dash_idx = rest.find("-")
                        if dash_idx >= 0:
                            try:
                                ack_id = int(rest[:dash_idx])
                                json_str = rest[dash_idx+1:]
                                event_data = json.loads(json_str)
                                event_name = event_data[0] if event_data else "unknown"
                                print(f"  [{elapsed:.1f}s] EVENT name={event_name} ack_id={ack_id}", flush=True)

                                # Send ACK
                                ack_msg = f"43{ack_id}-[true]"
                                await ws.send(ack_msg)
                                print(f"  [{elapsed:.1f}s] SENT ack id={ack_id}", flush=True)
                            except (json.JSONDecodeError, ValueError):
                                pass
                        else:
                            try:
                                event_data = json.loads(rest)
                                event_name = event_data[0] if event_data else "unknown"
                                print(f"  [{elapsed:.1f}s] EVENT name={event_name}", flush=True)
                            except (json.JSONDecodeError, ValueError):
                                pass
                        continue

        except asyncio.TimeoutError:
            print("  recv timeout (30s)", flush=True)
        except Exception as e:
            print(f"  recv error: {type(e).__name__}: {e}", flush=True)

    # Start recv loop
    recv_task = asyncio.create_task(recv_loop())
    await asyncio.sleep(0.5)

    # Step 1: EIO handshake already received by recv_loop
    # Step 2: SI connect
    print("\n=== Send SI connect ===", flush=True)
    await ws.send("40")
    await asyncio.sleep(2)

    # Step 3: Auth
    print("\n=== Send auth ===", flush=True)
    auth_payload = json.dumps(["auth", {
        "session": "AY7fG7xNFAC6M2_Rp",
        "isDemo": 1,
        "uid": 90292458,
        "platform": 1,
    }])
    await ws.send(f"42{auth_payload}")
    await asyncio.sleep(5)

    # Step 4: Get balance
    print("\n=== Send getBalance ===", flush=True)
    await ws.send('42["getBalance"]')
    await asyncio.sleep(5)

    # Step 5: Try to subscribe to an asset
    print("\n=== Subscribe to an asset ===", flush=True)
    await ws.send('42["subscribeSymbol",{"asset":"EURUSD","timeframe":60}]')
    await asyncio.sleep(10)

    # Step 6: Keep alive
    print("\n=== Keeping alive for 30 more seconds ===", flush=True)
    for i in range(6):
        await asyncio.sleep(5)
        if not ws.closed:
            print(f"  Still alive at {time.time()-start:.1f}s", flush=True)
        else:
            print(f"  DISCONNECTED at {time.time()-start:.1f}s", flush=True)
            break

    recv_task.cancel()
    try:
        await recv_task
    except asyncio.CancelledError:
        pass

    print(f"\nFinal: closed={ws.closed} code={ws.close_code} reason={ws.close_reason}", flush=True)


asyncio.run(test())

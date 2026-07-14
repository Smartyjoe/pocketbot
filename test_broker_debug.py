"""Debug script to test broker connection and find disconnect cause."""
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
    print(f"Connected! state={ws.state}", flush=True)

    messages = []
    start = time.time()

    async def recv_for(duration):
        try:
            while True:
                remaining = duration - (time.time() - start) % duration
                elapsed_total = time.time() - start
                msg = await asyncio.wait_for(ws.recv(), timeout=min(max(remaining, 0.1), 5))
                messages.append((time.time() - start, str(msg)[:200]))
                print(f"  [{time.time()-start:.1f}s] RECV: {str(msg)[:150]}", flush=True)

                if msg == "2":
                    await ws.send("3")
                    print(f"  [{time.time()-start:.1f}s] SENT pong", flush=True)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"  recv error at {time.time()-start:.1f}s: {e}", flush=True)

    # Step 1: Engine.IO handshake
    print("\n=== Step 1: EIO handshake ===", flush=True)
    await recv_for(5)

    # Step 2: Socket.IO connect
    print("\n=== Step 2: SI connect ===", flush=True)
    await ws.send("40")
    await recv_for(5)

    # Step 3: Auth
    print("\n=== Step 3: Auth ===", flush=True)
    auth_payload = json.dumps(["auth", {
        "session": "AY7fG7xNFAC6M2_Rp",
        "isDemo": 1,
        "uid": 90292458,
        "platform": 1,
    }])
    auth_msg = f"42{auth_payload}"
    await ws.send(auth_msg)
    await recv_for(10)

    # Step 4: Get balance
    print("\n=== Step 4: getBalance ===", flush=True)
    await ws.send(json.dumps(["getBalance"]))
    await recv_for(5)

    # Step 5: Keep alive and observe
    print("\n=== Step 5: Monitor for 30s ===", flush=True)
    monitor_start = time.time()
    try:
        while time.time() - monitor_start < 30:
            elapsed_total = time.time() - start
            remaining = 30 - (time.time() - monitor_start)
            msg = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5))
            messages.append((elapsed_total, str(msg)[:200]))
            print(f"  [{elapsed_total:.1f}s] RECV: {str(msg)[:150]}", flush=True)
            if msg == "2":
                await ws.send("3")
                print(f"  [{elapsed_total:.1f}s] SENT pong", flush=True)
    except asyncio.TimeoutError:
        print("  Timeout waiting for messages", flush=True)
    except Exception as e:
        print(f"  Error at {time.time()-start:.1f}s: {type(e).__name__}: {e}", flush=True)

    print(f"\n=== Final state ===", flush=True)
    print(f"WebSocket closed: {ws.closed}", flush=True)
    print(f"Close code: {ws.close_code}", flush=True)
    print(f"Close reason: {ws.close_reason}", flush=True)
    print(f"Total messages: {len(messages)}", flush=True)
    for t, m in messages:
        print(f"  [{t:.1f}s] {m[:120]}")


asyncio.run(test())

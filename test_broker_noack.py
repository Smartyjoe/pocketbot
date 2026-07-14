"""Debug: DON'T ack, just observe."""
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
        url, ssl=ssl_ctx,
        extra_headers={
            "Origin": "https://pocketoption.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        ping_interval=None, ping_timeout=None,
    )
    start = time.time()
    print("Connected!", flush=True)

    async def recv_loop():
        try:
            while not ws.closed:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                e = time.time() - start
                if isinstance(msg, bytes):
                    print(f"  [{e:.1f}s] BIN: {len(msg)} bytes", flush=True)
                    continue
                print(f"  [{e:.1f}s] RECV: {msg[:200]}", flush=True)
                if msg == "2":
                    await ws.send("3")
                    print(f"  [{e:.1f}s] pong", flush=True)
        except asyncio.TimeoutError:
            print("  30s recv timeout", flush=True)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"  error: {type(e).__name__}: {e}", flush=True)

    recv_task = asyncio.create_task(recv_loop())
    await asyncio.sleep(0.5)

    # EIO handshake should already be received
    print("\n=== SI connect ===", flush=True)
    await ws.send("40")
    await asyncio.sleep(2)

    print("\n=== Auth ===", flush=True)
    auth_payload = json.dumps(["auth", {
        "session": "AY7fG7xNFAC6M2_Rp",
        "isDemo": 1,
        "uid": 90292458,
        "platform": 1,
    }])
    await ws.send(f"42{auth_payload}")
    await asyncio.sleep(8)

    if not ws.closed:
        print("\n=== getBalance ===", flush=True)
        await ws.send('42["getBalance"]')
        await asyncio.sleep(10)

    if not ws.closed:
        print("\n=== subscribe ===", flush=True)
        await ws.send('42["subscribeSymbol",{"asset":"EURUSD-otc","timeframe":60}]')
        await asyncio.sleep(10)

    # Monitor
    print(f"\n=== Monitor ===", flush=True)
    for i in range(6):
        await asyncio.sleep(5)
        print(f"  [{time.time()-start:.1f}s] closed={ws.closed}", flush=True)
        if ws.closed:
            break

    recv_task.cancel()
    try:
        await recv_task
    except asyncio.CancelledError:
        pass
    print(f"\nFinal: closed={ws.closed} code={ws.close_code}", flush=True)


asyncio.run(test())

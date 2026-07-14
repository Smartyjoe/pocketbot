"""Raw connection test v2 - longer listen."""
import asyncio
import json
import ssl
from websockets.legacy.client import connect


SSID = '42["auth",{"session":"AY7fG7xNFAC6M2_Rp","isDemo":1,"uid":90292458,"platform":1}]'
URL = "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket"


async def main():
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    ws = await connect(
        URL,
        ssl=ssl_ctx,
        extra_headers={
            "Origin": "https://pocketoption.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        ping_interval=None,
        ping_timeout=None,
    )

    # Engine.IO handshake
    msg = await asyncio.wait_for(ws.recv(), timeout=10)
    print(f"EIO: {msg[:80]}")

    # Socket.IO connect
    await ws.send("40")
    msg = await asyncio.wait_for(ws.recv(), timeout=10)
    print(f"SIO: {msg[:80]}")

    # Auth
    await ws.send(SSID)
    print("AUTH sent")

    # Listen for all messages for 15 seconds
    messages = []
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            preview = msg[:200] if isinstance(msg, str) else f"binary({len(msg)} bytes)"
            messages.append(msg)
            print(f"RECV: {preview}")
    except asyncio.TimeoutError:
        pass

    print(f"\nTotal messages received: {len(messages)}")

    # Now try getBalance
    await ws.send('42["getBalance"]')
    print("getBalance sent")

    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"RECV BAL: {msg[:300]}")
    except asyncio.TimeoutError:
        pass

    # Try placing a small test request
    await ws.send('42["sendSignal",{"type":"subscribe","asset":"EURUSD"}]')
    print("subscribe sent")

    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"RECV SUB: {msg[:300]}")
    except asyncio.TimeoutError:
        pass

    await ws.close()


if __name__ == "__main__":
    asyncio.run(main())

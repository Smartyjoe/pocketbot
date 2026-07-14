"""Raw connection test to debug auth flow."""
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

    print(f"Connecting to {URL}...")
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
    print("Connected!")

    # Step 1: Receive Engine.IO handshake
    msg = await asyncio.wait_for(ws.recv(), timeout=10)
    print(f"RECV: {msg}")

    # Step 2: Send Socket.IO connect
    await ws.send("40")
    print("SENT: 40")

    # Step 3: Receive Socket.IO connect ack
    msg = await asyncio.wait_for(ws.recv(), timeout=10)
    print(f"RECV: {msg}")

    # Step 4: Send auth SSID
    await ws.send(SSID)
    print(f"SENT: {SSID}")

    # Step 5: Listen for responses
    for i in range(10):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"RECV [{i}]: {msg[:200]}")
        except asyncio.TimeoutError:
            print(f"TIMEOUT [{i}]")
            break

    # Step 6: Request balance
    await ws.send('42["getBalance"]')
    print("SENT: getBalance")

    for i in range(5):
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"RECV BAL [{i}]: {msg[:300]}")
        except asyncio.TimeoutError:
            print(f"TIMEOUT BAL [{i}]")
            break

    await ws.close()
    print("Done")


if __name__ == "__main__":
    asyncio.run(main())

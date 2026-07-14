"""Test broker connection to Pocket Option."""
import asyncio
from infrastructure.broker.pocket_option import PocketOptionBroker
from config.settings import load_settings


async def main():
    settings = load_settings()
    broker = PocketOptionBroker(config=settings.broker)

    # Add message logger
    async def log_msg(msg):
        if isinstance(msg, str):
            print(f"  RAW: {msg[:200]}")
    broker.on_message(log_msg)

    print("Connecting to Pocket Option...")
    try:
        await broker.connect()
        connected = await broker.is_connected()
        print(f"Connected: {connected}")

        if connected:
            print(f"Balance after connect: {broker._balance}")

            print("Requesting balance...")
            try:
                balance = await broker.get_balance()
                print(f"Balance: {balance.amount}")
            except Exception as e:
                print(f"Balance error: {e}")
                print(f"Balance cache: {broker._balance}")

            assets = await broker.get_available_assets()
            print(f"Available assets: {len(assets)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await broker.disconnect()
        print("Disconnected")


if __name__ == "__main__":
    asyncio.run(main())

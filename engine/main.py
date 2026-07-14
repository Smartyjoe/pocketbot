import asyncio
import signal as signal_module

import structlog
from telegram import Bot

from config.settings import load_settings
from infrastructure.persistence.database import init_db
from infrastructure.persistence.postgres.strategy_repository import StrategyRepository
from infrastructure.persistence.postgres.signal_repository import SignalRepository
from infrastructure.persistence.postgres.trade_repository import TradeRepository
from infrastructure.event_bus import InMemoryEventBus
from infrastructure.clock import SystemClock
from infrastructure.broker.pocket_option import PocketOptionBroker
from application.use_cases.trading import TradingUseCase
from application.use_cases.strategy import StrategyUseCase
from interfaces.telegram.bot import TradingBot
from interfaces.telegram.notifications import TelegramNotifier
from domain.events.trade_opened import TradeOpened
from domain.events.trade_expired import TradeExpired
from domain.events.balance_changed import BalanceChanged
from domain.events.broker_status import BrokerConnected, BrokerDisconnected, BrokerError
from domain.services.risk_calculator import RiskCalculator
from domain.services.signal_evaluator import SignalEvaluator
from domain.value_objects.money import Money

logger = structlog.get_logger()

SETTLE_INTERVAL = 10  # seconds between trade settlement checks
RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 120


async def broker_reconnect_loop(
    broker: PocketOptionBroker,
    event_bus: InMemoryEventBus,
) -> None:
    """Continuously try to reconnect the broker if disconnected."""
    delay = RECONNECT_BASE_DELAY
    while True:
        try:
            if not await broker.is_connected():
                logger.info("broker_reconnect_attempt", delay=delay)
                await event_bus.publish(BrokerDisconnected(
                    next_attempt_in=delay,
                ))
                try:
                    await broker.connect()
                    delay = RECONNECT_BASE_DELAY
                    await event_bus.publish(BrokerConnected())
                    logger.info("broker_reconnected")
                except Exception as e:
                    logger.error("broker_reconnect_failed", error=str(e))
                    await event_bus.publish(BrokerError(
                        error_code="RECONNECT_FAILED",
                        message=str(e),
                    ))
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, RECONNECT_MAX_DELAY)
            else:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("reconnect_loop_error")
            await asyncio.sleep(delay)


async def settlement_loop(
    trading_uc: TradingUseCase,
) -> None:
    """Periodically check and settle expired trades."""
    while True:
        try:
            settled = await trading_uc.settle_expired_trades()
            if settled:
                logger.info("trades_settled", count=len(settled))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("settlement_loop_error")
        await asyncio.sleep(SETTLE_INTERVAL)


async def main():
    settings = load_settings()
    logger.info("starting_engine", env=settings.logging.environment)

    # Initialize infrastructure — retry DB connection on failure
    engine = None
    session_factory = None
    for attempt in range(1, 6):
        try:
            engine, session_factory = await init_db(settings.postgres)
            logger.info("db_connected", attempt=attempt)
            break
        except Exception as e:
            logger.warning("db_connect_failed", attempt=attempt, error=str(e))
            if attempt < 5:
                await asyncio.sleep(10)
    if session_factory is None:
        logger.error("db_unavailable_starting_without_persistence")
        # Create a dummy session factory that always raises — callers must handle
        # This lets the Telegram bot start so the user can interact with it.
    event_bus = InMemoryEventBus()
    clock = SystemClock()
    broker = PocketOptionBroker(config=settings.broker)

    # Initialize repositories (only if DB is available)
    strategy_repo = StrategyRepository(session_factory) if session_factory else None
    signal_repo = SignalRepository(session_factory) if session_factory else None
    trade_repo = TradeRepository(session_factory) if session_factory else None

    # Initialize risk calculator
    risk_calculator = RiskCalculator(
        max_daily_loss=Money(amount=settings.trading.max_daily_loss),
        max_consecutive_losses=settings.trading.max_consecutive_losses,
        base_stake=Money(amount=settings.trading.base_stake),
        max_stake=Money(amount=settings.trading.max_stake),
    )

    # Initialize signal evaluator
    signal_evaluator = SignalEvaluator()

    # Initialize use cases
    trading_uc = TradingUseCase(
        broker=broker,
        event_bus=event_bus,
        strategy_repo=strategy_repo,
        signal_repo=signal_repo,
        trade_repo=trade_repo,
        risk_calculator=risk_calculator,
        signal_evaluator=signal_evaluator,
        min_confidence=settings.signal.min_confidence,
    )

    strategy_uc = StrategyUseCase(strategy_repo=strategy_repo)

    # Initialize Telegram bot and notifier
    telegram_bot = Bot(token=settings.telegram.bot_token.get_secret_value())
    notifier = TelegramNotifier(
        bot=telegram_bot,
        admin_user_ids=settings.telegram.admin_user_ids,
    )

    # Wire event subscriptions
    event_bus.subscribe(TradeOpened, notifier.on_trade_opened)
    event_bus.subscribe(TradeExpired, notifier.on_trade_expired)
    event_bus.subscribe(BalanceChanged, notifier.on_balance_changed)
    event_bus.subscribe(BrokerConnected, notifier.on_broker_connected)
    event_bus.subscribe(BrokerDisconnected, notifier.on_broker_disconnected)
    event_bus.subscribe(BrokerError, notifier.on_broker_error)

    # Initialize Telegram bot commands
    bot = TradingBot(
        config=settings,
        trading_use_case=trading_uc,
        strategy_use_case=strategy_uc,
    )
    app = bot.build()

    # Connect broker
    logger.info("connecting_broker")
    try:
        await broker.connect()
        await event_bus.publish(BrokerConnected())
        logger.info("broker_connected")
    except Exception as e:
        logger.error("broker_connection_failed", error=str(e))
        await event_bus.publish(BrokerError(
            error_code="INITIAL_CONNECT_FAILED",
            message=str(e),
        ))

    # Set up signal handling
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("shutdown_signal_received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal_module.SIGINT, signal_module.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    # Start the Telegram bot
    logger.info("starting_telegram_bot")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await bot.set_commands()

    # Start background loops
    reconnect_task = asyncio.create_task(broker_reconnect_loop(broker, event_bus))
    settlement_task = asyncio.create_task(settlement_loop(trading_uc))

    logger.info("engine_started")

    # Wait for shutdown
    await stop_event.wait()

    # Graceful shutdown
    logger.info("shutting_down")
    reconnect_task.cancel()
    settlement_task.cancel()
    await asyncio.gather(reconnect_task, settlement_task, return_exceptions=True)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await broker.disconnect()
    if engine is not None:
        await engine.dispose()
    logger.info("engine_stopped")


if __name__ == "__main__":
    asyncio.run(main())

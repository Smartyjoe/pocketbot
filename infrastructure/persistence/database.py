import asyncio
import sys
import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import PostgresConfig

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Database:
    def __init__(self, config: PostgresConfig) -> None:
        self._engine: AsyncEngine = create_async_engine(
            str(config.url),
            pool_size=config.pool_max,
            max_overflow=config.pool_max - config.pool_min,
            pool_pre_ping=True,
            connect_args={"timeout": config.connect_timeout},
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def session(self) -> AsyncSession:
        return self._session_factory()

    async def close(self) -> None:
        await self._engine.dispose()


async def init_db(config: PostgresConfig) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    db = Database(config)
    try:
        async with db._engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("Database connection established")
    except Exception:
        logger.exception("Database connection failed")
        raise
    return db.engine, db.session_factory

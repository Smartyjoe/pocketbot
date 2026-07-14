"""Test full SQLAlchemy async connection with the correct pooler."""
import asyncio
import sys

# Fix Windows event loop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text


async def main() -> None:
    url = "postgresql+asyncpg://postgres.wwizcetkljblramximwv:SZLY7yPyINN74qzO@aws-1-us-east-1.pooler.supabase.com:5432/postgres"

    engine = create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        print("[sqlalchemy] OK:", result.scalar())

        result2 = await session.execute(text("SELECT version()"))
        print("[version]", result2.scalar())

        result3 = await session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        )
        print("[tables]", [row[0] for row in result3.fetchall()])

    await engine.dispose()
    print("[sqlalchemy] Connection pool working!")


asyncio.run(main())

"""Test Supabase DB connections."""
import asyncio
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def test():
    tests = [
        ("SQLAlchemy pooler 6543", 
         "postgresql+asyncpg://postgres.wwizcetkljblramximwv:0101TRADEaVIATOR@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
         {"ssl": "require", "timeout": 15}),
        ("SQLAlchemy direct 5432",
         "postgresql+asyncpg://postgres:0101TRADEaVIATOR@db.wwizcetkljblramximwv.supabase.co:5432/postgres",
         {"ssl": "require", "timeout": 15}),
        ("SQLAlchemy pooler 6543 user=postgres",
         "postgresql+asyncpg://postgres:0101TRADEaVIATOR@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
         {"ssl": "require", "timeout": 15}),
        ("SQLAlchemy pooler 5432",
         "postgresql+asyncpg://postgres.wwizcetkljblramximwv:0101TRADEaVIATOR@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
         {"ssl": "require", "timeout": 15}),
    ]

    for label, url, kwargs in tests:
        print(f"\n{label} ... ", end="", flush=True)
        try:
            engine = create_async_engine(url, connect_args=kwargs)
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                print(f"OK! value={result.scalar()}")
            await engine.dispose()
        except Exception as e:
            print(f"FAIL: {type(e).__name__}: {str(e)[:200]}")

    # Also try raw asyncpg
    raw_tests = [
        ("raw asyncpg direct",
         "db.wwizcetkljblramximwv.supabase.co", 5432, "postgres"),
        ("raw asyncpg pooler 6543",
         "aws-0-us-east-1.pooler.supabase.com", 6543, "postgres.wwizcetkljblramximwv"),
        ("raw asyncpg pooler 5432",
         "aws-0-us-east-1.pooler.supabase.com", 5432, "postgres.wwizcetkljblramximwv"),
    ]

    for label, host, port, user in raw_tests:
        print(f"\n{label} ... ", end="", flush=True)
        try:
            conn = await asyncpg.connect(
                host=host, port=port, user=user,
                password="0101TRADEaVIATOR", database="postgres",
                ssl="require", timeout=15,
            )
            val = await conn.fetchval("SELECT 1")
            print(f"OK! val={val}")
            await conn.close()
        except Exception as e:
            print(f"FAIL: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    asyncio.run(test())

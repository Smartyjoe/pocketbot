import asyncio
import sqlalchemy
from infrastructure.persistence.database import init_db
from config.settings import load_settings


async def main():
    s = load_settings()
    e, f = await init_db(s.postgres)
    async with e.connect() as conn:
        r1 = await conn.execute(sqlalchemy.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'predictions' AND column_name = 'result_requested_at'"
        ))
        print("result_requested_at:", r1.scalar_one_or_none())

        r2 = await conn.execute(sqlalchemy.text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'training_data')"
        ))
        print("training_data:", r2.scalar_one())
    await e.dispose()


asyncio.run(main())

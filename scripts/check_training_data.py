"""Check available training data on the server."""
import asyncio
from sqlalchemy import text
from infrastructure.persistence.database import get_async_session


async def main():
    async for session in get_async_session():
        # Check predictions table
        r1 = await session.execute(text(
            "SELECT count(*) as total, "
            "count(result) as with_result, "
            "count(CASE WHEN result = 'win' THEN 1 END) as wins, "
            "count(CASE WHEN result = 'loss' THEN 1 END) as losses "
            "FROM predictions"
        ))
        row = r1.one()
        print(f"Predictions: total={row.total}, with_result={row.with_result}, wins={row.wins}, losses={row.losses}")

        # Check training_data table
        r2 = await session.execute(text(
            "SELECT count(*) as total, "
            "count(CASE WHEN label IS NOT NULL THEN 1 END) as labeled "
            "FROM training_data"
        ))
        row2 = r2.one()
        print(f"Training data: total={row2.total}, labeled={row2.labeled}")

        # Check column names in training_data
        r3 = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'training_data' ORDER BY ordinal_position"
        ))
        cols = [row[0] for row in r3.fetchall()]
        print(f"Training data columns: {cols}")

        # Check column names in predictions
        r4 = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'predictions' ORDER BY ordinal_position"
        ))
        cols2 = [row[0] for row in r4.fetchall()]
        print(f"Predictions columns: {cols2}")

        # Sample a prediction with result
        r5 = await session.execute(text(
            "SELECT id, pair, direction, result, confidence, "
            "created_at FROM predictions "
            "WHERE result IS NOT NULL ORDER BY created_at DESC LIMIT 3"
        ))
        for row in r5.fetchall():
            print(f"  Sample: id={row.id}, pair={row.pair}, dir={row.direction}, "
                  f"result={row.result}, conf={row.confidence}, at={row.created_at}")

        # Sample training_data features
        r6 = await session.execute(text(
            "SELECT * FROM training_data LIMIT 1"
        ))
        first = r6.mappings().first()
        if first:
            print(f"\nTraining data sample keys: {list(first.keys())}")
        else:
            print("\nNo training data rows yet")

        break


if __name__ == "__main__":
    asyncio.run(main())

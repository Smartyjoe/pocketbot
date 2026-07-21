"""Model training script — query DB for labeled data, train LightGBM, save model.

Usage:
    cd /home/ubuntu/pocketbot
    .venv/bin/python scripts/train_model.py

This script:
1. Connects to the PostgreSQL database
2. Queries training_data joined with predictions for labeled outcomes
3. Converts feature JSONB to a DataFrame
4. Trains a LightGBM model using the Trainer pipeline
5. Saves model to storage/models/ml/
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from infrastructure.ml.trainer import Trainer, TrainingConfig

logger = structlog.get_logger()

MIN_SAMPLES = 50


async def fetch_training_data(session_factory) -> pd.DataFrame | None:
    """Fetch labeled training data from the database.

    Joins training_data with predictions to get feature vectors
    paired with their Win/Loss outcomes.
    """
    async with session_factory() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    t.features,
                    t.win_probability,
                    t.symbol,
                    t.timeframe_sec,
                    t.direction,
                    t.entry_price,
                    p.result
                FROM training_data t
                JOIN predictions p ON
                    p.symbol = t.symbol
                    AND ABS(p.entry_price - t.entry_price) < 0.0001
                    AND p.entry_time IS NOT NULL
                WHERE p.result IN ('win', 'loss')
                ORDER BY t.created_at DESC
                """
            )
        )
        rows = result.mappings().all()

    if not rows:
        logger.warning("no_labeled_training_data")
        return None

    logger.info("training_data_fetched", count=len(rows))

    records = []
    for row in rows:
        features_raw = row["features"]
        if isinstance(features_raw, str):
            features = json.loads(features_raw)
        elif isinstance(features_raw, dict):
            features = features_raw
        else:
            continue

        # Convert to a flat record
        record = dict(features)
        record["label"] = 1 if row["result"] == "win" else 0
        record["symbol"] = row["symbol"]
        record["timeframe_sec"] = row["timeframe_sec"]
        record["win_probability"] = row["win_probability"]
        records.append(record)

    if not records:
        logger.warning("no_valid_records_after_parsing")
        return None

    df = pd.DataFrame(records)
    logger.info(
        "training_dataframe_created",
        rows=len(df),
        columns=len(df.columns),
        label_distribution=df["label"].value_counts().to_dict(),
    )
    return df


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Extract feature columns and labels from the training DataFrame.

    Drops non-feature columns (label, symbol, timeframe_sec, win_probability).
    """
    label_col = "label"
    meta_cols = {"label", "symbol", "timeframe_sec", "win_probability"}

    feature_cols = [c for c in df.columns if c not in meta_cols]
    features = df[feature_cols].copy()
    labels = df[label_col].copy()

    return features, labels


async def main() -> None:
    """Main training pipeline."""
    settings = load_settings()
    logger.info("starting_model_training")

    # Connect to database
    engine = None
    session_factory = None
    try:
        dsn = settings.postgres.dsn
        if dsn is None:
            dsn = (
                f"postgresql+asyncpg://{settings.postgres.user}"
                f":{settings.postgres.password.get_secret_value()}"
                f"@{settings.postgres.host}:{settings.postgres.port}"
                f"/{settings.postgres.database}"
            )
        engine = create_async_engine(dsn, pool_size=5, max_overflow=10)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        logger.info("database_connected")
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        return

    try:
        # Fetch training data
        df = await fetch_training_data(session_factory)
        if df is None or len(df) < MIN_SAMPLES:
            logger.warning(
                "insufficient_training_data",
                available=len(df) if df is not None else 0,
                required=MIN_SAMPLES,
            )
            print(
                f"\nNot enough training data. "
                f"Have {len(df) if df is not None else 0} labeled samples, "
                f"need at least {MIN_SAMPLES}.\n"
                f"Keep using the bot to collect more predictions, then try again."
            )
            return

        # Prepare features and labels
        features, labels = prepare_features(df)

        # Log label distribution
        pos_ratio = labels.mean()
        logger.info(
            "label_distribution",
            total=len(labels),
            wins=int(labels.sum()),
            losses=int((1 - labels).sum()),
            win_rate=f"{pos_ratio:.1%}",
        )

        # Train model
        config = TrainingConfig(
            model_version="1.0.0",
            test_ratio=0.2,
        )
        trainer = Trainer(config=config)

        print(f"\nTraining model on {len(features)} samples...")
        print(f"Features: {len(features.columns)}")
        print(f"Win rate: {pos_ratio:.1%}")

        result = trainer.train(df=pd.concat([features, labels], axis=1))

        # Save model
        model_dir = PROJECT_ROOT / "storage" / "models" / "ml"
        trainer.model.save(model_dir)

        print("\nModel trained successfully!")
        print(f"  Version: {result.model_version}")
        print(f"  Accuracy: {result.metrics.accuracy:.1%}")
        print(f"  AUC: {result.metrics.auc:.3f}")
        print(f"  F1: {result.metrics.f1:.3f}")
        print(f"  Train samples: {result.metrics.train_samples}")
        print(f"  Test samples: {result.metrics.test_samples}")
        print(f"\nSaved to: {model_dir}")

        # Print feature importance
        importance = trainer.model.feature_importance()
        if importance:
            print("\nTop features:")
            sorted_imp = sorted(importance.items(), key=lambda x: -x[1])[:10]
            for name, imp in sorted_imp:
                print(f"  {name}: {imp:.1%}")

    except Exception:
        logger.exception("training_failed")
        raise
    finally:
        if engine is not None:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

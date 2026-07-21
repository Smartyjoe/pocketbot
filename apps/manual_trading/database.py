"""Supabase database operations for predictions."""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.manual_trading.models import Prediction

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj: object) -> str:
    """Convert a dict to JSON string, replacing NaN/Inf with null.

    PostgreSQL JSON columns reject NaN tokens.  We walk the dict and
    swap any ``float('nan')`` or ``float('inf')`` values for ``None``
    so ``json.dumps`` produces valid JSON (``null``).
    """

    def _clean(val: object) -> object:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        if isinstance(val, dict):
            return {k: _clean(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_clean(v) for v in val]
        return val

    return json.dumps(_clean(obj))


class PredictionStore:
    """Reads and writes prediction rows via SQLAlchemy."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(self, prediction: Prediction) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO predictions
                        (id, telegram_id, symbol, timeframe_sec, direction,
                         confidence, reasoning, indicators, entry_price,
                         entry_time, expiry_time, result)
                    VALUES
                        (:id, :telegram_id, :symbol, :timeframe_sec, :direction,
                         :confidence, :reasoning, :indicators, :entry_price,
                         :entry_time, :expiry_time, :result)
                    """
                ),
                {
                    "id": str(prediction.id),
                    "telegram_id": prediction.telegram_id,
                    "symbol": prediction.symbol,
                    "timeframe_sec": prediction.timeframe_sec,
                    "direction": prediction.direction,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "indicators": _sanitize_for_json(prediction.indicators),
                    "entry_price": float(prediction.entry_price),
                    "entry_time": prediction.entry_time,
                    "expiry_time": prediction.expiry_time,
                    "result": prediction.result,
                },
            )
            await session.commit()
        logger.info(
            "prediction_inserted",
            prediction_id=str(prediction.id),
            symbol=prediction.symbol,
            direction=prediction.direction,
        )

    async def resolve(
        self,
        prediction_id: UUID,
        exit_price: Decimal,
        result: str,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE predictions
                    SET exit_price = :exit_price, result = :result
                    WHERE id = :id
                    """
                ),
                {
                    "id": str(prediction_id),
                    "exit_price": float(exit_price),
                    "result": result,
                },
            )
            await session.commit()
        logger.info(
            "prediction_resolved",
            prediction_id=str(prediction_id),
            result=result,
        )

    async def get_pending(self) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, telegram_id, symbol, timeframe_sec, direction,
                           confidence, reasoning, indicators, entry_price,
                           entry_time, expiry_time
                    FROM predictions
                    WHERE result IS NULL AND expiry_time <= :now
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": datetime.now(timezone.utc)},
            )
            rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def get_user_stats(self, telegram_id: int) -> dict:
        async with self._session_factory() as session:
            total = await session.execute(
                text(
                    "SELECT COUNT(*) as cnt FROM predictions "
                    "WHERE telegram_id = :tid AND result IS NOT NULL"
                ),
                {"tid": telegram_id},
            )
            total_count = total.scalar_one()

            wins = await session.execute(
                text(
                    "SELECT COUNT(*) as cnt FROM predictions "
                    "WHERE telegram_id = :tid AND result = 'win'"
                ),
                {"tid": telegram_id},
            )
            win_count = wins.scalar_one()

            by_symbol = await session.execute(
                text(
                    "SELECT symbol, "
                    "COUNT(*) as total, "
                    "SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins "
                    "FROM predictions "
                    "WHERE telegram_id = :tid AND result IS NOT NULL "
                    "GROUP BY symbol ORDER BY total DESC"
                ),
                {"tid": telegram_id},
            )
            symbol_rows = by_symbol.mappings().all()

            by_confidence = await session.execute(
                text(
                    "SELECT "
                    "CASE "
                    "  WHEN confidence >= 0.9 THEN '90%+' "
                    "  WHEN confidence >= 0.8 THEN '80-89%' "
                    "  WHEN confidence >= 0.7 THEN '70-79%' "
                    "  ELSE '<70%' "
                    "END as bucket, "
                    "COUNT(*) as total, "
                    "SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins "
                    "FROM predictions "
                    "WHERE telegram_id = :tid AND result IS NOT NULL "
                    "GROUP BY bucket ORDER BY bucket DESC"
                ),
                {"tid": telegram_id},
            )
            conf_rows = by_confidence.mappings().all()

        return {
            "total": total_count,
            "wins": win_count,
            "losses": total_count - win_count,
            "win_rate": (win_count / total_count * 100) if total_count > 0 else 0.0,
            "by_symbol": [
                {"symbol": r["symbol"], "total": r["total"], "wins": r["wins"]}
                for r in symbol_rows
            ],
            "by_confidence": [
                {"bucket": r["bucket"], "total": r["total"], "wins": r["wins"]}
                for r in conf_rows
            ],
        }

    async def get_recent(self, telegram_id: int, limit: int = 5) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT symbol, direction, confidence, entry_price,
                           exit_price, result, entry_time, expiry_time
                    FROM predictions
                    WHERE telegram_id = :tid
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"tid": telegram_id, "limit": limit},
            )
            rows = result.mappings().all()
        return [dict(row) for row in rows]

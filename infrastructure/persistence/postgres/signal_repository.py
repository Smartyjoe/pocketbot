from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.entities.signal import Signal
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.confidence import Confidence
from domain.ports.signal_repository import SignalRepositoryPort
from infrastructure.persistence.postgres.models import SignalModel


class SignalRepository(SignalRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def save(self, signal: Signal) -> None:
        async with self._factory() as session:
            model = SignalModel(
                signal_id=signal.signal_id,
                strategy_id=signal.strategy_id,
                symbol=signal.symbol.code,
                direction=signal.direction.value,
                confidence=signal.confidence.score,
                feature_values=signal.feature_values,
                candle_timestamp=signal.candle_timestamp,
                model_version=signal.model_version,
                is_approved=signal.is_approved,
                rejection_reason=signal.rejection_reason,
                created_at=signal.created_at,
            )
            session.add(model)
            await session.commit()

    async def get(self, signal_id: UUID) -> Signal | None:
        async with self._factory() as session:
            result = await session.execute(
                select(SignalModel).where(SignalModel.signal_id == signal_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._to_domain(model)

    async def list_by_strategy(self, strategy_id: UUID, limit: int = 100) -> list[Signal]:
        async with self._factory() as session:
            result = await session.execute(
                select(SignalModel)
                .where(SignalModel.strategy_id == strategy_id)
                .order_by(SignalModel.created_at.desc())
                .limit(limit)
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    async def list_since(self, since: datetime, limit: int = 100) -> list[Signal]:
        async with self._factory() as session:
            result = await session.execute(
                select(SignalModel)
                .where(SignalModel.created_at >= since)
                .order_by(SignalModel.created_at.desc())
                .limit(limit)
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    @staticmethod
    def _to_domain(model: SignalModel) -> Signal:
        return Signal(
            signal_id=model.signal_id,
            strategy_id=model.strategy_id,
            symbol=Symbol(code=model.symbol),
            direction=Direction(model.direction),
            confidence=Confidence(score=model.confidence),
            feature_values=model.feature_values or {},
            candle_timestamp=model.candle_timestamp,
            created_at=model.created_at,
            model_version=model.model_version,
            is_approved=model.is_approved,
            rejection_reason=model.rejection_reason,
        )

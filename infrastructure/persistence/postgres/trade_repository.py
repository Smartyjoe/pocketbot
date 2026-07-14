from uuid import UUID
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.entities.trade import Trade, TradeStatus, TradeResult
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money
from domain.ports.trade_repository import TradeRepositoryPort
from infrastructure.persistence.postgres.models import TradeModel


class TradeRepository(TradeRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def save(self, trade: Trade) -> None:
        async with self._factory() as session:
            model = TradeModel(
                trade_id=trade.trade_id,
                signal_id=trade.signal_id,
                strategy_id=trade.strategy_id,
                symbol=trade.symbol.code,
                direction=trade.direction.value,
                amount=trade.amount.amount,
                entry_price=trade.entry_price,
                expires_at=trade.expires_at,
                status=trade.status.value,
                result=trade.result.value,
                profit_loss=trade.profit_loss.amount,
                broker_trade_id=trade.broker_trade_id,
                opened_at=trade.opened_at,
                closed_at=trade.closed_at,
            )
            session.add(model)
            await session.commit()

    async def get(self, trade_id: UUID) -> Trade | None:
        async with self._factory() as session:
            result = await session.execute(
                select(TradeModel).where(TradeModel.trade_id == trade_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._to_domain(model)

    async def list_by_strategy(self, strategy_id: UUID, limit: int = 100) -> list[Trade]:
        async with self._factory() as session:
            result = await session.execute(
                select(TradeModel)
                .where(TradeModel.strategy_id == strategy_id)
                .order_by(TradeModel.opened_at.desc())
                .limit(limit)
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    async def list_open(self) -> list[Trade]:
        async with self._factory() as session:
            result = await session.execute(
                select(TradeModel)
                .where(TradeModel.status == TradeStatus.OPEN.value)
                .order_by(TradeModel.opened_at.desc())
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    async def list_since(self, since: datetime, limit: int = 100) -> list[Trade]:
        async with self._factory() as session:
            result = await session.execute(
                select(TradeModel)
                .where(TradeModel.opened_at >= since)
                .order_by(TradeModel.opened_at.desc())
                .limit(limit)
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    @staticmethod
    def _to_domain(model: TradeModel) -> Trade:
        return Trade(
            trade_id=model.trade_id,
            signal_id=model.signal_id,
            strategy_id=model.strategy_id,
            symbol=Symbol(code=model.symbol),
            direction=Direction(model.direction),
            amount=Money(amount=model.amount),
            entry_price=Decimal(str(model.entry_price)),
            expires_at=model.expires_at,
            status=TradeStatus(model.status),
            result=TradeResult(model.result),
            profit_loss=Money(amount=model.profit_loss),
            broker_trade_id=model.broker_trade_id,
            opened_at=model.opened_at,
            closed_at=model.closed_at,
        )

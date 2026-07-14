from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.entities.strategy import Strategy
from domain.ports.strategy_repository import StrategyRepositoryPort
from infrastructure.persistence.postgres.models import StrategyModel


class StrategyRepository(StrategyRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def save(self, strategy: Strategy) -> None:
        async with self._factory() as session:
            model = StrategyModel(
                strategy_id=strategy.strategy_id,
                name=strategy.name,
                version=strategy.version,
                description=strategy.description,
                parameters=strategy.parameters,
                is_active=strategy.is_active,
                backtest_win_rate=strategy.backtest_win_rate,
                backtest_profit_factor=strategy.backtest_profit_factor,
                backtest_total_trades=strategy.backtest_total_trades,
                live_total_trades=strategy.live_total_trades,
                live_wins=strategy.live_wins,
                live_losses=strategy.live_losses,
                created_at=strategy.created_at,
                updated_at=strategy.updated_at,
            )
            session.add(model)
            await session.commit()

    async def get(self, strategy_id: UUID) -> Strategy | None:
        async with self._factory() as session:
            result = await session.execute(
                select(StrategyModel).where(StrategyModel.strategy_id == strategy_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._to_domain(model)

    async def list_active(self) -> list[Strategy]:
        async with self._factory() as session:
            result = await session.execute(
                select(StrategyModel).where(StrategyModel.is_active == True)
            )
            return [self._to_domain(m) for m in result.scalars().all()]

    async def list_all(self) -> list[Strategy]:
        async with self._factory() as session:
            result = await session.execute(select(StrategyModel))
            return [self._to_domain(m) for m in result.scalars().all()]

    async def get_by_name(self, name: str) -> Strategy | None:
        async with self._factory() as session:
            result = await session.execute(
                select(StrategyModel).where(StrategyModel.name == name)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return None
            return self._to_domain(model)

    @staticmethod
    def _to_domain(model: StrategyModel) -> Strategy:
        return Strategy(
            strategy_id=model.strategy_id,
            name=model.name,
            version=model.version,
            description=model.description,
            parameters=model.parameters or {},
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
            backtest_win_rate=model.backtest_win_rate,
            backtest_profit_factor=model.backtest_profit_factor,
            backtest_total_trades=model.backtest_total_trades,
            live_total_trades=model.live_total_trades,
            live_wins=model.live_wins,
            live_losses=model.live_losses,
        )

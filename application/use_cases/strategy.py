from uuid import UUID

import structlog

from domain.entities.strategy import Strategy
from domain.ports.strategy_repository import StrategyRepositoryPort

logger = structlog.get_logger()


class StrategyUseCase:
    def __init__(self, strategy_repo: StrategyRepositoryPort) -> None:
        self._strategy_repo = strategy_repo

    async def create_strategy(
        self,
        name: str,
        parameters: dict[str, float] | None = None,
        version: str = "1.0.0",
        description: str = "",
    ) -> Strategy:
        if self._strategy_repo is None:
            raise ValueError("Database unavailable")
        existing = await self._strategy_repo.get_by_name(name)
        if existing:
            raise ValueError(f"Strategy '{name}' already exists")

        strategy = Strategy.create(
            name=name,
            parameters=parameters,
            version=version,
            description=description,
        )
        await self._strategy_repo.save(strategy)
        logger.info("strategy_created", strategy_id=str(strategy.strategy_id), name=name)
        return strategy

    async def activate_strategy(self, strategy_id: UUID) -> Strategy:
        if self._strategy_repo is None:
            raise ValueError("Database unavailable")
        strategy = await self._strategy_repo.get(strategy_id)
        if strategy is None:
            raise ValueError("Strategy not found")
        strategy.activate()
        await self._strategy_repo.save(strategy)
        logger.info("strategy_activated", strategy_id=str(strategy_id))
        return strategy

    async def deactivate_strategy(self, strategy_id: UUID) -> Strategy:
        if self._strategy_repo is None:
            raise ValueError("Database unavailable")
        strategy = await self._strategy_repo.get(strategy_id)
        if strategy is None:
            raise ValueError("Strategy not found")
        strategy.deactivate()
        await self._strategy_repo.save(strategy)
        logger.info("strategy_deactivated", strategy_id=str(strategy_id))
        return strategy

    async def list_strategies(self) -> list[Strategy]:
        if self._strategy_repo is None:
            return []
        return await self._strategy_repo.list_all()

    async def list_active_strategies(self) -> list[Strategy]:
        if self._strategy_repo is None:
            return []
        return await self._strategy_repo.list_active()

    async def get_strategy(self, strategy_id: UUID) -> Strategy | None:
        return await self._strategy_repo.get(strategy_id)

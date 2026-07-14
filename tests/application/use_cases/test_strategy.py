import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from application.use_cases.strategy import StrategyUseCase


@pytest.fixture
def mock_strategy_repo():
    repo = AsyncMock()
    repo.get_by_name.return_value = None
    repo.list_all.return_value = []
    repo.list_active.return_value = []
    return repo


@pytest.fixture
def strategy_uc(mock_strategy_repo):
    return StrategyUseCase(strategy_repo=mock_strategy_repo)


@pytest.mark.asyncio
async def test_create_strategy(strategy_uc, mock_strategy_repo):
    strategy = await strategy_uc.create_strategy(
        name="test_strategy",
        parameters={"threshold": 0.7},
        version="1.0.0",
    )

    assert strategy.name == "test_strategy"
    assert strategy.parameters == {"threshold": 0.7}
    assert strategy.version == "1.0.0"
    mock_strategy_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_create_duplicate_strategy(strategy_uc, mock_strategy_repo):
    from domain.entities.strategy import Strategy
    existing = Strategy.create(name="existing")
    mock_strategy_repo.get_by_name.return_value = existing

    with pytest.raises(ValueError, match="already exists"):
        await strategy_uc.create_strategy(name="existing")


@pytest.mark.asyncio
async def test_activate_strategy(strategy_uc, mock_strategy_repo):
    from domain.entities.strategy import Strategy
    strategy = Strategy.create(name="test")
    mock_strategy_repo.get.return_value = strategy

    result = await strategy_uc.activate_strategy(strategy.strategy_id)
    assert result.is_active is True
    mock_strategy_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_activate_nonexistent_strategy(strategy_uc, mock_strategy_repo):
    mock_strategy_repo.get.return_value = None

    with pytest.raises(ValueError, match="not found"):
        await strategy_uc.activate_strategy(uuid4())

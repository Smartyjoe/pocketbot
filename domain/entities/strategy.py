from uuid import UUID, uuid4
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Strategy:
    strategy_id: UUID
    name: str
    version: str
    description: str
    parameters: dict[str, float]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    backtest_win_rate: float | None = None
    backtest_profit_factor: float | None = None
    backtest_total_trades: int = 0
    live_total_trades: int = 0
    live_wins: int = 0
    live_losses: int = 0

    @classmethod
    def create(
        cls,
        name: str,
        parameters: dict[str, float] | None = None,
        version: str = "1.0.0",
        description: str = "",
    ) -> "Strategy":
        now = datetime.now(timezone.utc)
        return cls(
            strategy_id=uuid4(),
            name=name,
            version=version,
            description=description,
            parameters=parameters or {},
            is_active=False,
            created_at=now,
            updated_at=now,
        )

    def activate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.now(timezone.utc)

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.now(timezone.utc)

    def update_parameters(self, params: dict[str, float]) -> None:
        self.parameters.update(params)
        self.updated_at = datetime.now(timezone.utc)

    def record_result(self, won: bool) -> None:
        self.live_total_trades += 1
        if won:
            self.live_wins += 1
        else:
            self.live_losses += 1
        self.updated_at = datetime.now(timezone.utc)

    @property
    def live_win_rate(self) -> float:
        if self.live_total_trades == 0:
            return 0.0
        return self.live_wins / self.live_total_trades

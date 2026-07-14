from dataclasses import dataclass, field
from uuid import UUID
from datetime import datetime
from decimal import Decimal


@dataclass
class OpenTradeDTO:
    symbol: str
    direction: str
    amount: Decimal
    duration_seconds: int
    signal_id: UUID | None = None
    strategy_id: UUID | None = None


@dataclass
class TradeResultDTO:
    trade_id: UUID
    symbol: str
    direction: str
    amount: Decimal
    entry_price: Decimal
    result: str
    profit_loss: Decimal
    opened_at: datetime
    closed_at: datetime | None


@dataclass
class SignalDTO:
    signal_id: UUID
    strategy_name: str
    symbol: str
    direction: str
    confidence: float
    confidence_label: str
    candle_timestamp: datetime
    is_approved: bool
    rejection_reason: str


@dataclass
class StrategyDTO:
    strategy_id: UUID
    name: str
    version: str
    is_active: bool
    live_win_rate: float
    live_total_trades: int
    live_wins: int
    live_losses: int


@dataclass
class DashboardDTO:
    balance: Decimal
    open_trades: list[TradeResultDTO] = field(default_factory=list)
    daily_pnl: Decimal = Decimal("0")
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    is_paused: bool = False
    pause_reason: str = ""


@dataclass
class RiskDTO:
    daily_loss: Decimal
    daily_loss_limit: Decimal
    consecutive_losses: int
    consecutive_loss_limit: int
    is_stoppped: bool
    stop_reason: str
    current_stake: Decimal

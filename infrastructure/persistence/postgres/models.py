from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class StrategyModel(Base):
    __tablename__ = "strategies"

    strategy_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(Text, nullable=False, unique=True)
    version = Column(Text, nullable=False, default="1.0.0")
    description = Column(Text, nullable=False, default="")
    parameters = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=False)

    backtest_win_rate = Column(Double, nullable=True)
    backtest_profit_factor = Column(Double, nullable=True)
    backtest_total_trades = Column(Integer, nullable=False, default=0)

    live_total_trades = Column(Integer, nullable=False, default=0)
    live_wins = Column(Integer, nullable=False, default=0)
    live_losses = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SignalModel(Base):
    __tablename__ = "signals"

    signal_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("strategies.strategy_id", ondelete="CASCADE"), nullable=False)
    symbol = Column(Text, nullable=False)
    direction = Column(Text, nullable=False)
    confidence = Column(Double, nullable=False)
    feature_values = Column(JSONB, nullable=False, default=dict)
    candle_timestamp = Column(DateTime(timezone=True), nullable=False)
    model_version = Column(Text, nullable=False, default="")
    is_approved = Column(Boolean, nullable=False, default=False)
    rejection_reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TradeModel(Base):
    __tablename__ = "trades"

    trade_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    signal_id = Column(UUID(as_uuid=True), ForeignKey("signals.signal_id", ondelete="SET NULL"), nullable=True)
    strategy_id = Column(UUID(as_uuid=True), ForeignKey("strategies.strategy_id", ondelete="SET NULL"), nullable=True)
    symbol = Column(Text, nullable=False)
    direction = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    entry_price = Column(Numeric(20, 8), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False, default="open")
    result = Column(Text, nullable=False, default="pending")
    profit_loss = Column(Numeric(12, 2), nullable=False, default=0)
    broker_trade_id = Column(Text, nullable=False, default="")
    opened_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)


class TradeSessionModel(Base):
    __tablename__ = "trade_sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    date = Column(Date, nullable=False, unique=True, default=date.today)
    starting_balance = Column(Numeric(12, 2), nullable=False)
    current_balance = Column(Numeric(12, 2), nullable=False)
    daily_pnl = Column(Numeric(12, 2), nullable=False, default=0)
    total_trades = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    consecutive_losses = Column(Integer, nullable=False, default=0)
    is_paused = Column(Boolean, nullable=False, default=False)
    pause_reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class MLModel(Base):
    __tablename__ = "ml_models"

    model_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(Text, nullable=False)
    version = Column(Text, nullable=False)
    algorithm = Column(Text, nullable=False, default="")
    features = Column(JSONB, nullable=False, default=list)
    metrics = Column(JSONB, nullable=False, default=dict)
    file_path = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

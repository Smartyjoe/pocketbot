from datetime import datetime, timezone
from decimal import Decimal

import structlog

from domain.entities.signal import Signal
from domain.entities.trade import Trade
from domain.value_objects.symbol import Symbol
from domain.value_objects.direction import Direction
from domain.value_objects.money import Money
from domain.value_objects.confidence import Confidence
from domain.services.risk_calculator import RiskCalculator
from domain.services.signal_evaluator import SignalEvaluator
from domain.ports.event_bus import EventBusPort
from domain.ports.broker_port import BrokerPort
from domain.ports.strategy_repository import StrategyRepositoryPort
from domain.ports.signal_repository import SignalRepositoryPort
from domain.ports.trade_repository import TradeRepositoryPort
from domain.events.signal_generated import SignalGenerated
from domain.events.trade_opened import TradeOpened
from domain.events.trade_expired import TradeExpired

logger = structlog.get_logger()


class TradingUseCase:
    def __init__(
        self,
        broker: BrokerPort,
        event_bus: EventBusPort,
        strategy_repo: StrategyRepositoryPort,
        signal_repo: SignalRepositoryPort,
        trade_repo: TradeRepositoryPort,
        risk_calculator: RiskCalculator,
        signal_evaluator: SignalEvaluator,
        min_confidence: float = 0.6,
    ) -> None:
        self._broker = broker
        self._event_bus = event_bus
        self._strategy_repo = strategy_repo
        self._signal_repo = signal_repo
        self._trade_repo = trade_repo
        self._risk_calculator = risk_calculator
        self._signal_evaluator = signal_evaluator
        self._min_confidence = min_confidence

    async def process_signal(
        self,
        strategy_id,
        symbol_code: str,
        direction_str: str,
        confidence_score: float,
        feature_values: dict[str, float],
        candle_timestamp,
        model_version: str = "",
    ) -> Trade | None:
        strategy = await self._strategy_repo.get(strategy_id)
        if strategy is None or not strategy.is_active:
            logger.warning("signal_skipped_inactive_strategy", strategy_id=str(strategy_id))
            return None

        symbol = Symbol(code=symbol_code)
        direction = Direction.from_str(direction_str)
        confidence = Confidence(score=confidence_score)

        signal = Signal.create(
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            candle_timestamp=candle_timestamp,
            feature_values=feature_values,
            model_version=model_version,
        )

        if not self._signal_evaluator.evaluate(signal, min_confidence=self._min_confidence):
            await self._signal_repo.save(signal)
            logger.info("signal_rejected", signal_id=str(signal.signal_id))
            return None

        await self._signal_repo.save(signal)
        await self._event_bus.publish(SignalGenerated(
            signal_id=signal.signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            feature_values=feature_values,
            candle_timestamp=candle_timestamp,
            model_version=model_version,
        ))

        balance = await self._broker.get_balance()
        open_trades = await self._trade_repo.list_open()
        consecutive_losses = strategy.live_losses
        daily_loss = Money(amount="0")

        stake = self._risk_calculator.calculate_stake(
            confidence_score=confidence_score,
            current_balance=balance,
            consecutive_losses=consecutive_losses,
            daily_loss=daily_loss,
        )

        if stake.is_zero():
            logger.info("trade_blocked_risk", signal_id=str(signal.signal_id))
            return None

        broker_trade_id = await self._broker.place_trade(
            symbol=symbol,
            direction=direction,
            amount=stake,
            duration_seconds=60,
        )

        trade = Trade.open(
            symbol=symbol,
            direction=direction,
            amount=stake,
            entry_price=await self._broker.get_current_price(symbol),
            expires_at=candle_timestamp,
            signal_id=signal.signal_id,
            strategy_id=strategy_id,
            broker_trade_id=broker_trade_id,
        )

        await self._trade_repo.save(trade)
        await self._event_bus.publish(TradeOpened(
            trade_id=trade.trade_id,
            signal_id=signal.signal_id,
            strategy_id=strategy_id,
            symbol=symbol,
            direction=direction,
            amount=stake,
            entry_price=trade.entry_price.amount,
            expires_at=trade.expires_at,
            broker_trade_id=broker_trade_id,
        ))

        logger.info("trade_opened", trade_id=str(trade.trade_id), stake=str(stake))
        return trade

    async def manual_trade(
        self,
        symbol_code: str,
        direction_str: str,
        amount: Decimal,
        duration_seconds: int = 60,
    ) -> Trade:
        symbol = Symbol(code=symbol_code)
        direction = Direction.from_str(direction_str)
        stake = Money(amount=amount)

        broker_trade_id = await self._broker.place_trade(
            symbol=symbol,
            direction=direction,
            amount=stake,
            duration_seconds=duration_seconds,
        )

        entry_price = await self._broker.get_current_price(symbol)
        from datetime import datetime, timezone, timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)

        trade = Trade.open(
            symbol=symbol,
            direction=direction,
            amount=stake,
            entry_price=entry_price,
            expires_at=expires_at,
            broker_trade_id=broker_trade_id,
        )

        await self._trade_repo.save(trade)
        await self._event_bus.publish(TradeOpened(
            trade_id=trade.trade_id,
            symbol=symbol,
            direction=direction,
            amount=stake,
            entry_price=entry_price.amount,
            expires_at=expires_at,
            broker_trade_id=broker_trade_id,
        ))

        logger.info("manual_trade_opened", trade_id=str(trade.trade_id))
        return trade

    async def settle_expired_trades(self) -> list[Trade]:
        """Check open trades for expiry and settle them with exit prices."""
        if self._trade_repo is None:
            return []
        open_trades = await self._trade_repo.list_open()
        now = datetime.now(timezone.utc)
        settled: list[Trade] = []

        for trade in open_trades:
            if not trade.is_expired(now):
                continue

            try:
                exit_price = await self._broker.get_current_price(trade.symbol)
            except Exception:
                exit_price = trade.entry_price

            trade.close(exit_price)
            await self._trade_repo.save(trade)
            settled.append(trade)

            await self._event_bus.publish(TradeExpired(
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                direction=trade.direction,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                result=trade.result.value,
                profit_loss=trade.profit_loss,
            ))

            logger.info(
                "trade_settled",
                trade_id=str(trade.trade_id),
                result=trade.result.value,
                pnl=str(trade.profit_loss),
            )

        return settled

    async def get_open_trades(self) -> list[Trade]:
        if self._trade_repo is None:
            return []
        return await self._trade_repo.list_open()

    async def get_recent_trades(self, limit: int = 20) -> list[Trade]:
        if self._trade_repo is None:
            return []
        from datetime import datetime, timezone, timedelta
        since = datetime.now(timezone.utc) - timedelta(days=7)
        return await self._trade_repo.list_since(since, limit=limit)

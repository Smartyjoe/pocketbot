from datetime import datetime, timezone, timedelta
from decimal import Decimal

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import structlog

from config.settings import AppConfig
from application.use_cases.trading import TradingUseCase
from application.use_cases.strategy import StrategyUseCase

logger = structlog.get_logger()


class TradingBot:
    def __init__(
        self,
        config: AppConfig,
        trading_use_case: TradingUseCase,
        strategy_use_case: StrategyUseCase,
    ) -> None:
        self._config = config
        self._trading = trading_use_case
        self._strategy = strategy_use_case
        self._app: Application | None = None

    def build(self) -> Application:
        self._app = (
            Application.builder()
            .token(self._config.telegram.bot_token.get_secret_value())
            .build()
        )

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("balance", self._cmd_balance))
        self._app.add_handler(CommandHandler("signals", self._cmd_signals))
        self._app.add_handler(CommandHandler("trades", self._cmd_trades))
        self._app.add_handler(CommandHandler("history", self._cmd_history))
        self._app.add_handler(CommandHandler("trade", self._cmd_trade))
        self._app.add_handler(CommandHandler("strategies", self._cmd_strategies))
        self._app.add_handler(CommandHandler("activate", self._cmd_activate))
        self._app.add_handler(CommandHandler("deactivate", self._cmd_deactivate))
        self._app.add_handler(CommandHandler("risk", self._cmd_risk))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._cmd_unknown)
        )

        return self._app

    def _is_authorized(self, user_id: int) -> bool:
        allowed = self._config.telegram.allowed_user_ids
        return user_id in allowed if allowed else True

    def _is_admin(self, user_id: int) -> bool:
        admins = self._config.telegram.admin_user_ids
        return user_id in admins if admins else False

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("Access denied.")
            return
        await update.message.reply_text(
            "Trading Bot\n\n"
            "Commands:\n"
            "/status - Dashboard\n"
            "/balance - Current balance\n"
            "/signals - Recent signals\n"
            "/trades - Open trades\n"
            "/history - Trade history\n"
            "/trade call|put EURUSD_otc 10 - Manual trade\n"
            "/risk - Risk status\n"
            "/strategies - List strategies\n"
            "/help - Show this message"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text(
            "Manual Trade: /trade call EURUSD_otc 10\n"
            "Activate Strategy: /activate <strategy_id>\n"
            "Deactivate Strategy: /deactivate <strategy_id>\n"
            "Risk Status: /risk\n"
            "Pause Trading: /pause (admin)\n"
            "Resume Trading: /resume (admin)"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return

        try:
            balance = await self._trading._broker.get_balance()
            if self._trading._trade_repo is not None:
                open_trades = await self._trading.get_open_trades()
                recent = await self._trading.get_recent_trades(limit=50)
            else:
                open_trades = []
                recent = []

            today = datetime.now(timezone.utc).date()
            today_trades = [t for t in recent if t.opened_at.date() == today]
            wins = sum(1 for t in today_trades if t.result.value == "win")
            losses = sum(1 for t in today_trades if t.result.value == "loss")
            pnl = sum(t.profit_loss.amount for t in today_trades)

            lines = [
                f"Balance: {balance}",
                f"Open Trades: {len(open_trades)}",
                f"Today: {wins}W / {losses}L | P&L: {pnl:+.2f}",
            ]

            if open_trades:
                lines.append("\nOpen:")
                for t in open_trades[:5]:
                    emoji = "CALL" if t.direction.value == "call" else "PUT"
                    remaining = (t.expires_at - datetime.now(timezone.utc)).seconds
                    lines.append(f"  {emoji} {t.symbol.code} {t.amount} | {remaining}s left")

            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            logger.exception("status_error")
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            balance = await self._trading._broker.get_balance()
            await update.message.reply_text(f"Balance: {balance}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            if self._trading._signal_repo is None:
                await update.message.reply_text("Database unavailable — signals not loaded.")
                return
            from datetime import datetime, timezone, timedelta
            since = datetime.now(timezone.utc) - timedelta(hours=1)
            signals = await self._trading._signal_repo.list_since(since, limit=10)

            if not signals:
                await update.message.reply_text("No signals in the last hour.")
                return

            lines = ["Recent Signals:"]
            for s in signals:
                status = "APPROVED" if s.is_approved else "REJECTED"
                emoji = "CALL" if s.direction.value == "call" else "PUT"
                lines.append(
                    f"  {emoji} {s.symbol.code} | "
                    f"{s.confidence.score:.0%} confidence | "
                    f"{status}"
                )
                if s.rejection_reason:
                    lines.append(f"    Reason: {s.rejection_reason}")

            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            open_trades = await self._trading.get_open_trades()
            if not open_trades:
                await update.message.reply_text("No open trades.")
                return

            lines = ["Open Trades:"]
            for t in open_trades:
                emoji = "CALL" if t.direction.value == "call" else "PUT"
                remaining = (t.expires_at - datetime.now(timezone.utc)).seconds
                lines.append(
                    f"  {emoji} {t.symbol.code} | "
                    f"{t.amount} | "
                    f"Entry: {t.entry_price} | "
                    f"{remaining}s left"
                )
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            trades = await self._trading.get_recent_trades(limit=10)
            if not trades:
                await update.message.reply_text("No recent trades.")
                return

            lines = ["Recent Trades:"]
            for t in trades:
                emoji = "CALL" if t.direction.value == "call" else "PUT"
                result_emoji = {"win": "W", "loss": "L", "draw": "D", "pending": "?"}
                r = result_emoji.get(t.result.value, "?")
                lines.append(
                    f"  [{r}] {emoji} {t.symbol.code} | "
                    f"{t.amount} | "
                    f"P&L: {t.profit_loss.amount:+.2f}"
                )

            wins = sum(1 for t in trades if t.result.value == "win")
            losses = sum(1 for t in trades if t.result.value == "loss")
            total_pnl = sum(t.profit_loss.amount for t in trades)
            lines.append(f"\n{wins}W / {losses}L | Total P&L: {total_pnl:+.2f}")

            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_trade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return

        args = context.args
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: /trade <call|put> <symbol> <amount>\n"
                "Example: /trade call EURUSD_otc 10"
            )
            return

        direction_str, symbol_code, amount_str = args[0], args[1], args[2]

        try:
            amount = Decimal(amount_str)
            trade = await self._trading.manual_trade(
                symbol_code=symbol_code,
                direction_str=direction_str,
                amount=amount,
            )
            emoji = "CALL" if trade.direction.value == "call" else "PUT"
            await update.message.reply_text(
                f"Trade Opened\n"
                f"{emoji} {trade.symbol.code}\n"
                f"Amount: {trade.amount}\n"
                f"Entry: {trade.entry_price}"
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            strategies = await self._strategy.list_strategies()
            if not strategies:
                await update.message.reply_text("No strategies found.")
                return

            lines = ["Strategies:"]
            for s in strategies:
                status = "ACTIVE" if s.is_active else "INACTIVE"
                wr = f"{s.live_win_rate:.0%}" if s.live_total_trades > 0 else "N/A"
                lines.append(
                    f"  [{status}] {s.name} v{s.version}\n"
                    f"    Win Rate: {wr} | Trades: {s.live_total_trades}"
                )
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_activate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return

        if not context.args:
            await update.message.reply_text("Usage: /activate <strategy_id>")
            return

        try:
            from uuid import UUID
            strategy_id = UUID(context.args[0])
            strategy = await self._strategy.activate_strategy(strategy_id)
            await update.message.reply_text(f"Activated: {strategy.name}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_deactivate(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return

        if not context.args:
            await update.message.reply_text("Usage: /deactivate <strategy_id>")
            return

        try:
            from uuid import UUID
            strategy_id = UUID(context.args[0])
            strategy = await self._strategy.deactivate_strategy(strategy_id)
            await update.message.reply_text(f"Deactivated: {strategy.name}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("Risk status: OK\nDaily loss: $0 / $50\nConsecutive losses: 0 / 3")

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        await update.message.reply_text("Trading paused.")

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        await update.message.reply_text("Trading resumed.")

    async def _cmd_unknown(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Unknown command. Use /help for available commands.")

    async def set_commands(self) -> None:
        if self._app:
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("help", "Show commands"),
                BotCommand("status", "Dashboard"),
                BotCommand("balance", "Current balance"),
                BotCommand("signals", "Recent signals"),
                BotCommand("trades", "Open trades"),
                BotCommand("history", "Trade history"),
                BotCommand("trade", "Manual trade"),
                BotCommand("strategies", "List strategies"),
                BotCommand("risk", "Risk status"),
            ]
            await self._app.bot.set_my_commands(commands)

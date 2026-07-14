from decimal import Decimal

from domain.value_objects.money import Money


class RiskCalculator:
    def __init__(
        self,
        max_daily_loss: Money = Money(amount="50"),
        max_consecutive_losses: int = 3,
        base_stake: Money = Money(amount="2"),
        max_stake: Money = Money(amount="10"),
    ):
        self.max_daily_loss = max_daily_loss
        self.max_consecutive_losses = max_consecutive_losses
        self.base_stake = base_stake
        self.max_stake = max_stake

    def calculate_stake(
        self,
        confidence_score: float,
        current_balance: Money,
        consecutive_losses: int,
        daily_loss: Money,
    ) -> Money:
        if daily_loss >= self.max_daily_loss:
            return Money(amount="0")

        if consecutive_losses >= self.max_consecutive_losses:
            return Money(amount="0")

        stake_multiplier = Decimal(str(0.5 + confidence_score))
        stake = Money(
            amount=(self.base_stake.amount * stake_multiplier).quantize(
                Decimal("0.01")
            )
        )

        if stake > self.max_stake:
            stake = self.max_stake

        if stake > current_balance * Decimal("0.1"):
            stake = Money(amount=(current_balance.amount * Decimal("0.1")).quantize(Decimal("0.01")))

        return stake

    def should_stop_trading(
        self,
        consecutive_losses: int,
        daily_loss: Money,
        daily_loss_limit: Money | None = None,
    ) -> tuple[bool, str]:
        limit = daily_loss_limit or self.max_daily_loss
        if daily_loss >= limit:
            return True, f"Daily loss limit {limit} reached"
        if consecutive_losses >= self.max_consecutive_losses:
            return True, f"{consecutive_losses} consecutive losses reached"
        return False, ""

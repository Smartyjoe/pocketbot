from decimal import Decimal, ROUND_HALF_UP
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator


class CurrencyMismatchError(ValueError):
    pass


class Money(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str = "USD"

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        if isinstance(v, Decimal):
            return v
        if isinstance(v, (int, float, str)):
            return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        raise TypeError(f"Cannot coerce {type(v)} to Decimal")

    def _check_currency(self, other: Self) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Cannot operate on different currencies: {self.currency} vs {other.currency}"
            )

    def __add__(self, other: Self) -> "Money":
        self._check_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Self) -> "Money":
        self._check_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int | float) -> "Money":
        return Money(amount=self.amount * Decimal(str(factor)), currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    def __abs__(self) -> "Money":
        return Money(amount=abs(self.amount), currency=self.currency)

    def __ge__(self, other: Self) -> bool:
        self._check_currency(other)
        return self.amount >= other.amount

    def __gt__(self, other: Self) -> bool:
        self._check_currency(other)
        return self.amount > other.amount

    def __le__(self, other: Self) -> bool:
        self._check_currency(other)
        return self.amount <= other.amount

    def __lt__(self, other: Self) -> bool:
        self._check_currency(other)
        return self.amount < other.amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_zero(self) -> bool:
        return self.amount == 0

    def as_float(self) -> float:
        return float(self.amount)

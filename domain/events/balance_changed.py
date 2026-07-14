from domain.events.base import DomainEvent
from domain.value_objects.money import Money


class BalanceChanged(DomainEvent):
    old_balance: Money
    new_balance: Money

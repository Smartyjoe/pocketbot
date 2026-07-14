from typing import Protocol, Any
from collections.abc import Callable, Awaitable

from domain.events.base import DomainEvent

EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBusPort(Protocol):
    async def publish(self, event: DomainEvent) -> None:
        ...

    def subscribe(
        self, event_type: type[DomainEvent], handler: EventHandler
    ) -> None:
        ...

    def unsubscribe(
        self, event_type: type[DomainEvent], handler: EventHandler
    ) -> None:
        ...

import asyncio
from collections import defaultdict

import structlog

from domain.events.base import DomainEvent
from domain.ports.event_bus import EventBusPort, EventHandler

logger = structlog.get_logger()


class InMemoryEventBus(EventBusPort):
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)

    async def publish(self, event: DomainEvent) -> None:
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        logger.info("event_published", event_type=event_type.__name__, handler_count=len(handlers))
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception("event_handler_error", event_type=event_type.__name__)

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)
        logger.debug("event_subscribed", event_type=event_type.__name__)

    def unsubscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

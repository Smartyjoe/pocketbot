from domain.events.base import DomainEvent


class BrokerConnected(DomainEvent):
    pass


class BrokerDisconnected(DomainEvent):
    reconnect_attempt: int = 0
    next_attempt_in: float = 5.0


class BrokerError(DomainEvent):
    error_code: str = ""
    message: str = ""

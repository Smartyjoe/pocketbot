from uuid import UUID, uuid4
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

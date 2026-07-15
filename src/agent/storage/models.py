"""Plain dataclasses for persisted records."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class Incident:
    id: str
    service: str
    summary: str
    status: str = "open"
    created_at: str | None = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

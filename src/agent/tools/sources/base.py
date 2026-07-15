"""Common interface for external infrastructure sources."""

from abc import ABC, abstractmethod


class Source(ABC):
    @abstractmethod
    async def query(self, query: str) -> dict:
        raise NotImplementedError

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WebSearchResult:
    query: str
    title: str
    url: str
    text: str


class WebSearchPort(Protocol):
    async def search(self, queries: list[str]) -> list[WebSearchResult]:
        """Search the public web. It never opens a page the caller names."""
        ...

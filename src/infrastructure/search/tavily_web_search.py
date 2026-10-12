import asyncio
from typing import Any

import httpx

from src.domain.errors import ServiceUnavailableError, UpstreamServiceError
from src.domain.ports.web_search import WebSearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
BACKEND = "tavily"
MAX_RESULTS_PER_QUERY = 5


class TavilyWebSearch:
    """Basic Tavily search: titles, links, and the excerpt Tavily returns. No page is opened."""

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, queries: list[str]) -> list[WebSearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            per_query = await asyncio.gather(*(self._search_one(client, query) for query in queries))
        return [result for results in per_query for result in results]

    async def _search_one(self, client: httpx.AsyncClient, query: str) -> list[WebSearchResult]:
        try:
            response = await client.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": MAX_RESULTS_PER_QUERY,
                },
            )
        except httpx.RequestError as exc:
            raise ServiceUnavailableError(f"{BACKEND} unavailable: {exc}") from exc
        if response.status_code >= 400:
            raise UpstreamServiceError(
                status_code=response.status_code,
                backend=BACKEND,
                body=_error_body(response),
            )
        try:
            items = response.json()["results"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamServiceError(
                status_code=502,
                backend=BACKEND,
                body={"error": "Tavily returned an unreadable search reply"},
            ) from exc
        return [
            WebSearchResult(
                query=query,
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                text=str(item.get("content") or ""),
            )
            for item in items
            if isinstance(item, dict)
        ]


def _error_body(response: httpx.Response) -> Any:
    # Tavily 的錯誤是 {"detail": {"error": "..."}}，攤平成上游失敗格式讀得到的樣子。
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return {"error": detail["error"]}
    if isinstance(detail, str):
        return {"error": detail}
    return response.text

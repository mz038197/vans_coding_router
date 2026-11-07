import asyncio
from typing import Any

import httpx

from src.domain.errors import ServiceUnavailableError, UpstreamServiceError
from src.domain.ports.web_search import WebSearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
BACKEND_NAME = "tavily"
MAX_RESULTS_PER_QUERY = 5


class TavilyWebSearch:
    """Basic Tavily search: titles, links, and the excerpt Tavily returns. No page is opened."""

    def __init__(
        self,
        api_key: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def search(self, queries: list[str]) -> list[WebSearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            tasks = [asyncio.ensure_future(self._search_one(client, query)) for query in queries]
            try:
                per_query = await asyncio.gather(*tasks)
            except BaseException:
                # One query failed: stop the others before the client closes under them.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
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
            raise ServiceUnavailableError(f"{BACKEND_NAME} unavailable: {_unreachable_reason(exc)}") from exc
        if response.status_code >= 400:
            raise UpstreamServiceError(
                status_code=response.status_code,
                backend=BACKEND_NAME,
                body=_error_body(response),
            )
        try:
            items = response.json()["results"]
        except (ValueError, KeyError, TypeError):
            items = None
        if not isinstance(items, list):
            raise UpstreamServiceError(
                status_code=502,
                backend=BACKEND_NAME,
                body={"error": "Tavily returned an unreadable search reply"},
            )
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


def _unreachable_reason(exc: httpx.RequestError) -> str:
    # httpx timeouts usually carry no message of their own.
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    return str(exc) or type(exc).__name__


def _error_body(response: httpx.Response) -> Any:
    # Tavily reports errors as {"detail": {"error": "..."}}; flatten that into what the upstream-failure shape reads.
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return {"error": detail["error"]}
    if isinstance(detail, str):
        return {"error": detail}
    return response.text

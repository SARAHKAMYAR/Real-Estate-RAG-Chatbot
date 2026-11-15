"""Optional web search, restricted to configured public authorities by default."""

from urllib.parse import urlsplit

from app.config import get_settings
from app.sources import is_safe_url
from app.tools import ToolError, WebSearch


class TavilyWebSearch:
    def __init__(
        self, api_key: str, max_results: int, allowed_domains: list[str], timeout: float
    ) -> None:
        from tavily import TavilyClient

        self._client = TavilyClient(api_key=api_key)
        self._max_results = max_results
        self._domains = [domain.lower().strip().rstrip(".") for domain in allowed_domains]
        self._timeout = timeout

    def __call__(self, query: str) -> list[dict]:
        if len(query) > 2000:
            raise ToolError("Search query is too long.")
        try:
            response = self._client.search(
                query=query,
                max_results=self._max_results,
                search_depth="basic",
                include_domains=self._domains or None,
                timeout=self._timeout,
            )
        except Exception as exc:
            # Provider exception text can include request content; do not echo it to the model.
            raise ToolError("Web search is temporarily unavailable.") from exc
        results = []
        for result in response.get("results", []):
            url = result.get("url", "")
            if not is_safe_url(url):
                continue
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
            if self._domains and not any(
                host == d or host.endswith("." + d) for d in self._domains
            ):
                continue
            results.append(
                {
                    "title": str(result.get("title") or "")[:300],
                    "url": url,
                    "content": str(result.get("content") or "")[:6000],
                }
            )
        return results[: self._max_results]


def get_web_search() -> WebSearch | None:
    settings = get_settings()
    if not settings.tavily_api_key:
        return None
    return TavilyWebSearch(
        settings.tavily_api_key,
        settings.web_max_results,
        settings.web_allowed_domains,
        settings.provider_timeout_seconds,
    )

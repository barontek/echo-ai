import asyncio
import logging
import os
import re
from datetime import date, timedelta
from typing import Any

import httpx

from .base import BaseSearchProvider

logger = logging.getLogger(__name__)

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
NEWS_SEARCH_URL = "https://api.search.brave.com/res/v1/news/search"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _age_label(age: str | None) -> str:
    if not age:
        return ""
    age = age.strip().lower()
    if re.match(r"^\d+h$", age):
        return f"[{age}]"
    if re.match(r"^\d+d$", age):
        return f"[{age}]"
    if re.match(r"^\d+m$", age):
        return f"[{age}]"
    if age in ("just now", "now"):
        return "[now]"
    return f"[{age}]"


def _freshness(query: str) -> str | None:
    today = date.today()
    low = query.lower()

    m = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        low,
    )
    if m:
        day = int(m.group(2))
        year = int(m.group(3))
        start = date(year, MONTH_NAMES[m.group(1)], day)
        end = start + timedelta(days=7)
        if end > today:
            end = today
        return f"{start.isoformat()}to{end.isoformat()}"

    m = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+(\d{4})",
        low,
    )
    if m:
        year = int(m.group(2))
        month = MONTH_NAMES[m.group(1)]
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        if end > today:
            end = today
        return f"{start.isoformat()}to{end.isoformat()}"

    m = re.search(r"\b(20\d{2})\b", low)
    if m:
        year = int(m.group(1))
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        if end > today:
            end = today
        return f"{start.isoformat()}to{end.isoformat()}"

    return None


class BraveSearchProvider(BaseSearchProvider):
    """Brave Search API provider."""

    def __init__(self):
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY environment variable not set")

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        try:
            timeout = httpx.Timeout(15.0, connect=5.0, read=10.0)

            params: dict[str, str | int] = {
                "q": query,
                "count": max_results,
                "extra_snippets": "true",
            }

            freshness = _freshness(query)
            if freshness:
                params["freshness"] = freshness

            headers = {
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            }

            async def _search(url: str) -> dict[str, Any]:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    return resp.json()

            web_task = _search(WEB_SEARCH_URL)
            news_task = _search(NEWS_SEARCH_URL)
            web_data, news_data = await asyncio.gather(web_task, news_task)

            seen_urls: set[str] = set()
            results: list[dict[str, Any]] = []

            def extract_news(r: dict[str, Any]) -> dict[str, Any]:
                snippet = _strip_html(r.get("description", ""))
                extra = r.get("extra_snippets")
                if extra:
                    extra_text = "\n".join(_strip_html(s) for s in extra)
                    snippet += "\n" + extra_text
                label = _age_label(r.get("age"))
                if label:
                    snippet = f"{label} {snippet}"
                return {
                    "title": _strip_html(r.get("title", "")),
                    "url": r.get("url", ""),
                    "snippet": snippet.strip(),
                }

            # News results first
            for r in news_data.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(extract_news(r))

            # Web results second (deduplicated)
            for r in web_data.get("web", {}).get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    snippet = _strip_html(r.get("description", ""))
                    extra = r.get("extra_snippets")
                    if extra:
                        extra_text = "\n".join(_strip_html(s) for s in extra)
                        snippet += "\n" + extra_text
                    results.append({
                        "title": _strip_html(r.get("title", "")),
                        "url": url,
                        "snippet": snippet.strip(),
                    })

            return results[:max_results]
        except asyncio.TimeoutError:
            raise RuntimeError("Brave search timed out after 15s")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Brave search returned {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Brave search request failed: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Brave search failed: {e}") from e

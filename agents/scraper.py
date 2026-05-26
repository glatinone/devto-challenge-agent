"""
ScraperAgent: Evening scrape — collect current reaction/comment counts for today's articles.

No LLM. Sets state.performance_metrics.
Sister to ReconAgent but focused on metrics capture, not angle analysis.
"""

import os
from datetime import datetime, timezone

import requests

from core.state import PerformanceMetrics, PipelineState

_DEVTO_API_BASE = "https://dev.to/api"
_PER_PAGE = 100
_TOP_DAYS = 1  # only articles from the last 24 hours


def _derive_tag(challenge_url: str) -> str:
    return challenge_url.rstrip("/").split("/")[-1]


def _build_headers(api_key) -> dict:
    headers = {"Accept": "application/vnd.forem.api-v1+json"}
    if api_key:
        headers["api-key"] = api_key
    return headers


def _fetch_recent_articles(tag: str, api_key) -> list[dict]:
    params = {"tag": tag, "per_page": _PER_PAGE, "top": _TOP_DAYS}
    response = requests.get(
        f"{_DEVTO_API_BASE}/articles",
        params=params,
        headers=_build_headers(api_key),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _parse_metrics(raw: dict) -> PerformanceMetrics:
    return PerformanceMetrics(
        article_url=raw.get("url", ""),
        title=raw.get("title", ""),
        author=raw.get("user", {}).get("username", "unknown"),
        reactions=raw.get("positive_reactions_count", 0),
        comments_count=raw.get("comments_count", 0),
        captured_at=datetime.now(timezone.utc).isoformat(),
    )


def run(state: PipelineState) -> PipelineState:
    challenge_url = os.getenv("DEVTO_CHALLENGE_URL", "").strip()
    if not challenge_url:
        state.add_error("ScraperAgent", "DEVTO_CHALLENGE_URL is not set")
        return state

    api_key = os.getenv("DEVTO_API_KEY", "").strip() or None
    tag = _derive_tag(challenge_url)

    try:
        raw_articles = _fetch_recent_articles(tag, api_key)
    except requests.HTTPError as exc:
        state.add_error("ScraperAgent", f"HTTP error scraping feed: {exc}")
        return state
    except requests.RequestException as exc:
        state.add_error("ScraperAgent", f"Network error scraping feed: {exc}")
        return state

    metrics = []
    for raw in raw_articles:
        try:
            metrics.append(_parse_metrics(raw))
        except Exception as exc:
            state.add_error(
                "ScraperAgent", f"Skipped article '{raw.get('title')}': {exc}"
            )

    state.performance_metrics = metrics
    return state

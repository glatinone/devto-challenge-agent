"""
ReconAgent: Fetch top articles from a dev.to challenge feed.

No LLM calls. Pure HTTP + parsing. Stores results in state.articles
and persists a raw JSON snapshot to data/feed/feed_YYYY-MM-DD.json.
"""

import json
import os
from datetime import date, datetime, timezone
from typing import Optional

import requests

from core.github_client import GitHubClient
from core.state import Article, PipelineState

# --- Module-level config (tune here, not scattered in logic) ---
_DEFAULT_PER_PAGE = 50
_DEFAULT_TOP_DAYS = 7
_DEVTO_API_BASE = "https://dev.to/api"


# ---------------------------------------------------------------------------
# Internal helpers (testable without network)
# ---------------------------------------------------------------------------

def _derive_tag(challenge_url: str) -> str:
    """Extract the challenge tag from the challenge URL.

    Assumes: https://dev.to/challenges/{tag}
    e.g. https://dev.to/challenges/ai -> "ai"
    """
    return challenge_url.rstrip("/").split("/")[-1]


def _build_headers(api_key: Optional[str]) -> dict:
    headers = {"Accept": "application/vnd.forem.api-v1+json"}
    if api_key:
        headers["api-key"] = api_key
    return headers


def _fetch_articles(
    tag: str,
    per_page: int,
    top_days: int,
    api_key: Optional[str],
) -> list[dict]:
    """Fetch articles from dev.to API. Returns raw API response dicts."""
    params = {
        "tag": tag,
        "per_page": per_page,
        "top": top_days,
    }
    response = requests.get(
        f"{_DEVTO_API_BASE}/articles",
        params=params,
        headers=_build_headers(api_key),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _parse_article(raw: dict) -> Article:
    """Map a raw dev.to API article dict to an Article model."""
    return Article(
        title=raw.get("title", ""),
        url=raw.get("url", ""),
        author=raw.get("user", {}).get("username", "unknown"),
        tags=raw.get("tag_list", []),
        reactions=raw.get("positive_reactions_count", 0),
        comments_count=raw.get("comments_count", 0),
        reading_time_minutes=raw.get("reading_time_minutes", 0),
        published_at=raw.get("published_at", ""),
        description=raw.get("description"),
    )


def _build_feed_path(run_date: date) -> str:
    return f"data/feed/feed_{run_date.isoformat()}.json"


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run(state: PipelineState) -> PipelineState:
    challenge_url = os.getenv("DEVTO_CHALLENGE_URL", "").strip()
    if not challenge_url:
        state.add_error("ReconAgent", "DEVTO_CHALLENGE_URL is not set")
        return state

    api_key = os.getenv("DEVTO_API_KEY", "").strip() or None
    tag = _derive_tag(challenge_url)

    # --- Fetch ---
    try:
        raw_articles = _fetch_articles(
            tag=tag,
            per_page=_DEFAULT_PER_PAGE,
            top_days=_DEFAULT_TOP_DAYS,
            api_key=api_key,
        )
    except requests.HTTPError as exc:
        state.add_error("ReconAgent", f"HTTP error fetching feed: {exc}")
        return state
    except requests.RequestException as exc:
        state.add_error("ReconAgent", f"Network error fetching feed: {exc}")
        return state

    if not raw_articles:
        state.add_error("ReconAgent", f"No articles found for tag '{tag}'")
        return state

    # --- Parse ---
    articles: list[Article] = []
    for raw in raw_articles:
        try:
            articles.append(_parse_article(raw))
        except Exception as exc:
            # Skip malformed articles, don't abort the run
            state.add_error("ReconAgent", f"Skipped article '{raw.get('title')}': {exc}")

    if not articles:
        state.add_error("ReconAgent", "All articles failed to parse")
        return state

    state.articles = articles

    # --- Persist feed snapshot to GitHub ---
    run_date = state.run_date or date.today()
    feed_path = _build_feed_path(run_date)
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "challenge_url": challenge_url,
        "article_count": len(raw_articles),
        "articles": raw_articles,
    }

    try:
        gh = GitHubClient()
        gh.commit_file(
            path=feed_path,
            content=json.dumps(snapshot, indent=2, ensure_ascii=False),
            message=f"data: feed snapshot {run_date.isoformat()} ({len(articles)} articles)",
        )
    except Exception as exc:
        # Non-fatal: pipeline can continue without the snapshot
        state.add_error("ReconAgent", f"Failed to persist feed snapshot: {exc}")

    return state

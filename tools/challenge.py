"""
Challenge tools: discover open challenges, fetch article feeds and metrics.
"""

import os
import re
from typing import Optional

import requests

_CHALLENGES_URL = "https://dev.to/challenges"
_API_BASE = "https://dev.to/api"
_HEADERS = {"User-Agent": "devto-challenge-agent/1.0"}
_SLUG_BLOCKLIST = {"terms", "privacy", "contact", "rules", "faq", "about"}


def _api_headers() -> dict:
    h = dict(_HEADERS)
    key = os.getenv("DEVTO_API_KEY", "").strip()
    if key:
        h["api-key"] = key
    return h


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=15, headers=_HEADERS)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def _extract_slugs(html: str) -> list[str]:
    raw = re.findall(r'href=["\']?/challenges/([a-z0-9][a-z0-9-]*)', html)
    seen: set[str] = set()
    result = []
    for s in raw:
        if s not in seen and s not in _SLUG_BLOCKLIST:
            seen.add(s)
            result.append(s)
    return result


def _is_open(html: str) -> bool:
    lower = html.lower()
    closed = ["submissions closed", "challenge is closed", "no longer accepting",
              "submission period has ended", "challenge has ended"]
    return not any(m in lower for m in closed)


def _extract_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1).split("|")[0].strip() if m else "Unknown Challenge"


# ── Tool functions (called by the agent) ──────────────────────────────────

def discover_open_challenge() -> str:
    """Scrape dev.to/challenges and return the first open challenge URL and title."""
    html = _fetch(_CHALLENGES_URL)
    if not html:
        return "Error: Could not reach dev.to/challenges"

    slugs = _extract_slugs(html)
    if not slugs:
        return "No challenge links found on dev.to/challenges"

    for slug in slugs[:8]:
        url = f"https://dev.to/challenges/{slug}"
        page = _fetch(url)
        if page and _is_open(page):
            title = _extract_title(page)
            return f"Open challenge found: '{title}' at {url}"

    return "No open challenges found — all appear closed"


def fetch_challenge_feed(challenge_url: str, per_page: int = 50) -> str:
    """Fetch top articles from the challenge feed (last 7 days by reactions)."""
    tag = challenge_url.rstrip("/").split("/")[-1]
    try:
        r = requests.get(
            f"{_API_BASE}/articles",
            params={"tag": tag, "per_page": per_page, "top": 7},
            headers=_api_headers(),
            timeout=15,
        )
        r.raise_for_status()
        articles = r.json()
    except requests.RequestException as exc:
        return f"Error fetching feed: {exc}"

    if not articles:
        return f"No articles found for tag '{tag}'"

    lines = [f"Found {len(articles)} articles in '{tag}' challenge feed:\n"]
    for i, a in enumerate(articles[:30], 1):
        tags = ", ".join(a.get("tag_list", [])[:4])
        lines.append(
            f'{i}. "{a["title"]}" by @{a["user"]["username"]} — '
            f'{a["positive_reactions_count"]} reactions, '
            f'{a["comments_count"]} comments, '
            f'{a["reading_time_minutes"]} min read\n'
            f"   Tags: [{tags}]"
        )
    return "\n".join(lines)


def fetch_today_metrics(challenge_url: str) -> str:
    """Fetch articles published in the last 24 hours with their current metrics."""
    tag = challenge_url.rstrip("/").split("/")[-1]
    try:
        r = requests.get(
            f"{_API_BASE}/articles",
            params={"tag": tag, "per_page": 100, "top": 1},
            headers=_api_headers(),
            timeout=15,
        )
        r.raise_for_status()
        articles = r.json()
    except requests.RequestException as exc:
        return f"Error fetching metrics: {exc}"

    if not articles:
        return "No articles published today"

    by_reactions = sorted(articles, key=lambda a: a["positive_reactions_count"], reverse=True)
    lines = [f"Today's {len(articles)} articles (sorted by reactions):\n"]
    for i, a in enumerate(by_reactions[:30], 1):
        lines.append(
            f'{i}. "{a["title"]}" by @{a["user"]["username"]} — '
            f'{a["positive_reactions_count"]} reactions, {a["comments_count"]} comments'
        )
    return "\n".join(lines)

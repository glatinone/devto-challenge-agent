"""
Challenge tools: discover open challenges, fetch article feeds and metrics.
"""

import os
import re
from typing import Optional

import requests

_CHALLENGES_URL = "https://dev.to/challenges"
_API_BASE = "https://dev.to/api"
# Browser-like UA — plain Python UA gets blocked or gets a stripped response
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_SLUG_BLOCKLIST = {"terms", "privacy", "contact", "rules", "faq", "about", "challenges"}


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
    """
    Extract challenge slugs from anywhere in the page source —
    href attributes, JSON script tags, data-props, JS bundles, all of it.
    Forem (dev.to) may embed challenge data as JSON inside <script> tags
    rather than as plain <a href> links, so we search the whole document.
    """
    raw = re.findall(r'["\'/]challenges/([a-z0-9][a-z0-9-]{2,})', html)
    seen: set[str] = set()
    result = []
    for s in raw:
        if s not in seen and s not in _SLUG_BLOCKLIST:
            seen.add(s)
            result.append(s)
    return result


def _discover_via_devteam_api() -> list[str]:
    """
    Fallback: fetch full bodies of recent devteam announcement articles and
    extract /challenges/<slug> links from them.

    Why full bodies: the listing endpoint (/api/articles?username=devteam)
    does NOT include body_html — it must be fetched per article via
    /api/articles/{id}. Challenge announcement posts always link to the
    challenge page in their body.
    """
    try:
        r = requests.get(
            f"{_API_BASE}/articles",
            params={"username": "devteam", "per_page": 20},
            headers=_api_headers(),
            timeout=15,
        )
        r.raise_for_status()
        articles = r.json()
    except requests.RequestException:
        return []

    slugs: list[str] = []
    for article in articles:
        title = article.get("title", "").lower()
        # Only bother fetching full body for challenge-related posts
        if not any(w in title for w in ("challenge", "hackathon", "contest", "writing")):
            continue

        article_id = article.get("id")
        if not article_id:
            continue

        try:
            r2 = requests.get(
                f"{_API_BASE}/articles/{article_id}",
                headers=_api_headers(),
                timeout=15,
            )
            r2.raise_for_status()
            body = r2.json().get("body_html", "") or ""
        except requests.RequestException:
            continue

        found = re.findall(r'["\'/]challenges/([a-z0-9][a-z0-9-]{2,})', body)
        for s in found:
            if s not in _SLUG_BLOCKLIST and s not in slugs:
                slugs.append(s)

    return slugs


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
    """
    Autonomously find the currently open dev.to challenge.

    Strategy (in order):
    1. Scrape dev.to/challenges — search the entire page source for
       /challenges/<slug> patterns (covers href, JSON blobs, data-props, etc.)
    2. Fallback: scan recent devteam articles via API for challenge announcements
    3. Probe each candidate URL and confirm it's not closed
    """
    import sys
    print("[discover v4] starting challenge discovery", flush=True)

    # ── 1. Scrape challenges page ──────────────────────────────────────────
    html = _fetch(_CHALLENGES_URL)
    print(f"[discover v4] challenges page: {len(html) if html else 0} bytes", flush=True)

    slugs: list[str] = []
    if html:
        slugs = _extract_slugs(html)
    print(f"[discover v4] slugs from page HTML: {slugs}", flush=True)

    # ── 2. Fallback: devteam article API ──────────────────────────────────
    if not slugs:
        print("[discover v4] falling back to devteam API", flush=True)
        slugs = _discover_via_devteam_api()
        print(f"[discover v4] slugs from devteam API: {slugs}", flush=True)

    if not slugs:
        return (
            "DISCOVERY FAILED: no challenge slugs found via page scrape "
            "or devteam API. Both strategies returned empty."
        )

    # ── 3. Probe candidates and confirm open ──────────────────────────────
    for slug in slugs[:10]:
        url = f"https://dev.to/challenges/{slug}"
        page = _fetch(url)
        open_status = _is_open(page) if page else False
        print(f"[discover v4] probing {slug}: page={len(page) if page else 0}b open={open_status}", flush=True)
        if page and open_status:
            title = _extract_title(page)
            return f"Open challenge found: '{title}' at {url}"

    return "No open challenges found — all candidate pages appear closed"


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

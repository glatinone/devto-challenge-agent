"""
Challenge tools: discover open challenges, fetch article feeds and metrics.
"""

import os
import re
from typing import Optional

import requests

_CHALLENGES_URL = "https://dev.to/challenges"
_API_BASE = "https://dev.to/api"
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

# Keep old name as alias so existing tests don't break
discover_open_challenge = None  # replaced below after definition


def _api_headers() -> dict:
    h = {"User-Agent": _HEADERS["User-Agent"], "Accept": "application/json"}
    key = os.getenv("DEVTO_API_KEY", "").strip()
    if key:
        h["api-key"] = key
    return h


def _fetch_html(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=15, headers=_HEADERS)
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None


def _is_open(html: str) -> bool:
    lower = html.lower()
    closed = [
        "submissions closed", "challenge is closed", "no longer accepting",
        "submission period has ended", "challenge has ended",
    ]
    return not any(m in lower for m in closed)


def _extract_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1).split("|")[0].strip() if m else "Unknown Challenge"


def _slugs_from_text(text: str) -> list[str]:
    raw = re.findall(r'["\'/]challenges/([a-z0-9][a-z0-9-]{2,})', text)
    seen: set[str] = set()
    result = []
    for s in raw:
        if s not in seen and s not in _SLUG_BLOCKLIST:
            seen.add(s)
            result.append(s)
    return result


def _probe_slug(slug: str) -> Optional[tuple[str, str]]:
    """Return (url, title) if slug points to an open challenge, else None."""
    url = f"https://dev.to/challenges/{slug}"
    page = _fetch_html(url)
    if page and _is_open(page):
        return url, _extract_title(page)
    return None


# ── Tool function ─────────────────────────────────────────────────────────

def find_current_challenge() -> str:
    """
    Autonomously find the currently active dev.to challenge.

    Three-stage strategy:
    1. Scrape dev.to/challenges page — works if any SSR content is present
    2. Query devteam's 50 most recent articles via API and fetch full bodies
       for challenge-related posts (challenge announcements ALWAYS link to
       the /challenges/<slug> page in their body)
    3. Probe each found slug to confirm the page is still open

    Returns a string like:
      "Active challenge: 'Title' at https://dev.to/challenges/slug"
    or a descriptive failure message.
    """
    print("[challenge] find_current_challenge v5 — starting", flush=True)

    slugs: list[str] = []

    # ── Stage 1: challenges listing page (may be JS-rendered) ─────────────
    html = _fetch_html(_CHALLENGES_URL)
    print(f"[challenge] stage1 page: {len(html) if html else 0} bytes", flush=True)
    if html:
        slugs = _slugs_from_text(html)
    print(f"[challenge] stage1 slugs: {slugs}", flush=True)

    # ── Stage 2: devteam API — fetch full bodies of recent articles ────────
    if not slugs:
        print("[challenge] stage2: querying devteam API", flush=True)
        try:
            r = requests.get(
                f"{_API_BASE}/articles",
                params={"username": "devteam", "per_page": 50},
                headers=_api_headers(),
                timeout=15,
            )
            r.raise_for_status()
            articles = r.json()
            print(f"[challenge] stage2: got {len(articles)} devteam articles", flush=True)
        except requests.RequestException as exc:
            articles = []
            print(f"[challenge] stage2 API error: {exc}", flush=True)

        for article in articles:
            url_slug = article.get("url", "").lower()
            title = article.get("title", "").lower()
            # Any article that looks challenge-related
            if not any(w in url_slug or w in title
                       for w in ("challenge", "hackathon", "contest")):
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
                found = _slugs_from_text(body)
                print(f"[challenge] stage2 article '{article.get('title','')}': {found}", flush=True)
                for s in found:
                    if s not in slugs:
                        slugs.append(s)
            except requests.RequestException:
                continue

    print(f"[challenge] total candidate slugs: {slugs}", flush=True)

    if not slugs:
        return (
            "Challenge discovery failed: dev.to/challenges is JS-rendered "
            "and no challenge links found in recent devteam articles. "
            "Check https://dev.to/challenges manually and retry."
        )

    # ── Stage 3: probe each candidate ────────────────────────────────────
    for slug in slugs[:10]:
        result = _probe_slug(slug)
        if result:
            url, title = result
            print(f"[challenge] found open: {url}", flush=True)
            return f"Active challenge: '{title}' at {url}"

    return "No open challenges found — all candidate pages appear closed or inaccessible"


# Keep the old name pointing to the new function so nothing breaks
discover_open_challenge = find_current_challenge


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

    by_reactions = sorted(
        articles, key=lambda a: a["positive_reactions_count"], reverse=True
    )
    lines = [f"Today's {len(articles)} articles (sorted by reactions):\n"]
    for i, a in enumerate(by_reactions[:30], 1):
        lines.append(
            f'{i}. "{a["title"]}" by @{a["user"]["username"]} — '
            f'{a["positive_reactions_count"]} reactions, {a["comments_count"]} comments'
        )
    return "\n".join(lines)

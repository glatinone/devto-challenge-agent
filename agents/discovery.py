"""
DiscoveryAgent: Find the currently open dev.to challenge autonomously.

No LLM. Scrapes https://dev.to/challenges listing, checks each challenge
page for open status, and persists the result to data/challenge.json.

This is the first agent in both pipelines — it replaces the need for a
manually-set DEVTO_CHALLENGE_URL environment variable.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from core.github_client import GitHubClient
from core.state import PipelineState

_CHALLENGES_LISTING_URL = "https://dev.to/challenges"
_CHALLENGE_STORAGE_PATH = "data/challenge.json"
_MAX_CHALLENGES_TO_CHECK = 8
_REQUEST_HEADERS = {"User-Agent": "devto-challenge-agent/1.0"}

# Slugs that appear in /challenges/* URLs but are not actual challenges
_SLUG_BLOCKLIST = {"terms", "privacy", "contact", "rules", "faq", "about"}


def _extract_challenge_slugs(html: str) -> list[str]:
    """Extract unique challenge slugs from the dev.to/challenges listing page."""
    raw = re.findall(r'href=["\']?/challenges/([a-z0-9][a-z0-9-]*)', html)
    seen: set[str] = set()
    unique: list[str] = []
    for slug in raw:
        if slug not in seen and slug not in _SLUG_BLOCKLIST:
            seen.add(slug)
            unique.append(slug)
    return unique


def _fetch_html(url: str) -> Optional[str]:
    """Fetch a URL and return HTML. Returns None on any error."""
    try:
        resp = requests.get(url, timeout=15, headers=_REQUEST_HEADERS)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def _is_challenge_open(html: str) -> bool:
    """Re-use MonitorAgent's detection logic."""
    from agents.monitor import _detect_open_status
    return _detect_open_status(html) != "closed"


def _extract_title(html: str) -> str:
    from agents.monitor import _extract_title as _mt
    return _mt(html)


def _load_stored_challenge(gh: GitHubClient) -> Optional[dict]:
    raw = gh.read_file(_CHALLENGE_STORAGE_PATH)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _persist_challenge(gh: GitHubClient, url: str, title: str, is_new: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "url": url,
        "title": title,
        "last_confirmed_at": now,
    }
    action = "new" if is_new else "confirm"
    gh.commit_file(
        path=_CHALLENGE_STORAGE_PATH,
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        message=f"data: {action} challenge — {title[:50]}",
    )


def run(state: PipelineState) -> PipelineState:
    gh = GitHubClient()

    # --- Step 1: Fetch listing ---
    listing_html = _fetch_html(_CHALLENGES_LISTING_URL)

    if not listing_html:
        # Listing unreachable — fall back to stored challenge
        stored = _load_stored_challenge(gh)
        if stored and stored.get("url"):
            state.challenge_url = stored["url"]
            state.challenge_title = stored.get("title", "")
            state.add_error(
                "DiscoveryAgent",
                "dev.to/challenges unreachable — using last stored challenge",
            )
            return state
        state.add_error(
            "DiscoveryAgent",
            "dev.to/challenges unreachable and no stored fallback found",
        )
        return state

    # --- Step 2: Extract and check each challenge ---
    slugs = _extract_challenge_slugs(listing_html)
    if not slugs:
        state.add_error("DiscoveryAgent", "No challenge links found on listing page")
        return state

    for slug in slugs[:_MAX_CHALLENGES_TO_CHECK]:
        url = f"https://dev.to/challenges/{slug}"
        html = _fetch_html(url)
        if not html:
            continue
        if _is_challenge_open(html):
            title = _extract_title(html)
            state.challenge_url = url
            state.challenge_title = title

            # --- Step 3: Persist ---
            try:
                stored = _load_stored_challenge(gh)
                is_new = not stored or stored.get("url") != url
                _persist_challenge(gh, url, title, is_new)
            except Exception as exc:
                state.add_error(
                    "DiscoveryAgent", f"Failed to persist challenge (non-fatal): {exc}"
                )

            return state

    # No open challenges found
    state.add_error(
        "DiscoveryAgent",
        f"Checked {min(len(slugs), _MAX_CHALLENGES_TO_CHECK)} challenges — none are open",
    )
    return state

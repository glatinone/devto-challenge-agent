"""
MonitorAgent: Check whether the dev.to challenge is still active.

No LLM. Pure HTTP + HTML pattern matching. Sets state.challenge_status.
"""

import os
import re
from typing import Optional

import requests

from core.state import ChallengeStatus, PipelineState

_CLOSED_MARKERS = [
    "submissions closed",
    "challenge is closed",
    "no longer accepting",
    "submission period has ended",
    "challenge has ended",
]
_CLOSING_MARKERS = [
    "closing soon",
    "last day",
    "ends tomorrow",
    "final day",
    "one day left",
]


def _detect_open_status(html: str) -> str:
    """Return 'closed', 'closing', or 'open' based on page HTML."""
    lower = html.lower()
    if any(marker in lower for marker in _CLOSED_MARKERS):
        return "closed"
    if any(marker in lower for marker in _CLOSING_MARKERS):
        return "closing"
    return "open"


def _extract_title(html: str) -> str:
    """Best-effort title extraction from <h1> or <title>."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip().split("|")[0].strip()
    return "Unknown Challenge"


def _fetch_challenge_page(url: str) -> str:
    response = requests.get(
        url, timeout=15, headers={"User-Agent": "devto-challenge-agent/1.0"}
    )
    response.raise_for_status()
    return response.text


def _determine_status(
    html: str, previous_status: Optional[ChallengeStatus]
) -> ChallengeStatus:
    raw = _detect_open_status(html)
    if raw == "closed":
        return ChallengeStatus.CLOSED
    if raw == "closing":
        return ChallengeStatus.CLOSING
    if previous_status is None:
        return ChallengeStatus.NEW
    return ChallengeStatus.ACTIVE


def run(state: PipelineState) -> PipelineState:
    challenge_url = state.challenge_url or os.getenv("DEVTO_CHALLENGE_URL", "").strip()
    if not challenge_url:
        state.add_error("MonitorAgent", "No challenge URL in state or DEVTO_CHALLENGE_URL env var")
        return state

    try:
        html = _fetch_challenge_page(challenge_url)
    except requests.HTTPError as exc:
        state.add_error("MonitorAgent", f"HTTP error fetching challenge page: {exc}")
        return state
    except requests.RequestException as exc:
        state.add_error("MonitorAgent", f"Network error fetching challenge page: {exc}")
        return state

    state.challenge_status = _determine_status(html, state.challenge_status)
    state.challenge_title = _extract_title(html)
    state.challenge_url = challenge_url

    return state

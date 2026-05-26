"""Unit tests for ScraperAgent. No network, no LLM."""

from unittest.mock import patch

import pytest

from agents.scraper import _derive_tag, _parse_metrics, run
from core.state import PipelineState

RAW_ARTICLE = {
    "title": "Building Agents in 200 Lines",
    "url": "https://dev.to/kiel/building-agents",
    "user": {"username": "kiel"},
    "positive_reactions_count": 55,
    "comments_count": 12,
}

RAW_MINIMAL = {"title": "Minimal"}


# ── _derive_tag ────────────────────────────────────────────────────────────

def test_derive_tag():
    assert _derive_tag("https://dev.to/challenges/ai") == "ai"


def test_derive_tag_trailing_slash():
    assert _derive_tag("https://dev.to/challenges/pulumi/") == "pulumi"


# ── _parse_metrics ─────────────────────────────────────────────────────────

def test_parse_metrics_full():
    m = _parse_metrics(RAW_ARTICLE)
    assert m.title == "Building Agents in 200 Lines"
    assert m.author == "kiel"
    assert m.reactions == 55
    assert m.comments_count == 12


def test_parse_metrics_minimal():
    m = _parse_metrics(RAW_MINIMAL)
    assert m.title == "Minimal"
    assert m.author == "unknown"
    assert m.reactions == 0


# ── run() ──────────────────────────────────────────────────────────────────

@patch("agents.scraper.requests.get")
@patch("agents.scraper.os.getenv")
def test_run_happy_path(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = [RAW_ARTICLE]

    state = PipelineState()
    result = run(state)

    assert len(result.performance_metrics) == 1
    assert result.performance_metrics[0].reactions == 55
    assert not result.errors


@patch("agents.scraper.os.getenv")
def test_run_missing_env(mock_getenv):
    mock_getenv.side_effect = lambda key, default="": ""
    state = PipelineState()
    result = run(state)
    assert any("DEVTO_CHALLENGE_URL" in e for e in result.errors.get("ScraperAgent", []))


@patch("agents.scraper.requests.get")
@patch("agents.scraper.os.getenv")
def test_run_network_error(mock_getenv, mock_get):
    import requests as req_lib

    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)
    mock_get.side_effect = req_lib.RequestException("timeout")

    state = PipelineState()
    result = run(state)
    assert any("Network error" in e for e in result.errors.get("ScraperAgent", []))

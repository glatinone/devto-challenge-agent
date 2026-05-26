"""Unit tests for ReconAgent. No network, no LLM, no GitHub calls."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from agents.recon import (
    _build_feed_path,
    _derive_tag,
    _parse_article,
    run,
)
from core.state import PipelineState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RAW_ARTICLE = {
    "title": "Building AI Agents with Python",
    "url": "https://dev.to/glatinone/building-ai-agents-123",
    "user": {"username": "glatinone"},
    "tag_list": ["ai", "python", "agents"],
    "positive_reactions_count": 42,
    "comments_count": 7,
    "reading_time_minutes": 8,
    "published_at": "2026-05-26T00:00:00Z",
    "description": "A practical guide to multi-agent systems.",
}

RAW_ARTICLE_MINIMAL = {
    "title": "Minimal Article",
    "url": "https://dev.to/foo/bar",
}


def make_state(**kwargs) -> PipelineState:
    defaults = {
        "challenge_url": "https://dev.to/challenges/ai",
        "run_date": date(2026, 5, 26),
    }
    return PipelineState(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# _derive_tag
# ---------------------------------------------------------------------------

def test_derive_tag_standard():
    assert _derive_tag("https://dev.to/challenges/ai") == "ai"


def test_derive_tag_trailing_slash():
    assert _derive_tag("https://dev.to/challenges/pulumi/") == "pulumi"


def test_derive_tag_multiword_slug():
    assert _derive_tag("https://dev.to/challenges/open-source") == "open-source"


# ---------------------------------------------------------------------------
# _parse_article
# ---------------------------------------------------------------------------

def test_parse_article_full():
    article = _parse_article(RAW_ARTICLE)
    assert article.title == "Building AI Agents with Python"
    assert article.author == "glatinone"
    assert article.reactions == 42
    assert article.tags == ["ai", "python", "agents"]
    assert article.description == "A practical guide to multi-agent systems."


def test_parse_article_minimal_no_crash():
    article = _parse_article(RAW_ARTICLE_MINIMAL)
    assert article.title == "Minimal Article"
    assert article.author == "unknown"
    assert article.reactions == 0
    assert article.tags == []


# ---------------------------------------------------------------------------
# _build_feed_path
# ---------------------------------------------------------------------------

def test_build_feed_path():
    assert _build_feed_path(date(2026, 5, 26)) == "data/feed/feed_2026-05-26.json"


# ---------------------------------------------------------------------------
# run() — happy path
# ---------------------------------------------------------------------------

@patch("agents.recon.requests.get")
@patch("agents.recon.os.getenv")
def test_run_happy_path(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
        "DEVTO_API_KEY": "test-key",
    }.get(key, default)

    mock_response = MagicMock()
    mock_response.json.return_value = [RAW_ARTICLE]
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    state = make_state()

    with patch("agents.recon.GitHubClient") as mock_gh_cls:
        mock_gh_cls.return_value.commit_file.return_value = None
        result = run(state)

    assert len(result.articles) == 1
    assert result.articles[0].title == "Building AI Agents with Python"
    assert not result.errors


# ---------------------------------------------------------------------------
# run() — error cases
# ---------------------------------------------------------------------------

@patch("agents.recon.os.getenv")
def test_run_missing_challenge_url(mock_getenv):
    mock_getenv.side_effect = lambda key, default="": ""
    state = make_state()
    result = run(state)
    assert any("DEVTO_CHALLENGE_URL" in e for e in result.errors.get("ReconAgent", []))


@patch("agents.recon.requests.get")
@patch("agents.recon.os.getenv")
def test_run_empty_response(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    state = make_state()
    result = run(state)
    assert any("No articles found" in e for e in result.errors.get("ReconAgent", []))


@patch("agents.recon.requests.get")
@patch("agents.recon.os.getenv")
def test_run_network_error(mock_getenv, mock_get):
    import requests as req_lib

    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_get.side_effect = req_lib.RequestException("timeout")

    state = make_state()
    result = run(state)
    assert any("Network error" in e for e in result.errors.get("ReconAgent", []))


@patch("agents.recon.requests.get")
@patch("agents.recon.os.getenv")
def test_run_github_commit_failure_is_nonfatal(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_response = MagicMock()
    mock_response.json.return_value = [RAW_ARTICLE]
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    state = make_state()

    with patch("agents.recon.GitHubClient") as mock_gh_cls:
        mock_gh_cls.return_value.commit_file.side_effect = Exception("GitHub 503")
        result = run(state)

    # Articles are populated even if GitHub commit fails
    assert len(result.articles) == 1
    # Error is recorded but pipeline can continue
    assert any("Failed to persist" in e for e in result.errors.get("ReconAgent", []))

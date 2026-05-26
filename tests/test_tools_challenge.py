"""Tests for tools/challenge.py — discover, feed, metrics."""

from unittest.mock import MagicMock, patch

import pytest

from tools.challenge import (
    _extract_slugs,
    _extract_title,
    _is_open,
    discover_open_challenge,
    fetch_challenge_feed,
    fetch_today_metrics,
)

# ── helper extractors ─────────────────────────────────────────────────────


def test_extract_slugs_basic():
    html = '<a href="/challenges/ai">AI</a><a href="/challenges/python">Python</a>'
    assert _extract_slugs(html) == ["ai", "python"]


def test_extract_slugs_deduplicates():
    html = '<a href="/challenges/ai"><a href="/challenges/ai">'
    assert _extract_slugs(html) == ["ai"]


def test_extract_slugs_filters_blocklist():
    html = '<a href="/challenges/terms"><a href="/challenges/ai">'
    assert "terms" not in _extract_slugs(html)
    assert "ai" in _extract_slugs(html)


def test_is_open_true():
    assert _is_open("<p>Submit your entry now!</p>")


def test_is_open_false_when_closed():
    assert not _is_open("<p>Submissions closed.</p>")


def test_extract_title_from_h1():
    html = "<h1>The AI Challenge</h1>"
    assert _extract_title(html) == "The AI Challenge"


def test_extract_title_strips_tags():
    html = "<h1><span>My Challenge</span></h1>"
    assert _extract_title(html) == "My Challenge"


def test_extract_title_fallback_to_page_title():
    html = "<title>Dev.to Challenge | Dev.to</title>"
    assert _extract_title(html) == "Dev.to Challenge"


# ── discover_open_challenge ───────────────────────────────────────────────


@patch("tools.challenge._fetch")
def test_discover_returns_open_challenge(mock_fetch):
    mock_fetch.side_effect = [
        '<a href="/challenges/ai">AI</a>',  # challenges page
        "<h1>AI Challenge 2024</h1><p>Submit now!</p>",  # challenge detail page
    ]
    result = discover_open_challenge()
    assert "AI Challenge 2024" in result
    assert "dev.to/challenges/ai" in result


@patch("tools.challenge._fetch")
def test_discover_skips_closed(mock_fetch):
    mock_fetch.side_effect = [
        '<a href="/challenges/ai"><a href="/challenges/ml">',
        "<h1>Old AI</h1><p>Submissions closed.</p>",  # closed
        "<h1>ML Challenge</h1><p>Submit now!</p>",  # open
    ]
    result = discover_open_challenge()
    assert "ML Challenge" in result


@patch("tools.challenge._fetch")
def test_discover_returns_error_on_network_fail(mock_fetch):
    mock_fetch.return_value = None
    result = discover_open_challenge()
    assert "Error" in result


@patch("tools.challenge._fetch")
def test_discover_returns_message_when_no_slugs(mock_fetch):
    mock_fetch.return_value = "<p>No links here.</p>"
    result = discover_open_challenge()
    assert "No challenge links" in result


# ── fetch_challenge_feed ──────────────────────────────────────────────────


@patch("tools.challenge.requests.get")
def test_fetch_challenge_feed_formats_output(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = [
        {
            "title": "Using Claude for everything",
            "user": {"username": "alice"},
            "positive_reactions_count": 150,
            "comments_count": 12,
            "reading_time_minutes": 5,
            "tag_list": ["ai", "python"],
        }
    ]
    result = fetch_challenge_feed("https://dev.to/challenges/ai")
    assert "Using Claude for everything" in result
    assert "alice" in result
    assert "150 reactions" in result


@patch("tools.challenge.requests.get")
def test_fetch_challenge_feed_uses_tag_from_url(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = []
    fetch_challenge_feed("https://dev.to/challenges/webdev")
    call_kwargs = mock_get.call_args
    assert call_kwargs[1]["params"]["tag"] == "webdev"


@patch("tools.challenge.requests.get")
def test_fetch_challenge_feed_handles_request_error(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("timeout")
    result = fetch_challenge_feed("https://dev.to/challenges/ai")
    assert "Error" in result


# ── fetch_today_metrics ───────────────────────────────────────────────────


@patch("tools.challenge.requests.get")
def test_fetch_today_metrics_sorts_by_reactions(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = [
        {"title": "Low", "user": {"username": "bob"}, "positive_reactions_count": 5, "comments_count": 0},
        {"title": "High", "user": {"username": "alice"}, "positive_reactions_count": 200, "comments_count": 10},
    ]
    result = fetch_today_metrics("https://dev.to/challenges/ai")
    assert result.index("High") < result.index("Low")


@patch("tools.challenge.requests.get")
def test_fetch_today_metrics_handles_empty(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = []
    result = fetch_today_metrics("https://dev.to/challenges/ai")
    assert "No articles" in result

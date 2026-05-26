"""Unit tests for DiscoveryAgent. No network."""

from unittest.mock import MagicMock, call, patch

from agents.discovery import _extract_challenge_slugs, run
from core.state import PipelineState

# ── Fixtures ───────────────────────────────────────────────────────────────

LISTING_HTML = """
<html>
  <a href="/challenges/ai">AI Challenge</a>
  <a href="/challenges/pulumi">Pulumi Challenge</a>
  <a href="/challenges/open-source">Open Source Challenge</a>
  <a href="/challenges/terms">Terms</a>
</html>
"""

OPEN_CHALLENGE_HTML = """
<html>
  <h1>AI Writing Challenge 2026</h1>
  <p>Submit your article by end of June.</p>
</html>
"""

CLOSED_CHALLENGE_HTML = """
<html>
  <h1>Old Challenge</h1>
  <p>Submissions closed.</p>
</html>
"""


# ── _extract_challenge_slugs ───────────────────────────────────────────────

def test_extract_slugs_basic():
    slugs = _extract_challenge_slugs(LISTING_HTML)
    assert "ai" in slugs
    assert "pulumi" in slugs
    assert "open-source" in slugs


def test_extract_slugs_blocklist_filtered():
    slugs = _extract_challenge_slugs(LISTING_HTML)
    assert "terms" not in slugs


def test_extract_slugs_deduplicates():
    html = '<a href="/challenges/ai"></a><a href="/challenges/ai"></a>'
    slugs = _extract_challenge_slugs(html)
    assert slugs.count("ai") == 1


def test_extract_slugs_empty_page():
    assert _extract_challenge_slugs("<html><p>nothing here</p></html>") == []


# ── run() — happy path ─────────────────────────────────────────────────────

@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_finds_open_challenge(mock_fetch, mock_gh_cls):
    mock_fetch.side_effect = [
        LISTING_HTML,           # listing page
        OPEN_CHALLENGE_HTML,    # first challenge (ai) — open
    ]
    mock_gh_cls.return_value.read_file.return_value = None
    mock_gh_cls.return_value.commit_file.return_value = None

    state = PipelineState()
    result = run(state)

    assert result.challenge_url == "https://dev.to/challenges/ai"
    assert result.challenge_title == "AI Writing Challenge 2026"
    assert "DiscoveryAgent" not in result.errors


@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_skips_closed_finds_second(mock_fetch, mock_gh_cls):
    mock_fetch.side_effect = [
        LISTING_HTML,            # listing
        CLOSED_CHALLENGE_HTML,   # ai — closed
        OPEN_CHALLENGE_HTML,     # pulumi — open
    ]
    mock_gh_cls.return_value.read_file.return_value = None
    mock_gh_cls.return_value.commit_file.return_value = None

    state = PipelineState()
    result = run(state)

    assert result.challenge_url == "https://dev.to/challenges/pulumi"


# ── run() — no open challenges ─────────────────────────────────────────────

@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_no_open_challenges(mock_fetch, mock_gh_cls):
    mock_fetch.side_effect = [
        LISTING_HTML,
        CLOSED_CHALLENGE_HTML,  # ai
        CLOSED_CHALLENGE_HTML,  # pulumi
        CLOSED_CHALLENGE_HTML,  # open-source
    ]
    mock_gh_cls.return_value.read_file.return_value = None

    state = PipelineState()
    result = run(state)

    assert result.challenge_url is None
    assert any("none are open" in e for e in result.errors.get("DiscoveryAgent", []))


# ── run() — listing unreachable ────────────────────────────────────────────

@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_listing_fails_uses_stored_fallback(mock_fetch, mock_gh_cls):
    mock_fetch.return_value = None  # all HTTP calls fail

    stored = {"url": "https://dev.to/challenges/ai", "title": "AI Challenge"}
    mock_gh_cls.return_value.read_file.return_value = '{"url": "https://dev.to/challenges/ai", "title": "AI Challenge"}'

    state = PipelineState()
    result = run(state)

    assert result.challenge_url == "https://dev.to/challenges/ai"
    assert any("stored challenge" in e for e in result.errors.get("DiscoveryAgent", []))


@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_listing_fails_no_fallback(mock_fetch, mock_gh_cls):
    mock_fetch.return_value = None
    mock_gh_cls.return_value.read_file.return_value = None

    state = PipelineState()
    result = run(state)

    assert result.challenge_url is None
    assert any("no stored fallback" in e for e in result.errors.get("DiscoveryAgent", []))


# ── run() — commit failure is non-fatal ───────────────────────────────────

@patch("agents.discovery.GitHubClient")
@patch("agents.discovery._fetch_html")
def test_run_persist_failure_is_nonfatal(mock_fetch, mock_gh_cls):
    mock_fetch.side_effect = [LISTING_HTML, OPEN_CHALLENGE_HTML]
    mock_gh_cls.return_value.read_file.return_value = None
    mock_gh_cls.return_value.commit_file.side_effect = Exception("GitHub 503")

    state = PipelineState()
    result = run(state)

    # Challenge URL still set even if persist failed
    assert result.challenge_url == "https://dev.to/challenges/ai"
    assert any("non-fatal" in e for e in result.errors.get("DiscoveryAgent", []))

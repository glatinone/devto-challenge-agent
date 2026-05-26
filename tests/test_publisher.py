"""Unit tests for PublishAgent. No network, no real dev.to API calls."""

import json
from unittest.mock import MagicMock, patch

from agents.publisher import (
    _already_published,
    _extract_draft_path,
    _parse_frontmatter,
    run,
)
from core.state import PipelineState

# ── Fixtures ───────────────────────────────────────────────────────────────

ISSUE_BODY = """\
## Article Draft Ready for Review

**Title:** Why Your AI Pipeline Is Lying to You
**Draft file:** `drafts/draft_2026-05-26.md`

Close this issue to approve.
"""

DRAFT_CONTENT = """\
---
title: Why Your AI Pipeline Is Lying to You
tags: ai, python, agents, debugging
---

I built an agent last month that confidently told me everything was fine.
It was not fine.
"""

DEVTO_API_RESPONSE = {
    "id": 123456,
    "url": "https://dev.to/glatinone/why-your-ai-pipeline-is-lying-123",
    "title": "Why Your AI Pipeline Is Lying to You",
}


def make_env(api_key="test-key", issue_body=ISSUE_BODY):
    return {
        "DEVTO_API_KEY": api_key,
        "ISSUE_BODY": issue_body,
        "GITHUB_TOKEN": "ghp_test",
        "GITHUB_REPOSITORY": "glatinone/devto-challenge-agent",
    }


# ── _extract_draft_path ────────────────────────────────────────────────────

def test_extract_draft_path_standard():
    assert _extract_draft_path(ISSUE_BODY) == "drafts/draft_2026-05-26.md"


def test_extract_draft_path_missing():
    assert _extract_draft_path("No draft path here") is None


# ── _parse_frontmatter ─────────────────────────────────────────────────────

def test_parse_frontmatter_full():
    title, tags, body = _parse_frontmatter(DRAFT_CONTENT)
    assert title == "Why Your AI Pipeline Is Lying to You"
    assert tags == ["ai", "python", "agents", "debugging"]
    assert "confidently" in body


def test_parse_frontmatter_no_yaml():
    title, tags, body = _parse_frontmatter("Just a plain body with no frontmatter")
    assert title == ""
    assert tags == []
    assert "plain body" in body


def test_parse_frontmatter_max_four_tags():
    content = "---\ntitle: Test\ntags: a, b, c, d, e\n---\nbody"
    _, tags, _ = _parse_frontmatter(content)
    assert len(tags) == 5  # _parse_frontmatter returns all; publisher truncates to 4


# ── _already_published ─────────────────────────────────────────────────────

def test_already_published_true():
    log = json.dumps([{"draft_path": "drafts/draft_2026-05-26.md", "title": "X"}])
    gh = MagicMock()
    gh.read_file.return_value = log
    assert _already_published(gh, "drafts/draft_2026-05-26.md") is True


def test_already_published_false():
    gh = MagicMock()
    gh.read_file.return_value = None
    assert _already_published(gh, "drafts/draft_2026-05-26.md") is False


def test_already_published_corrupted_log():
    gh = MagicMock()
    gh.read_file.return_value = "not json"
    assert _already_published(gh, "drafts/draft_2026-05-26.md") is False


# ── run() — happy path ─────────────────────────────────────────────────────

@patch("agents.publisher.requests.post")
@patch("agents.publisher.GitHubClient")
@patch("agents.publisher.os.getenv")
def test_run_happy_path(mock_getenv, mock_gh_cls, mock_post):
    mock_getenv.side_effect = lambda k, d="": make_env().get(k, d)

    gh = mock_gh_cls.return_value
    # 1st read: published log check (None = not published)
    # 2nd read: draft content
    # 3rd read: existing log before appending (None = empty)
    gh.read_file.side_effect = [None, DRAFT_CONTENT, None]
    gh.commit_file.return_value = None

    mock_post.return_value.raise_for_status.return_value = None
    mock_post.return_value.json.return_value = DEVTO_API_RESPONSE

    state = PipelineState()
    result = run(state)

    assert not result.errors
    mock_post.assert_called_once()
    gh.commit_file.assert_called_once()


@patch("agents.publisher.requests.post")
@patch("agents.publisher.GitHubClient")
@patch("agents.publisher.os.getenv")
def test_run_skips_if_already_published(mock_getenv, mock_gh_cls, mock_post):
    mock_getenv.side_effect = lambda k, d="": make_env().get(k, d)

    log = json.dumps([{"draft_path": "drafts/draft_2026-05-26.md"}])
    mock_gh_cls.return_value.read_file.return_value = log

    state = PipelineState()
    result = run(state)

    mock_post.assert_not_called()
    assert any("Already published" in e for e in result.errors.get("PublishAgent", []))


# ── run() — error cases ────────────────────────────────────────────────────

@patch("agents.publisher.os.getenv")
def test_run_missing_api_key(mock_getenv):
    mock_getenv.side_effect = lambda k, d="": make_env(api_key="").get(k, d)
    result = run(PipelineState())
    assert any("DEVTO_API_KEY" in e for e in result.errors.get("PublishAgent", []))


@patch("agents.publisher.os.getenv")
def test_run_missing_issue_body(mock_getenv):
    mock_getenv.side_effect = lambda k, d="": make_env(issue_body="").get(k, d)
    result = run(PipelineState())
    assert any("ISSUE_BODY" in e for e in result.errors.get("PublishAgent", []))


@patch("agents.publisher.GitHubClient")
@patch("agents.publisher.os.getenv")
def test_run_draft_not_found(mock_getenv, mock_gh_cls):
    mock_getenv.side_effect = lambda k, d="": make_env().get(k, d)
    gh = mock_gh_cls.return_value
    gh.read_file.return_value = None  # log empty AND draft empty

    result = run(PipelineState())
    assert any("not found" in e for e in result.errors.get("PublishAgent", []))


@patch("agents.publisher.requests.post")
@patch("agents.publisher.GitHubClient")
@patch("agents.publisher.os.getenv")
def test_run_devto_api_error(mock_getenv, mock_gh_cls, mock_post):
    import requests as req_lib

    mock_getenv.side_effect = lambda k, d="": make_env().get(k, d)
    gh = mock_gh_cls.return_value
    gh.read_file.side_effect = [None, DRAFT_CONTENT]

    mock_post.side_effect = req_lib.HTTPError("422 Unprocessable")

    result = run(PipelineState())
    assert any("API error" in e for e in result.errors.get("PublishAgent", []))


@patch("agents.publisher.requests.post")
@patch("agents.publisher.GitHubClient")
@patch("agents.publisher.os.getenv")
def test_run_log_update_failure_is_nonfatal(mock_getenv, mock_gh_cls, mock_post):
    mock_getenv.side_effect = lambda k, d="": make_env().get(k, d)

    gh = mock_gh_cls.return_value
    gh.read_file.side_effect = [None, DRAFT_CONTENT]
    gh.commit_file.side_effect = Exception("GitHub 503")  # log update fails

    mock_post.return_value.raise_for_status.return_value = None
    mock_post.return_value.json.return_value = DEVTO_API_RESPONSE

    result = run(PipelineState())

    # Article was published — errors contain log failure but not API failure
    mock_post.assert_called_once()
    assert any("IS live" in e for e in result.errors.get("PublishAgent", []))

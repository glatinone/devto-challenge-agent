"""Tests for tools/github_tools.py — review issues, challenge state."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.github_tools import load_challenge_state, request_human_review, save_challenge_state


# ── request_human_review ──────────────────────────────────────────────────


@patch("tools.github_tools.GitHubClient")
def test_request_human_review_creates_issue(MockGH):
    MockGH.return_value.create_issue.return_value = "https://github.com/user/repo/issues/42"
    result = request_human_review(
        draft_path="drafts/draft_2026-05-26_1.md",
        title="Why I Rewrote My Backend in Rust",
        score=32,
        angle="Production migration story with real latency numbers",
        score_breakdown="Creativity: 9, Technical: 8, Writing: 8, Knowledge: 7",
    )
    assert "https://github.com" in result
    assert MockGH.return_value.create_issue.called


@patch("tools.github_tools.GitHubClient")
def test_request_human_review_includes_score_in_body(MockGH):
    MockGH.return_value.create_issue.return_value = "https://github.com/user/repo/issues/1"
    request_human_review("drafts/x.md", "Title", 30, "angle", "breakdown")
    body = MockGH.return_value.create_issue.call_args[1]["body"]
    assert "30/40" in body
    assert "breakdown" in body


@patch("tools.github_tools.GitHubClient")
def test_request_human_review_returns_error_on_exception(MockGH):
    MockGH.return_value.create_issue.side_effect = RuntimeError("GitHub down")
    result = request_human_review("drafts/x.md", "Title", 30, "angle", "breakdown")
    assert "Error" in result


# ── save_challenge_state ──────────────────────────────────────────────────


@patch("tools.github_tools.GitHubClient")
def test_save_challenge_state_commits_json(MockGH):
    MockGH.return_value.commit_file.return_value = None
    result = save_challenge_state(
        challenge_url="https://dev.to/challenges/ai",
        challenge_title="AI Writing Challenge",
    )
    assert "saved" in result.lower()
    call_args = MockGH.return_value.commit_file.call_args
    path = call_args[0][0]
    content = call_args[0][1]
    assert path == "data/challenge.json"
    payload = json.loads(content)
    assert payload["url"] == "https://dev.to/challenges/ai"
    assert payload["title"] == "AI Writing Challenge"
    assert "last_confirmed_at" in payload


@patch("tools.github_tools.GitHubClient")
def test_save_challenge_state_returns_error_on_exception(MockGH):
    MockGH.return_value.commit_file.side_effect = RuntimeError("auth fail")
    result = save_challenge_state("https://dev.to/challenges/ai", "AI")
    assert "Error" in result


# ── load_challenge_state ──────────────────────────────────────────────────


@patch("tools.github_tools.GitHubClient")
def test_load_challenge_state_returns_stored_data(MockGH):
    payload = {"url": "https://dev.to/challenges/ai", "title": "AI Challenge"}
    MockGH.return_value.read_file.return_value = json.dumps(payload)
    result = load_challenge_state()
    assert "AI Challenge" in result
    assert "dev.to/challenges/ai" in result


@patch("tools.github_tools.GitHubClient")
def test_load_challenge_state_handles_missing_file(MockGH):
    MockGH.return_value.read_file.return_value = None
    result = load_challenge_state()
    assert "No stored" in result


@patch("tools.github_tools.GitHubClient")
def test_load_challenge_state_returns_error_on_exception(MockGH):
    MockGH.return_value.read_file.side_effect = RuntimeError("network fail")
    result = load_challenge_state()
    assert "Error" in result

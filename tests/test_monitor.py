"""Unit tests for MonitorAgent. No network, no LLM."""

from unittest.mock import patch

import pytest

from agents.monitor import (
    _detect_open_status,
    _determine_status,
    _extract_title,
    run,
)
from core.state import ChallengeStatus, PipelineState


# ── _detect_open_status ────────────────────────────────────────────────────

def test_detect_closed_by_submissions_closed():
    assert _detect_open_status("Submissions closed for this challenge.") == "closed"


def test_detect_closed_case_insensitive():
    assert _detect_open_status("SUBMISSIONS CLOSED") == "closed"


def test_detect_closing():
    assert _detect_open_status("Challenge closing soon, hurry up!") == "closing"


def test_detect_open():
    assert _detect_open_status("Submit your article by end of month.") == "open"


# ── _determine_status ──────────────────────────────────────────────────────

def test_determine_closed():
    html = "submissions closed"
    assert _determine_status(html, None) == ChallengeStatus.CLOSED


def test_determine_closing():
    html = "challenge closing soon"
    assert _determine_status(html, ChallengeStatus.ACTIVE) == ChallengeStatus.CLOSING


def test_determine_new_when_no_previous_status():
    html = "open for submissions"
    assert _determine_status(html, None) == ChallengeStatus.NEW


def test_determine_active_when_previous_status_exists():
    html = "open for submissions"
    assert _determine_status(html, ChallengeStatus.ACTIVE) == ChallengeStatus.ACTIVE


# ── _extract_title ─────────────────────────────────────────────────────────

def test_extract_title_from_h1():
    html = "<h1>AI Writing Challenge</h1>"
    assert _extract_title(html) == "AI Writing Challenge"


def test_extract_title_from_title_tag():
    html = "<title>Dev.to AI Challenge | Dev.to</title>"
    assert _extract_title(html) == "Dev.to AI Challenge"


def test_extract_title_fallback():
    assert _extract_title("<p>no title here</p>") == "Unknown Challenge"


# ── run() ──────────────────────────────────────────────────────────────────

@patch("agents.monitor.requests.get")
@patch("agents.monitor.os.getenv")
def test_run_happy_path(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<h1>AI Challenge 2026</h1><p>Open for submissions.</p>"

    state = PipelineState()
    result = run(state)

    assert result.challenge_status == ChallengeStatus.NEW
    assert result.challenge_title == "AI Challenge 2026"
    assert not result.errors


@patch("agents.monitor.os.getenv")
def test_run_missing_env(mock_getenv):
    mock_getenv.side_effect = lambda key, default="": ""
    state = PipelineState()
    result = run(state)
    assert any("DEVTO_CHALLENGE_URL" in e for e in result.errors.get("MonitorAgent", []))


@patch("agents.monitor.requests.get")
@patch("agents.monitor.os.getenv")
def test_run_network_error(mock_getenv, mock_get):
    import requests as req_lib

    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)
    mock_get.side_effect = req_lib.RequestException("connection refused")

    state = PipelineState()
    result = run(state)
    assert any("Network error" in e for e in result.errors.get("MonitorAgent", []))


@patch("agents.monitor.requests.get")
@patch("agents.monitor.os.getenv")
def test_run_challenge_closed(mock_getenv, mock_get):
    mock_getenv.side_effect = lambda key, default="": {
        "DEVTO_CHALLENGE_URL": "https://dev.to/challenges/ai",
    }.get(key, default)

    mock_response = mock_get.return_value
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<p>Submissions closed. Thank you for participating.</p>"

    state = PipelineState()
    result = run(state)
    assert result.challenge_status == ChallengeStatus.CLOSED

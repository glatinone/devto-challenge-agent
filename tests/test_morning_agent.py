"""Tests for agents/morning_agent.py — build_tools and run."""

from unittest.mock import MagicMock, patch

import pytest

from agents.morning_agent import build_tools, run
from core.agent_loop import Tool


def test_build_tools_returns_expected_names():
    tools = build_tools()
    names = {t.name for t in tools}
    assert "discover_open_challenge" in names
    assert "save_challenge_state" in names
    assert "fetch_challenge_feed" in names
    assert "read_memory" in names
    assert "write_and_save_draft" in names
    assert "self_judge_draft" in names
    assert "request_human_review" in names
    assert "update_memory" in names


def test_build_tools_all_are_tool_instances():
    for t in build_tools():
        assert isinstance(t, Tool)


def test_build_tools_all_have_callable_func():
    for t in build_tools():
        assert callable(t.func)


@patch("agents.morning_agent.AgentLoop")
def test_run_creates_agent_with_correct_params(MockAgentLoop):
    instance = MockAgentLoop.return_value
    instance.run.return_value = "Done."

    result = run()

    assert MockAgentLoop.called
    kwargs = MockAgentLoop.call_args[1]
    assert kwargs["max_iterations"] == 60
    assert result == "Done."


@patch("agents.morning_agent.AgentLoop")
def test_run_returns_agent_summary(MockAgentLoop):
    MockAgentLoop.return_value.run.return_value = "Published 2 articles."
    assert run() == "Published 2 articles."

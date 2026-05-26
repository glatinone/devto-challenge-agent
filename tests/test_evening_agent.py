"""Tests for agents/evening_agent.py — build_tools and run."""

from unittest.mock import MagicMock, patch

import pytest

from agents.evening_agent import build_tools, run
from core.agent_loop import Tool


def test_build_tools_returns_expected_names():
    tools = build_tools()
    names = {t.name for t in tools}
    assert "load_challenge_state" in names
    assert "fetch_today_metrics" in names
    assert "read_memory" in names
    assert "update_memory" in names


def test_build_tools_all_are_tool_instances():
    for t in build_tools():
        assert isinstance(t, Tool)


def test_build_tools_all_have_callable_func():
    for t in build_tools():
        assert callable(t.func)


@patch("agents.evening_agent.AgentLoop")
def test_run_creates_agent_with_correct_params(MockAgentLoop):
    instance = MockAgentLoop.return_value
    instance.run.return_value = "Analysis done."

    result = run()

    assert MockAgentLoop.called
    kwargs = MockAgentLoop.call_args[1]
    assert kwargs["max_iterations"] == 20
    assert result == "Analysis done."


@patch("agents.evening_agent.AgentLoop")
def test_run_returns_agent_summary(MockAgentLoop):
    MockAgentLoop.return_value.run.return_value = "Memory updated."
    assert run() == "Memory updated."

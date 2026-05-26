"""Tests for core/agent_loop.py — Tool dataclass and AgentLoop engine."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.agent_loop import AgentLoop, Tool, _fmt_args


# ── Tool ──────────────────────────────────────────────────────────────────


def test_tool_execute_returns_string():
    tool = Tool(name="echo", description="echo", parameters={}, func=lambda msg: msg)
    assert tool.execute(msg="hello") == "hello"


def test_tool_execute_converts_non_string():
    tool = Tool(name="num", description="", parameters={}, func=lambda: 42)
    assert tool.execute() == "42"


def test_tool_execute_returns_done_on_none():
    tool = Tool(name="noop", description="", parameters={}, func=lambda: None)
    assert tool.execute() == "Done."


def test_tool_execute_catches_exception():
    def boom():
        raise ValueError("exploded")

    tool = Tool(name="boom", description="", parameters={}, func=boom)
    result = tool.execute()
    assert "Tool error (boom)" in result
    assert "exploded" in result


def test_tool_to_openai():
    params = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    tool = Tool(name="greet", description="Say hi", parameters=params, func=lambda x: x)
    d = tool.to_openai()
    assert d["type"] == "function"
    assert d["function"]["name"] == "greet"
    assert d["function"]["description"] == "Say hi"
    assert d["function"]["parameters"] == params


def test_tool_to_anthropic():
    params = {"type": "object", "properties": {}, "required": []}
    tool = Tool(name="noop", description="Does nothing", parameters=params, func=lambda: None)
    d = tool.to_anthropic()
    assert d["name"] == "noop"
    assert d["description"] == "Does nothing"
    assert d["input_schema"] == params


# ── _fmt_args ─────────────────────────────────────────────────────────────


def test_fmt_args_short():
    assert _fmt_args({"a": "hello"}) == "a='hello'"


def test_fmt_args_truncates():
    result = _fmt_args({"body": "x" * 100})
    assert "..." in result


# ── AgentLoop (OpenAI path) ───────────────────────────────────────────────


def _make_tool(name="ping", return_val="pong"):
    return Tool(name=name, description="", parameters={}, func=lambda: return_val)


def _openai_stop_response(text="All done."):
    """Minimal mock of openai response with finish_reason='stop'."""
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = text
    choice.message.tool_calls = None
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _openai_tool_response(tool_name, tool_id="tc1", args=None):
    """Mock a response that requests a tool call."""
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args or {})

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message.content = None
    choice.message.tool_calls = [tc]

    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch.dict("os.environ", {"MODEL_PROVIDER": "openai", "MODEL_NAME": "gpt-4o"})
@patch("core.agent_loop.AgentLoop._run_openai")
def test_run_dispatches_to_openai(mock_run_openai):
    mock_run_openai.return_value = "ok"
    loop = AgentLoop(tools=[_make_tool()], system="sys")
    result = loop.run("goal")
    mock_run_openai.assert_called_once_with("goal")
    assert result == "ok"


@patch.dict("os.environ", {"MODEL_PROVIDER": "anthropic", "MODEL_NAME": "claude-3-5-haiku-20241022"})
@patch("core.agent_loop.AgentLoop._run_anthropic")
def test_run_dispatches_to_anthropic(mock_run_anthropic):
    mock_run_anthropic.return_value = "done"
    loop = AgentLoop(tools=[_make_tool()], system="sys")
    result = loop.run("goal")
    mock_run_anthropic.assert_called_once_with("goal")
    assert result == "done"


@patch.dict("os.environ", {"MODEL_PROVIDER": "openai", "MODEL_NAME": "gpt-4o"})
def test_openai_stops_on_stop():
    with patch("openai.OpenAI") as MockOpenAI:
        client = MockOpenAI.return_value
        client.chat.completions.create.return_value = _openai_stop_response("Finished!")

        loop = AgentLoop(tools=[_make_tool()], system="sys")
        result = loop._run_openai("do something")

    assert result == "Finished!"


@patch.dict("os.environ", {"MODEL_PROVIDER": "openai", "MODEL_NAME": "gpt-4o"})
def test_openai_calls_tool_then_stops():
    ping_tool = _make_tool("ping", "pong")

    with patch("openai.OpenAI") as MockOpenAI:
        client = MockOpenAI.return_value
        client.chat.completions.create.side_effect = [
            _openai_tool_response("ping"),
            _openai_stop_response("Used ping."),
        ]

        loop = AgentLoop(tools=[ping_tool], system="sys")
        result = loop._run_openai("use ping")

    assert result == "Used ping."
    assert client.chat.completions.create.call_count == 2


@patch.dict("os.environ", {"MODEL_PROVIDER": "openai", "MODEL_NAME": "gpt-4o"})
def test_openai_unknown_tool_doesnt_crash():
    with patch("openai.OpenAI") as MockOpenAI:
        client = MockOpenAI.return_value
        client.chat.completions.create.side_effect = [
            _openai_tool_response("nonexistent"),
            _openai_stop_response("done"),
        ]

        loop = AgentLoop(tools=[], system="sys")
        result = loop._run_openai("go")

    assert result == "done"


@patch.dict("os.environ", {"MODEL_PROVIDER": "openai", "MODEL_NAME": "gpt-4o"})
def test_openai_stops_after_max_iterations():
    with patch("openai.OpenAI") as MockOpenAI:
        client = MockOpenAI.return_value
        # Always returns a tool call, never stops
        client.chat.completions.create.return_value = _openai_tool_response("ping")

        loop = AgentLoop(tools=[_make_tool("ping")], system="sys", max_iterations=3)
        result = loop._run_openai("loop forever")

    assert "3 iterations" in result


# ── AgentLoop (Anthropic path) ────────────────────────────────────────────


def _anthropic_text_response(text="Done."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _anthropic_tool_response(tool_name, tool_id="tu1", args=None):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = args or {}
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


@patch.dict("os.environ", {"MODEL_PROVIDER": "anthropic", "MODEL_NAME": "claude-3-5-haiku-20241022"})
def test_anthropic_stops_on_end_turn():
    with patch("anthropic.Anthropic") as MockAnthropic:
        client = MockAnthropic.return_value
        client.messages.create.return_value = _anthropic_text_response("All done.")

        loop = AgentLoop(tools=[_make_tool()], system="sys")
        result = loop._run_anthropic("goal")

    assert result == "All done."


@patch.dict("os.environ", {"MODEL_PROVIDER": "anthropic", "MODEL_NAME": "claude-3-5-haiku-20241022"})
def test_anthropic_calls_tool_then_stops():
    ping_tool = _make_tool("ping", "pong")

    with patch("anthropic.Anthropic") as MockAnthropic:
        client = MockAnthropic.return_value
        client.messages.create.side_effect = [
            _anthropic_tool_response("ping"),
            _anthropic_text_response("Used ping."),
        ]

        loop = AgentLoop(tools=[ping_tool], system="sys")
        result = loop._run_anthropic("use ping")

    assert result == "Used ping."
    assert client.messages.create.call_count == 2

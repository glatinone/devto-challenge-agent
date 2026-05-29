"""
AgentLoop: the engine that runs an LLM with tools until it decides it's done.

Supports OpenAI (default) and Anthropic. The LLM drives all decisions —
which tools to call, in what order, and when to stop.

Key behaviors:
- parallel_tool_calls=False on OpenAI: forces one tool at a time so each
  write_and_save_draft call gets the full token budget for a complete article.
- Continuation injection: if the last tool round returned a REJECTED/BLOCKED
  result and the model responds with text instead of a tool call, the loop
  injects a reminder and continues rather than exiting prematurely.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Callable

# Signals in a tool result that mean "keep working, don't stop"
_KEEP_WORKING_SIGNALS = ("DRAFT REJECTED", "DRAFT BLOCKED", "REVIEW BLOCKED")

# Max consecutive text-only responses before giving up on continuation injection
_MAX_CONTINUATION_RETRIES = 4


def _had_rejection(tool_results: list[str]) -> bool:
    return any(
        any(sig in r for sig in _KEEP_WORKING_SIGNALS)
        for r in tool_results
    )


_CONTINUE_MSG = (
    "CONTINUE WORKING. One or more tool calls returned REJECTED or BLOCKED. "
    "You must fix the issue and call the tool again immediately. "
    "Do NOT produce a planning response. Do NOT explain what you will fix. "
    "Call write_and_save_draft right now with the corrected, complete article."
)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    func: Callable

    def execute(self, **kwargs) -> str:
        try:
            result = self.func(**kwargs)
            return str(result) if result is not None else "Done."
        except Exception as exc:
            return f"Tool error ({self.name}): {exc}"

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class AgentLoop:
    def __init__(
        self,
        tools: list[Tool],
        system: str,
        max_iterations: int = 60,
        max_tokens: int | None = None,
    ):
        self.tools = {t.name: t for t in tools}
        self.system = system
        self.max_iterations = max_iterations
        self.provider = os.getenv("MODEL_PROVIDER", "openai").lower()
        self.model = os.getenv("MODEL_NAME", "gpt-4o")
        # Caller can override max_tokens; otherwise use env var (default 4096)
        self.max_tokens = max_tokens or int(os.getenv("MODEL_MAX_TOKENS", "4096"))

    def run(self, goal: str) -> str:
        print(f"[agent] Starting with {len(self.tools)} tools, model={self.model}, max_tokens={self.max_tokens}")
        if self.provider == "anthropic":
            return self._run_anthropic(goal)
        return self._run_openai(goal)

    # ── OpenAI ────────────────────────────────────────────────────────────

    def _run_openai(self, goal: str) -> str:
        from openai import OpenAI

        client = OpenAI()
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": goal},
        ]
        tool_defs = [t.to_openai() for t in self.tools.values()]
        pending_rejection = False   # True after any round that returned REJECTED/BLOCKED
        continuation_count = 0      # consecutive text responses after a rejection

        for iteration in range(self.max_iterations):
            # Retry with exponential backoff on rate limit errors (e.g. OpenAI TPM exceeded).
            # Waits: 10s, 20s, 40s, 80s, 90s across 5 attempts — enough for a TPM window reset.
            response = None
            _MAX_API_RETRIES = 5
            for api_attempt in range(_MAX_API_RETRIES):
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        tools=tool_defs,
                        tool_choice="auto",
                        max_tokens=self.max_tokens,
                        # Force sequential tool calls so each write_and_save_draft
                        # gets the full token budget instead of splitting it across
                        # two simultaneous article writes.
                        parallel_tool_calls=False,
                    )
                    break  # success
                except Exception as exc:
                    err_str = str(exc).lower()
                    is_rate_limit = (
                        "rate_limit" in err_str or "rate limit" in err_str or "429" in err_str
                    )
                    if is_rate_limit and api_attempt < _MAX_API_RETRIES - 1:
                        wait = min(90, 10 * (2 ** api_attempt))
                        print(
                            f"[agent] ⚠ Rate limit hit — waiting {wait}s "
                            f"(attempt {api_attempt + 1}/{_MAX_API_RETRIES})"
                        )
                        time.sleep(wait)
                    else:
                        raise
            choice = response.choices[0]

            # Build serializable assistant message
            assistant_msg: dict = {"role": "assistant", "content": choice.message.content}
            if choice.message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.message.tool_calls
                ]
            messages.append(assistant_msg)

            if choice.finish_reason != "tool_calls":
                # Model produced text instead of a tool call.
                # If we're in a rejection state, keep injecting until the model
                # actually calls a tool — but cap retries to avoid infinite loops.
                if pending_rejection and continuation_count < _MAX_CONTINUATION_RETRIES:
                    continuation_count += 1
                    print(
                        f"[agent] ⚠ Text response after rejection "
                        f"(attempt {continuation_count}/{_MAX_CONTINUATION_RETRIES}) "
                        f"— injecting continuation"
                    )
                    messages.append({"role": "user", "content": _CONTINUE_MSG})
                    continue
                # No pending rejection (or retries exhausted): normal stop.
                if pending_rejection:
                    print(f"[agent] ⚠ Gave up after {_MAX_CONTINUATION_RETRIES} continuation retries.")
                return choice.message.content or "Done."

            # Model called at least one tool — reset continuation state.
            continuation_count = 0

            # Guard: if the model returned more than one tool call despite
            # parallel_tool_calls=False, truncate to the first one and re-inject
            # the remainder as a follow-up. This prevents token budget splitting.
            tool_calls = choice.message.tool_calls
            if len(tool_calls) > 1:
                print(
                    f"[agent] ⚠ Model returned {len(tool_calls)} tool calls despite "
                    f"parallel_tool_calls=False — executing only the first, discarding rest."
                )
                tool_calls = tool_calls[:1]
                # Rewrite the assistant message to only reflect the first tool call
                messages[-1]["tool_calls"] = [messages[-1]["tool_calls"][0]]

            # Execute tools
            round_results: list[str] = []
            for tc in tool_calls:
                args = json.loads(tc.function.arguments)
                tool = self.tools.get(tc.function.name)
                if tool:
                    print(f"[agent] → {tc.function.name}({_fmt_args(args)})")
                    result = tool.execute(**args)
                    print(f"[agent]   {result[:120]}{'...' if len(result) > 120 else ''}")
                else:
                    result = f"Unknown tool: {tc.function.name}"
                round_results.append(result)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            pending_rejection = _had_rejection(round_results)
            if not pending_rejection:
                continuation_count = 0  # clean run — reset counter

        return f"Stopped after {self.max_iterations} iterations."

    # ── Anthropic ─────────────────────────────────────────────────────────

    def _run_anthropic(self, goal: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        messages: list[dict] = [{"role": "user", "content": goal}]
        tool_defs = [t.to_anthropic() for t in self.tools.values()]
        pending_rejection = False
        continuation_count = 0

        for iteration in range(self.max_iterations):
            # Retry with exponential backoff on rate limit errors.
            response = None
            _MAX_API_RETRIES = 5
            for api_attempt in range(_MAX_API_RETRIES):
                try:
                    response = client.messages.create(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        system=self.system,
                        messages=messages,
                        tools=tool_defs,
                    )
                    break  # success
                except Exception as exc:
                    err_str = str(exc).lower()
                    is_rate_limit = (
                        "rate_limit" in err_str or "rate limit" in err_str or "429" in err_str
                    )
                    if is_rate_limit and api_attempt < _MAX_API_RETRIES - 1:
                        wait = min(90, 10 * (2 ** api_attempt))
                        print(
                            f"[agent] ⚠ Rate limit hit — waiting {wait}s "
                            f"(attempt {api_attempt + 1}/{_MAX_API_RETRIES})"
                        )
                        time.sleep(wait)
                    else:
                        raise

            # Serialize content blocks for the next request
            content_blocks = []
            for block in response.content:
                if block.type == "text":
                    content_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content_blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )
            messages.append({"role": "assistant", "content": content_blocks})

            if response.stop_reason != "tool_use":
                if pending_rejection and continuation_count < _MAX_CONTINUATION_RETRIES:
                    continuation_count += 1
                    print(
                        f"[agent] ⚠ Text response after rejection "
                        f"(attempt {continuation_count}/{_MAX_CONTINUATION_RETRIES}) "
                        f"— injecting continuation"
                    )
                    messages.append({"role": "user", "content": _CONTINUE_MSG})
                    continue
                if pending_rejection:
                    print(f"[agent] ⚠ Gave up after {_MAX_CONTINUATION_RETRIES} continuation retries.")
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Done."

            # Model called tools — reset continuation state.
            continuation_count = 0

            # Execute tools and collect results
            tool_results = []
            round_results: list[str] = []
            for block in response.content:
                if block.type == "tool_use":
                    tool = self.tools.get(block.name)
                    if tool:
                        print(f"[agent] → {block.name}({_fmt_args(block.input)})")
                        result = tool.execute(**block.input)
                        print(f"[agent]   {result[:120]}{'...' if len(result) > 120 else ''}")
                    else:
                        result = f"Unknown tool: {block.name}"
                    round_results.append(result)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            messages.append({"role": "user", "content": tool_results})
            pending_rejection = _had_rejection(round_results)
            if not pending_rejection:
                continuation_count = 0

        return f"Stopped after {self.max_iterations} iterations."


def _fmt_args(args: dict) -> str:
    """Format tool args for logging — truncate long strings."""
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:40]!r}{'...' if len(s) > 40 else ''}")
    return ", ".join(parts)

"""
AgentLoop: the engine that runs an LLM with tools until it decides it's done.

Supports OpenAI (default) and Anthropic. The LLM drives all decisions —
which tools to call, in what order, and when to stop.
"""

import json
import os
from dataclasses import dataclass
from typing import Callable


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
        print(f"[agent] Starting with {len(self.tools)} tools, model={self.model}")
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

        for iteration in range(self.max_iterations):
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
                max_tokens=self.max_tokens,
            )
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
                return choice.message.content or "Done."

            # Execute tools
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments)
                tool = self.tools.get(tc.function.name)
                if tool:
                    print(f"[agent] → {tc.function.name}({_fmt_args(args)})")
                    result = tool.execute(**args)
                    print(f"[agent]   {result[:120]}{'...' if len(result) > 120 else ''}")
                else:
                    result = f"Unknown tool: {tc.function.name}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        return f"Stopped after {self.max_iterations} iterations."

    # ── Anthropic ─────────────────────────────────────────────────────────

    def _run_anthropic(self, goal: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        messages: list[dict] = [{"role": "user", "content": goal}]
        tool_defs = [t.to_anthropic() for t in self.tools.values()]

        for iteration in range(self.max_iterations):
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                messages=messages,
                tools=tool_defs,
            )

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
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Done."

            # Execute tools and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool = self.tools.get(block.name)
                    if tool:
                        print(f"[agent] → {block.name}({_fmt_args(block.input)})")
                        result = tool.execute(**block.input)
                        print(f"[agent]   {result[:120]}{'...' if len(result) > 120 else ''}")
                    else:
                        result = f"Unknown tool: {block.name}"
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            messages.append({"role": "user", "content": tool_results})

        return f"Stopped after {self.max_iterations} iterations."


def _fmt_args(args: dict) -> str:
    """Format tool args for logging — truncate long strings."""
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:40]!r}{'...' if len(s) > 40 else ''}")
    return ", ".join(parts)

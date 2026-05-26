"""
Model-agnostic LLM client. Reads all config from env vars.
Switch providers by setting MODEL_PROVIDER=anthropic.
"""

import json
import os


class LLMClient:
    def __init__(self) -> None:
        self.provider = os.getenv("MODEL_PROVIDER", "openai").lower()
        self.model = os.getenv("MODEL_NAME", "gpt-4o")
        self.max_tokens = int(os.getenv("MODEL_MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("MODEL_TEMPERATURE", "0.7"))

    def complete(self, user: str, system: str = "") -> str:
        if self.provider == "anthropic":
            return self._complete_anthropic(user, system)
        return self._complete_openai(user, system)

    def complete_json(self, user: str, system: str = "") -> dict:
        json_system = (
            system
            + "\n\nRespond with valid JSON only. No markdown fences, no explanation."
        )
        raw = self.complete(user, json_system)
        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        return json.loads(cleaned)

    def _complete_openai(self, user: str, system: str) -> str:
        from openai import OpenAI

        client = OpenAI()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return resp.choices[0].message.content

    def _complete_anthropic(self, user: str, system: str) -> str:
        import anthropic

        client = anthropic.Anthropic()
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text

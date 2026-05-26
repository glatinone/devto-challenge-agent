"""
AnalystAgent: Identify article angle gaps and rank 3 idea candidates.

One LLM call. Reads memory from GitHub. Sets state.idea_candidates and
state.selected_idea (rank 1).
"""

import json
from typing import Optional

from core.github_client import GitHubClient
from core.llm import LLMClient
from core.state import IdeaCandidate, PipelineState

_MEMORY_SATURATED_PATH = "data/memory/angles_saturated.json"
_MEMORY_PERFORMING_PATH = "data/memory/angles_performing.json"
_IDEA_COUNT = 3
_MAX_ARTICLES_IN_PROMPT = 30


def _format_articles(articles: list, max_count: int) -> str:
    lines = []
    for i, art in enumerate(articles[:max_count], 1):
        tags = ", ".join(art.tags[:4]) if art.tags else "none"
        lines.append(
            f'{i}. "{art.title}" by @{art.author} — '
            f"{art.reactions} reactions, {art.comments_count} comments, "
            f"{art.reading_time_minutes} min read\n   Tags: [{tags}]"
        )
    return "\n\n".join(lines)


def _format_memory(memory_json: Optional[str], key: str) -> str:
    if not memory_json:
        return "None recorded yet."
    try:
        data = json.loads(memory_json)
        items = data.get(key, [])
        if not items:
            return "None recorded yet."
        return "\n".join(f"- {json.dumps(item)}" for item in items[:10])
    except (json.JSONDecodeError, KeyError):
        return "Memory corrupted or empty."


def _build_prompt(
    articles_text: str, saturated_text: str, performing_text: str
) -> tuple[str, str]:
    system = (
        "You are a competitive dev.to article strategist. "
        "Identify unique angles that fill genuine gaps in the current challenge feed. "
        "Favor angles that are specific, opinionated, and backed by real data or personal experience. "
        "Penalize generic tutorials, beginner intros, and comparison listicles."
    )
    user = f"""Here are the current top articles in the dev.to challenge feed:

{articles_text}

---

Saturated angles (already covered well — avoid):
{saturated_text}

Angles that performed well in previous runs:
{performing_text}

---

Identify {_IDEA_COUNT} unique article ideas that fill real gaps in this feed.
Each idea should have a clear, defensible reason why it will outperform existing articles.

Return JSON:
{{
  "ideas": [
    {{
      "rank": 1,
      "title": "Proposed article title (compelling, specific)",
      "angle": "One-sentence description of the unique angle or hook",
      "gap_reasoning": "Why this gap exists and why this angle will outperform existing articles",
      "estimated_score": 34
    }}
  ]
}}"""
    return system, user


def run(state: PipelineState) -> PipelineState:
    if not state.articles:
        state.add_error(
            "AnalystAgent", "No articles in state — ReconAgent may have failed"
        )
        return state

    saturated_json: Optional[str] = None
    performing_json: Optional[str] = None

    try:
        gh = GitHubClient()
        saturated_json = gh.read_file(_MEMORY_SATURATED_PATH)
        performing_json = gh.read_file(_MEMORY_PERFORMING_PATH)
    except Exception as exc:
        state.add_error("AnalystAgent", f"Failed to load memory (non-fatal): {exc}")

    articles_text = _format_articles(state.articles, _MAX_ARTICLES_IN_PROMPT)
    saturated_text = _format_memory(saturated_json, "angles")
    performing_text = _format_memory(performing_json, "patterns")

    system, user = _build_prompt(articles_text, saturated_text, performing_text)

    try:
        result = LLMClient().complete_json(user, system)
    except Exception as exc:
        state.add_error("AnalystAgent", f"LLM call failed: {exc}")
        return state

    try:
        candidates = [IdeaCandidate(**idea) for idea in result.get("ideas", [])]
    except Exception as exc:
        state.add_error("AnalystAgent", f"Failed to parse LLM response: {exc}")
        return state

    if not candidates:
        state.add_error("AnalystAgent", "LLM returned no ideas")
        return state

    state.idea_candidates = sorted(candidates, key=lambda x: x.rank)
    state.selected_idea = state.idea_candidates[0]

    return state

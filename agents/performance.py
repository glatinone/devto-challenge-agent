"""
PerformanceAgent: Analyze evening metrics, update angle memory, write evening brief.

One LLM call. Reads and writes angles_saturated.json and angles_performing.json.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from core.github_client import GitHubClient
from core.llm import LLMClient
from core.state import PipelineState

_MEMORY_SATURATED_PATH = "data/memory/angles_saturated.json"
_MEMORY_PERFORMING_PATH = "data/memory/angles_performing.json"
_BRIEF_PATH_TPL = "data/briefs/brief_{date}.md"


def _format_metrics(metrics: list) -> str:
    if not metrics:
        return "No metrics available."
    by_reactions = sorted(metrics, key=lambda m: m.reactions, reverse=True)
    lines = []
    for i, m in enumerate(by_reactions[:30], 1):
        lines.append(
            f'{i}. "{m.title}" by @{m.author} — '
            f"{m.reactions} reactions, {m.comments_count} comments"
        )
    return "\n".join(lines)


def _build_prompt(
    metrics_text: str, saturated_json: Optional[str], performing_json: Optional[str]
) -> tuple[str, str]:
    system = (
        "You are a content performance analyst for competitive blogging. "
        "Identify patterns that drove high engagement and update memory for tomorrow's run."
    )
    user = f"""Today's dev.to challenge article performance (sorted by reactions):

{metrics_text}

---

Current memory:

Saturated angles:
{saturated_json or 'None recorded yet.'}

Performing patterns:
{performing_json or 'None recorded yet.'}

---

Analyze what drove high reactions today. Update the memory accordingly.

Return JSON:
{{
  "angles_performing_updates": [
    {{"pattern": "specific pattern description", "evidence": "article title that exemplifies this", "avg_reactions": 42}}
  ],
  "angles_saturated_updates": [
    {{"angle": "angle description that is now oversaturated", "frequency": 8}}
  ],
  "evening_brief": "2-3 sentence plain text summary for tomorrow's AnalystAgent. What worked, what to avoid, what gap remains."
}}"""
    return system, user


def _merge_memory(
    existing_json: Optional[str], key: str, updates: list, id_field: str
) -> str:
    if existing_json:
        try:
            data = json.loads(existing_json)
        except json.JSONDecodeError:
            data = {key: []}
    else:
        data = {key: []}

    existing = {item[id_field]: item for item in data.get(key, [])}
    for update in updates:
        item_id = update.get(id_field, "")
        if item_id in existing:
            existing[item_id].update(update)
        else:
            existing[item_id] = update

    data[key] = list(existing.values())
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(data, indent=2, ensure_ascii=False)


def run(state: PipelineState) -> PipelineState:
    if not state.performance_metrics:
        state.add_error(
            "PerformanceAgent",
            "No performance metrics — ScraperAgent may have failed",
        )
        return state

    gh = None
    saturated_json: Optional[str] = None
    performing_json: Optional[str] = None

    try:
        gh = GitHubClient()
        saturated_json = gh.read_file(_MEMORY_SATURATED_PATH)
        performing_json = gh.read_file(_MEMORY_PERFORMING_PATH)
    except Exception as exc:
        state.add_error("PerformanceAgent", f"Failed to load memory: {exc}")

    metrics_text = _format_metrics(state.performance_metrics)
    system, user = _build_prompt(metrics_text, saturated_json, performing_json)

    try:
        result = LLMClient().complete_json(user, system)
    except Exception as exc:
        state.add_error("PerformanceAgent", f"LLM call failed: {exc}")
        return state

    if not gh:
        return state

    # Update angles_performing.json
    performing_updates = result.get("angles_performing_updates", [])
    if performing_updates:
        try:
            merged = _merge_memory(performing_json, "patterns", performing_updates, "pattern")
            gh.commit_file(
                path=_MEMORY_PERFORMING_PATH,
                content=merged,
                message="data: update performing angles memory",
            )
        except Exception as exc:
            state.add_error("PerformanceAgent", f"Failed to update performing memory: {exc}")

    # Update angles_saturated.json
    saturated_updates = result.get("angles_saturated_updates", [])
    if saturated_updates:
        try:
            merged = _merge_memory(saturated_json, "angles", saturated_updates, "angle")
            gh.commit_file(
                path=_MEMORY_SATURATED_PATH,
                content=merged,
                message="data: update saturated angles memory",
            )
        except Exception as exc:
            state.add_error("PerformanceAgent", f"Failed to update saturated memory: {exc}")

    # Save evening brief
    brief_text = result.get("evening_brief", "")
    if brief_text and state.run_date:
        brief_path = _BRIEF_PATH_TPL.format(date=state.run_date.isoformat())
        try:
            gh.commit_file(
                path=brief_path,
                content=f"# Evening Brief — {state.run_date.isoformat()}\n\n{brief_text}\n",
                message=f"data: evening brief {state.run_date.isoformat()}",
            )
        except Exception as exc:
            state.add_error("PerformanceAgent", f"Failed to save evening brief: {exc}")

    return state

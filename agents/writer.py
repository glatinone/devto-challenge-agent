"""
WriterAgent: Draft a dev.to article using the selected idea.

LLM call flow: draft → judge → optional one revision.
Commits draft to GitHub and opens a "needs-review" issue.
"""

import re
from datetime import date

from core.github_client import GitHubClient
from core.llm import LLMClient
from core.state import DraftResult, PipelineState
from skills.devto_writer import (
    DRAFT_SYSTEM,
    JUDGE_SYSTEM,
    PASSING_SCORE,
    REVISION_SYSTEM,
    build_draft_prompt,
    build_judge_prompt,
    build_revision_prompt,
)

_MAX_REVISIONS = 1


def _extract_tags(content: str) -> list[str]:
    m = re.search(r"^tags:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1).strip().strip("[]")
    return [t.strip() for t in raw.split(",") if t.strip()]


def _draft(llm: LLMClient, idea) -> str:
    return llm.complete(
        build_draft_prompt(idea.title, idea.angle, idea.gap_reasoning),
        DRAFT_SYSTEM,
    )


def _judge(llm: LLMClient, content: str) -> dict:
    return llm.complete_json(build_judge_prompt(content), JUDGE_SYSTEM)


def _revise(llm: LLMClient, content: str, verdict: dict) -> str:
    return llm.complete(
        build_revision_prompt(
            content=content,
            score=verdict.get("composite", 0),
            weakest=verdict.get("weakest_dimension", "writing_quality"),
            suggestion=verdict.get(
                "improvement_suggestion", "Improve the weakest dimension."
            ),
        ),
        REVISION_SYSTEM,
    )


def _build_issue_body(idea, draft_path: str, score: int, verdict: dict) -> str:
    return f"""## Article Draft Ready for Review

**Title:** {idea.title}
**Angle:** {idea.angle}
**Self-judged score:** {score}/40
**Draft file:** `{draft_path}`

### Gap Reasoning
{idea.gap_reasoning}

### Score Breakdown
| Dimension | Score |
|---|---|
| Creativity | {verdict.get("creativity", "?")} |
| Technical Execution | {verdict.get("technical_execution", "?")} |
| Writing Quality | {verdict.get("writing_quality", "?")} |
| Wealth of Knowledge | {verdict.get("wealth_of_knowledge", "?")} |

---
*Close this issue to approve and trigger publishing. Add a comment with revision notes if changes are needed.*
"""


def run(state: PipelineState) -> PipelineState:
    if not state.selected_idea:
        state.add_error(
            "WriterAgent", "No selected idea — AnalystAgent may have failed"
        )
        return state

    llm = LLMClient()
    idea = state.selected_idea

    # Stage 1: Draft
    try:
        content = _draft(llm, idea)
    except Exception as exc:
        state.add_error("WriterAgent", f"Draft failed: {exc}")
        return state

    # Stage 2: Judge
    verdict: dict = {}
    score = 0
    try:
        verdict = _judge(llm, content)
        score = verdict.get("composite", 0)
    except Exception as exc:
        state.add_error("WriterAgent", f"Judge failed (non-fatal): {exc}")

    # Stage 3: Optional revision
    if score < PASSING_SCORE and _MAX_REVISIONS > 0 and verdict:
        try:
            content = _revise(llm, content, verdict)
            verdict = _judge(llm, content)
            score = verdict.get("composite", 0)
        except Exception as exc:
            state.add_error("WriterAgent", f"Revision failed (non-fatal): {exc}")

    run_date = state.run_date or date.today()
    draft_path = f"drafts/draft_{run_date.isoformat()}.md"
    tags = _extract_tags(content)

    # Commit draft
    try:
        gh = GitHubClient()
        gh.commit_file(
            path=draft_path,
            content=content,
            message=f"feat: draft — {idea.title[:60]}",
        )
    except Exception as exc:
        state.add_error("WriterAgent", f"Failed to commit draft: {exc}")
        return state

    # Open review issue
    try:
        gh = GitHubClient()
        issue_url = gh.create_issue(
            title=f"[Review] {idea.title}",
            body=_build_issue_body(idea, draft_path, score, verdict),
            labels=["needs-review"],
        )
        state.github_issue_url = issue_url
    except Exception as exc:
        state.add_error("WriterAgent", f"Failed to create review issue: {exc}")

    state.draft = DraftResult(
        title=idea.title,
        content=content,
        tags=tags,
        score=score,
        draft_path=draft_path,
    )

    return state

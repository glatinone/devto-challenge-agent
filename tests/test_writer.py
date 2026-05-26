"""Unit tests for WriterAgent. No network, no real LLM."""

from datetime import date
from unittest.mock import MagicMock, patch

from agents.writer import _extract_tags, run
from core.state import IdeaCandidate, PipelineState

# ── Fixtures ───────────────────────────────────────────────────────────────

IDEA = IdeaCandidate(
    rank=1,
    title="Why Your AI Pipeline Is Lying to You",
    angle="Hidden failure modes in multi-agent systems",
    gap_reasoning="Nobody covers failure modes specifically",
    estimated_score=35,
)

DRAFT_CONTENT = """---
title: Why Your AI Pipeline Is Lying to You
tags: ai, python, agents, debugging
---

I built an agent last month that confidently told me everything was fine.
It was not fine. Three retries, two wrong API calls, and one silent failure later,
I realized the problem: I had no visibility into what was actually happening.
"""

HIGH_VERDICT = {
    "creativity": 9,
    "technical_execution": 8,
    "writing_quality": 9,
    "wealth_of_knowledge": 8,
    "composite": 34,
    "weakest_dimension": "technical_execution",
    "improvement_suggestion": "Add a concrete benchmark number.",
}

LOW_VERDICT = {
    "creativity": 6,
    "technical_execution": 5,
    "writing_quality": 6,
    "wealth_of_knowledge": 5,
    "composite": 22,
    "weakest_dimension": "technical_execution",
    "improvement_suggestion": "Add real benchmarks.",
}


# ── _extract_tags ──────────────────────────────────────────────────────────

def test_extract_tags_comma_separated():
    content = "---\ntags: ai, python, agents\n---\nbody"
    assert _extract_tags(content) == ["ai", "python", "agents"]


def test_extract_tags_bracket_format():
    content = "---\ntags: [ai, python]\n---"
    assert _extract_tags(content) == ["ai", "python"]


def test_extract_tags_missing():
    assert _extract_tags("no frontmatter here") == []


# ── run() ──────────────────────────────────────────────────────────────────

@patch("agents.writer.GitHubClient")
@patch("agents.writer.LLMClient")
def test_run_happy_path_high_score(mock_llm_cls, mock_gh_cls):
    llm = mock_llm_cls.return_value
    llm.complete.return_value = DRAFT_CONTENT
    llm.complete_json.return_value = HIGH_VERDICT

    mock_gh_cls.return_value.commit_file.return_value = None
    mock_gh_cls.return_value.create_issue.return_value = "https://github.com/g/r/issues/1"

    state = PipelineState(run_date=date(2026, 5, 26), selected_idea=IDEA)
    result = run(state)

    assert result.draft is not None
    assert result.draft.score == 34
    assert result.github_issue_url is not None
    # No revision needed — complete() called once
    assert llm.complete.call_count == 1


@patch("agents.writer.GitHubClient")
@patch("agents.writer.LLMClient")
def test_run_low_score_triggers_revision(mock_llm_cls, mock_gh_cls):
    llm = mock_llm_cls.return_value
    llm.complete.side_effect = [DRAFT_CONTENT, DRAFT_CONTENT]  # draft + revision
    llm.complete_json.side_effect = [LOW_VERDICT, HIGH_VERDICT]  # judge + re-judge

    mock_gh_cls.return_value.commit_file.return_value = None
    mock_gh_cls.return_value.create_issue.return_value = "https://github.com/g/r/issues/2"

    state = PipelineState(run_date=date(2026, 5, 26), selected_idea=IDEA)
    result = run(state)

    assert result.draft is not None
    assert llm.complete.call_count == 2  # draft + revision


def test_run_no_selected_idea():
    state = PipelineState(run_date=date(2026, 5, 26))
    result = run(state)
    assert any("No selected idea" in e for e in result.errors.get("WriterAgent", []))


@patch("agents.writer.GitHubClient")
@patch("agents.writer.LLMClient")
def test_run_github_commit_failure_stops_pipeline(mock_llm_cls, mock_gh_cls):
    llm = mock_llm_cls.return_value
    llm.complete.return_value = DRAFT_CONTENT
    llm.complete_json.return_value = HIGH_VERDICT

    mock_gh_cls.return_value.commit_file.side_effect = Exception("GitHub 503")

    state = PipelineState(run_date=date(2026, 5, 26), selected_idea=IDEA)
    result = run(state)

    assert result.draft is None  # draft not set because commit failed
    assert any("Failed to commit" in e for e in result.errors.get("WriterAgent", []))


@patch("agents.writer.GitHubClient")
@patch("agents.writer.LLMClient")
def test_run_issue_creation_failure_is_nonfatal(mock_llm_cls, mock_gh_cls):
    llm = mock_llm_cls.return_value
    llm.complete.return_value = DRAFT_CONTENT
    llm.complete_json.return_value = HIGH_VERDICT

    mock_gh_cls.return_value.commit_file.return_value = None
    mock_gh_cls.return_value.create_issue.side_effect = Exception("labels API error")

    state = PipelineState(run_date=date(2026, 5, 26), selected_idea=IDEA)
    result = run(state)

    # Draft is set even if issue creation failed
    assert result.draft is not None
    assert result.github_issue_url is None

"""Tests for tools/writing.py — draft saving and self-judging."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.writing import self_judge_draft, write_and_save_draft


# ── write_and_save_draft ──────────────────────────────────────────────────


@patch("tools.writing.GitHubClient")
def test_write_and_save_draft_commits_file(MockGH):
    gh = MockGH.return_value
    gh.commit_file.return_value = None

    result = write_and_save_draft(
        title="My Article",
        tags=["ai", "python"],
        body_markdown="Some content here.",
        article_number=1,
    )

    assert gh.commit_file.called
    call_args = gh.commit_file.call_args
    path = call_args[0][0]
    content = call_args[0][1]

    assert "draft_" in path
    assert path.endswith("_1.md")
    assert "title: My Article" in content
    assert "tags: ai, python" in content
    assert "Some content here." in content
    assert "Draft saved" in result


@patch("tools.writing.GitHubClient")
def test_write_and_save_draft_truncates_tags_to_4(MockGH):
    MockGH.return_value.commit_file.return_value = None
    write_and_save_draft("T", ["a", "b", "c", "d", "e"], "body", 1)
    content = MockGH.return_value.commit_file.call_args[0][1]
    tag_line = [l for l in content.splitlines() if l.startswith("tags:")][0]
    assert "e" not in tag_line  # 5th tag excluded


@patch("tools.writing.GitHubClient")
def test_write_and_save_draft_uses_article_number(MockGH):
    MockGH.return_value.commit_file.return_value = None
    write_and_save_draft("T", ["ai"], "body", article_number=2)
    path = MockGH.return_value.commit_file.call_args[0][0]
    assert path.endswith("_2.md")


@patch("tools.writing.GitHubClient")
def test_write_and_save_draft_returns_error_on_exception(MockGH):
    MockGH.return_value.commit_file.side_effect = RuntimeError("network fail")
    result = write_and_save_draft("T", ["ai"], "body", 1)
    assert "Error" in result


@patch("tools.writing.GitHubClient")
def test_write_and_save_draft_reports_word_count(MockGH):
    MockGH.return_value.commit_file.return_value = None
    result = write_and_save_draft("T", ["ai"], "one two three", 1)
    assert "3 words" in result


# ── self_judge_draft ──────────────────────────────────────────────────────

DRAFT_CONTENT = "---\ntitle: My Article\ntags: ai\n---\n\nSome great content."
JUDGE_RESULT = {
    "creativity": 8,
    "technical_execution": 7,
    "writing_quality": 8,
    "wealth_of_knowledge": 8,
    "composite": 31,
    "weakest_dimension": "technical_execution",
    "improvement": "Add concrete benchmarks.",
}


@patch("tools.writing.LLMClient")
@patch("tools.writing.GitHubClient")
def test_self_judge_draft_returns_json(MockGH, MockLLM):
    MockGH.return_value.read_file.return_value = DRAFT_CONTENT
    MockLLM.return_value.complete_json.return_value = JUDGE_RESULT

    result = self_judge_draft("drafts/draft_2026-05-26_1.md")
    parsed = json.loads(result)
    assert parsed["composite"] == 31
    assert "weakest_dimension" in parsed


@patch("tools.writing.GitHubClient")
def test_self_judge_draft_file_not_found(MockGH):
    MockGH.return_value.read_file.return_value = None
    result = self_judge_draft("drafts/nonexistent.md")
    assert "not found" in result.lower() or "Draft not found" in result


@patch("tools.writing.GitHubClient")
def test_self_judge_draft_read_error(MockGH):
    MockGH.return_value.read_file.side_effect = RuntimeError("network fail")
    result = self_judge_draft("drafts/draft_2026-05-26_1.md")
    assert "Error" in result


@patch("tools.writing.LLMClient")
@patch("tools.writing.GitHubClient")
def test_self_judge_draft_llm_error(MockGH, MockLLM):
    MockGH.return_value.read_file.return_value = DRAFT_CONTENT
    MockLLM.return_value.complete_json.side_effect = RuntimeError("LLM down")
    result = self_judge_draft("drafts/draft_2026-05-26_1.md")
    assert "Error" in result

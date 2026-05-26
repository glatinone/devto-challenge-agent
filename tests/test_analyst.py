"""Unit tests for AnalystAgent. No network, no real LLM."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

from agents.analyst import _format_articles, _format_memory, run
from core.state import Article, IdeaCandidate, PipelineState

# ── Fixtures ───────────────────────────────────────────────────────────────

def make_articles(n=3):
    return [
        Article(
            title=f"Article {i}",
            url=f"https://dev.to/user/article-{i}",
            author=f"author{i}",
            tags=["ai", "python"],
            reactions=40 - i * 5,
            comments_count=i + 1,
            reading_time_minutes=5 + i,
        )
        for i in range(n)
    ]


LLM_RESPONSE = {
    "ideas": [
        {
            "rank": 1,
            "title": "Why Your AI Pipeline Is Lying to You",
            "angle": "Hidden failure modes in multi-agent systems",
            "gap_reasoning": "Nobody in the feed covers failure modes specifically",
            "estimated_score": 35,
        },
        {
            "rank": 2,
            "title": "Benchmarking GPT-4o vs Claude on Real Dev Tasks",
            "angle": "Empirical head-to-head with actual numbers",
            "gap_reasoning": "Existing comparisons are vague — this has data",
            "estimated_score": 33,
        },
        {
            "rank": 3,
            "title": "The 200-Line Agent That Replaced My Jira Board",
            "angle": "Minimal viable agent with measurable productivity gain",
            "gap_reasoning": "Most agent articles are theoretical",
            "estimated_score": 31,
        },
    ]
}


# ── _format_articles ───────────────────────────────────────────────────────

def test_format_articles_includes_reactions():
    articles = make_articles(2)
    text = _format_articles(articles, 10)
    assert "40 reactions" in text
    assert "author0" in text


def test_format_articles_respects_max_count():
    articles = make_articles(10)
    text = _format_articles(articles, 3)
    assert "Article 3" not in text


# ── _format_memory ─────────────────────────────────────────────────────────

def test_format_memory_none():
    assert "None recorded yet" in _format_memory(None, "angles")


def test_format_memory_valid():
    data = {"angles": [{"angle": "getting started tutorials", "frequency": 8}]}
    text = _format_memory(json.dumps(data), "angles")
    assert "getting started" in text


def test_format_memory_corrupted():
    assert "corrupted or empty" in _format_memory("not json", "angles")


# ── run() ──────────────────────────────────────────────────────────────────

@patch("agents.analyst.LLMClient")
@patch("agents.analyst.GitHubClient")
def test_run_happy_path(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.return_value = None
    mock_llm_cls.return_value.complete_json.return_value = LLM_RESPONSE

    state = PipelineState(run_date=date(2026, 5, 26), articles=make_articles())
    result = run(state)

    assert len(result.idea_candidates) == 3
    assert result.selected_idea.rank == 1
    assert "Lying" in result.selected_idea.title
    assert not result.errors


def test_run_no_articles():
    state = PipelineState(run_date=date(2026, 5, 26))
    result = run(state)
    assert any("No articles" in e for e in result.errors.get("AnalystAgent", []))


@patch("agents.analyst.LLMClient")
@patch("agents.analyst.GitHubClient")
def test_run_llm_failure(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.return_value = None
    mock_llm_cls.return_value.complete_json.side_effect = Exception("timeout")

    state = PipelineState(run_date=date(2026, 5, 26), articles=make_articles())
    result = run(state)
    assert any("LLM call failed" in e for e in result.errors.get("AnalystAgent", []))
    assert result.selected_idea is None


@patch("agents.analyst.LLMClient")
@patch("agents.analyst.GitHubClient")
def test_run_llm_empty_ideas(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.return_value = None
    mock_llm_cls.return_value.complete_json.return_value = {"ideas": []}

    state = PipelineState(run_date=date(2026, 5, 26), articles=make_articles())
    result = run(state)
    assert any("no ideas" in e for e in result.errors.get("AnalystAgent", []))


@patch("agents.analyst.LLMClient")
@patch("agents.analyst.GitHubClient")
def test_run_memory_load_failure_is_nonfatal(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.side_effect = Exception("GitHub 503")
    mock_llm_cls.return_value.complete_json.return_value = LLM_RESPONSE

    state = PipelineState(run_date=date(2026, 5, 26), articles=make_articles())
    result = run(state)

    # Memory load failure is non-fatal — ideas still generated
    assert result.selected_idea is not None
    assert any("non-fatal" in e for e in result.errors.get("AnalystAgent", []))

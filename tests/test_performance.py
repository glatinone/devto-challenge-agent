"""Unit tests for PerformanceAgent. No network, no real LLM."""

import json
from datetime import date
from unittest.mock import patch

from agents.performance import _format_metrics, _merge_memory, run
from core.state import PerformanceMetrics, PipelineState


# ── Fixtures ───────────────────────────────────────────────────────────────

def make_metrics(n=3):
    return [
        PerformanceMetrics(
            article_url=f"https://dev.to/u/article-{i}",
            title=f"Article {i}",
            author=f"author{i}",
            reactions=50 - i * 10,
            comments_count=i + 1,
            captured_at="2026-05-26T22:00:00Z",
        )
        for i in range(n)
    ]


LLM_RESPONSE = {
    "angles_performing_updates": [
        {"pattern": "real benchmarks", "evidence": "Article 0", "avg_reactions": 50}
    ],
    "angles_saturated_updates": [
        {"angle": "getting started tutorials", "frequency": 7}
    ],
    "evening_brief": "Real benchmarks drove top reactions today. Avoid generic intros tomorrow.",
}


# ── _format_metrics ────────────────────────────────────────────────────────

def test_format_metrics_sorted_by_reactions():
    metrics = make_metrics(3)
    text = _format_metrics(metrics)
    lines = [l for l in text.split("\n") if l.strip()]
    # First line should be Article 0 (50 reactions)
    assert "Article 0" in lines[0]


def test_format_metrics_empty():
    assert "No metrics" in _format_metrics([])


# ── _merge_memory ──────────────────────────────────────────────────────────

def test_merge_memory_creates_new():
    updates = [{"pattern": "benchmarks", "avg_reactions": 42}]
    result = _merge_memory(None, "patterns", updates, "pattern")
    data = json.loads(result)
    assert len(data["patterns"]) == 1
    assert data["patterns"][0]["avg_reactions"] == 42


def test_merge_memory_updates_existing():
    existing = json.dumps({"patterns": [{"pattern": "benchmarks", "avg_reactions": 30}]})
    updates = [{"pattern": "benchmarks", "avg_reactions": 45}]
    result = _merge_memory(existing, "patterns", updates, "pattern")
    data = json.loads(result)
    assert data["patterns"][0]["avg_reactions"] == 45


def test_merge_memory_adds_new_to_existing():
    existing = json.dumps({"patterns": [{"pattern": "benchmarks", "avg_reactions": 30}]})
    updates = [{"pattern": "personal story", "avg_reactions": 38}]
    result = _merge_memory(existing, "patterns", updates, "pattern")
    data = json.loads(result)
    assert len(data["patterns"]) == 2


def test_merge_memory_handles_corrupted_json():
    updates = [{"pattern": "benchmarks", "avg_reactions": 42}]
    result = _merge_memory("not json at all", "patterns", updates, "pattern")
    data = json.loads(result)
    assert len(data["patterns"]) == 1


# ── run() ──────────────────────────────────────────────────────────────────

@patch("agents.performance.LLMClient")
@patch("agents.performance.GitHubClient")
def test_run_happy_path(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.return_value = None
    mock_gh_cls.return_value.commit_file.return_value = None
    mock_llm_cls.return_value.complete_json.return_value = LLM_RESPONSE

    state = PipelineState(run_date=date(2026, 5, 26), performance_metrics=make_metrics())
    result = run(state)

    assert not result.errors
    assert mock_gh_cls.return_value.commit_file.call_count == 3  # performing + saturated + brief


def test_run_no_metrics():
    state = PipelineState(run_date=date(2026, 5, 26))
    result = run(state)
    assert any("No performance metrics" in e for e in result.errors.get("PerformanceAgent", []))


@patch("agents.performance.LLMClient")
@patch("agents.performance.GitHubClient")
def test_run_llm_failure(mock_gh_cls, mock_llm_cls):
    mock_gh_cls.return_value.read_file.return_value = None
    mock_llm_cls.return_value.complete_json.side_effect = Exception("LLM timeout")

    state = PipelineState(run_date=date(2026, 5, 26), performance_metrics=make_metrics())
    result = run(state)
    assert any("LLM call failed" in e for e in result.errors.get("PerformanceAgent", []))

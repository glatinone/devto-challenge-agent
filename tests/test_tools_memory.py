"""Tests for tools/memory.py — read and update angle memory."""

import json
from unittest.mock import MagicMock, call, patch

import pytest

from tools.memory import read_memory, update_memory


# ── read_memory ───────────────────────────────────────────────────────────


@patch("tools.memory.GitHubClient")
def test_read_memory_formats_both_files(MockGH):
    sat = json.dumps({"angles": [{"angle": "tutorial listicles"}]})
    perf = json.dumps({"patterns": [{"pattern": "benchmarks with real numbers"}]})
    MockGH.return_value.read_file.side_effect = [sat, perf]

    result = read_memory()
    assert "Saturated angles" in result
    assert "tutorial listicles" in result
    assert "Performing patterns" in result
    assert "benchmarks with real numbers" in result


@patch("tools.memory.GitHubClient")
def test_read_memory_handles_empty_files(MockGH):
    MockGH.return_value.read_file.return_value = None
    result = read_memory()
    assert "None recorded yet." in result


@patch("tools.memory.GitHubClient")
def test_read_memory_returns_error_on_exception(MockGH):
    MockGH.return_value.read_file.side_effect = RuntimeError("network fail")
    result = read_memory()
    assert "Error" in result


# ── update_memory ─────────────────────────────────────────────────────────


@patch("tools.memory.GitHubClient")
def test_update_memory_adds_new_angles(MockGH):
    gh = MockGH.return_value
    gh.read_file.side_effect = [
        json.dumps({"angles": []}),  # saturated read
        json.dumps({"patterns": [], "briefs": []}),  # performing read
    ]

    result = update_memory(
        saturated_angles=["beginner tutorials"],
        performing_patterns=["real production metrics"],
        brief="Focus on unique angles.",
    )

    assert "+1" in result
    assert gh.commit_file.call_count == 2


@patch("tools.memory.GitHubClient")
def test_update_memory_does_not_duplicate_angles(MockGH):
    gh = MockGH.return_value
    existing_sat = json.dumps({"angles": [{"angle": "beginner tutorials"}]})
    existing_perf = json.dumps({"patterns": [{"pattern": "real metrics"}], "briefs": []})
    gh.read_file.side_effect = [existing_sat, existing_perf]

    update_memory(
        saturated_angles=["beginner tutorials"],  # already exists
        performing_patterns=["real metrics"],  # already exists
        brief="Nothing new today.",
    )

    # Committed data should not have duplicates
    sat_committed = json.loads(gh.commit_file.call_args_list[0][0][1])
    assert sum(1 for a in sat_committed["angles"] if a["angle"] == "beginner tutorials") == 1


@patch("tools.memory.GitHubClient")
def test_update_memory_keeps_last_7_briefs(MockGH):
    gh = MockGH.return_value
    old_briefs = [{"date": f"2026-05-{i:02d}", "text": f"brief {i}"} for i in range(1, 8)]
    gh.read_file.side_effect = [
        json.dumps({"angles": []}),
        json.dumps({"patterns": [], "briefs": old_briefs}),
    ]

    update_memory(["x"], ["y"], "Today's brief.")

    perf_committed = json.loads(gh.commit_file.call_args_list[1][0][1])
    assert len(perf_committed["briefs"]) == 7
    assert perf_committed["briefs"][-1]["text"] == "Today's brief."


@patch("tools.memory.GitHubClient")
def test_update_memory_initialises_from_empty_files(MockGH):
    gh = MockGH.return_value
    gh.read_file.return_value = None  # both files empty

    result = update_memory(["angle1"], ["pattern1"], "brief")

    assert "Error" not in result
    assert gh.commit_file.call_count == 2


@patch("tools.memory.GitHubClient")
def test_update_memory_returns_error_on_exception(MockGH):
    MockGH.return_value.read_file.side_effect = RuntimeError("fail")
    result = update_memory(["a"], ["b"], "brief")
    assert "Error" in result

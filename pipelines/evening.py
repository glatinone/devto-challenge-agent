"""
Evening pipeline: ScraperAgent → PerformanceAgent.

Collects today's article metrics, updates angle memory, writes evening brief.
Run as: python -m pipelines.evening
"""

import os
import sys
from datetime import date

from core.state import PipelineState


def run() -> PipelineState:
    state = PipelineState(run_date=date.today())
    print(f"[evening] {state.run_date} — pipeline start")

    from agents.discovery import run as discovery_run

    state = discovery_run(state)
    if not state.challenge_url:
        print("[evening] No open challenge found. Pipeline stopped.")
        _log_errors(state, "DiscoveryAgent")
        return state
    print(f"[evening] DiscoveryAgent → {state.challenge_url}")

    from agents.scraper import run as scraper_run

    state = scraper_run(state)
    print(f"[evening] ScraperAgent → {len(state.performance_metrics)} articles")

    if not state.performance_metrics:
        print("[evening] No metrics collected. Pipeline stopped.")
        _log_errors(state, "ScraperAgent")
        return state

    from agents.performance import run as performance_run

    state = performance_run(state)
    print("[evening] PerformanceAgent → memory updated, brief saved")

    _log_errors(state, "PerformanceAgent")
    print(f"\n[evening] Pipeline complete.")
    return state


def _log_errors(state: PipelineState, agent: str) -> None:
    for msg in state.errors.get(agent, []):
        print(f"[evening] {agent} error: {msg}")


if __name__ == "__main__":
    result = run()
    sys.exit(1 if result.errors else 0)

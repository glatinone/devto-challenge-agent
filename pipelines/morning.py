"""
Morning pipeline: MonitorAgent → ReconAgent → AnalystAgent → WriterAgent.

Stops early if challenge is CLOSED or any critical agent produces no output.
Run as: python -m pipelines.morning
"""

import os
import sys
from datetime import date

from core.state import ChallengeStatus, PipelineState


def run() -> PipelineState:
    state = PipelineState(
        run_date=date.today(),
        challenge_url=os.getenv("DEVTO_CHALLENGE_URL", ""),
    )
    print(f"[morning] {state.run_date} — pipeline start")

    from agents.monitor import run as monitor_run

    state = monitor_run(state)
    print(f"[morning] MonitorAgent → {state.challenge_status} ({state.challenge_title})")

    if state.challenge_status == ChallengeStatus.CLOSED:
        print("[morning] Challenge is CLOSED. Pipeline stopped.")
        return state

    _log_errors(state, "MonitorAgent")

    from agents.recon import run as recon_run

    state = recon_run(state)
    print(f"[morning] ReconAgent → {len(state.articles)} articles")

    if not state.articles:
        print("[morning] No articles fetched. Pipeline stopped.")
        _log_errors(state, "ReconAgent")
        return state

    from agents.analyst import run as analyst_run

    state = analyst_run(state)
    print(f"[morning] AnalystAgent → {len(state.idea_candidates)} ideas")

    if not state.selected_idea:
        print("[morning] No ideas generated. Pipeline stopped.")
        _log_errors(state, "AnalystAgent")
        return state

    print(f"[morning] Selected: \"{state.selected_idea.title}\"")

    from agents.writer import run as writer_run

    state = writer_run(state)

    if state.draft:
        print(
            f"[morning] WriterAgent → score {state.draft.score}/40"
            f" | issue: {state.github_issue_url}"
        )
    else:
        print("[morning] WriterAgent produced no draft")

    _log_errors(state, "WriterAgent")
    print(f"\n[morning] Summary:\n{state.summary()}")
    return state


def _log_errors(state: PipelineState, agent: str) -> None:
    for msg in state.errors.get(agent, []):
        print(f"[morning] {agent} error: {msg}")


if __name__ == "__main__":
    result = run()
    critical_failure = (
        not result.draft and result.challenge_status != ChallengeStatus.CLOSED
    )
    sys.exit(1 if critical_failure else 0)

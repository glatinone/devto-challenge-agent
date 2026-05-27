"""
Publish pipeline: triggered when Kiel closes a "needs-review" GitHub issue.

Run as: python -m pipelines.publish
Context is passed via ISSUE_BODY and ISSUE_NUMBER env vars (set by the workflow).
"""

import sys
from datetime import date

from core.state import PipelineState


_CRITICAL_PATTERNS = ("API error", "not found", "not set", "empty", "parse", "Could not extract")


def run() -> PipelineState:
    import os

    state = PipelineState(run_date=date.today())
    issue_num = os.getenv("ISSUE_NUMBER", "?")
    print(f"[publish] Issue #{issue_num} closed — starting publish pipeline")

    from agents.publisher import run as publisher_run

    state = publisher_run(state)

    for agent, msgs in state.errors.items():
        for msg in msgs:
            print(f"[publish] {agent}: {msg}")

    if not state.errors:
        print("[publish] Done.")

    return state


if __name__ == "__main__":
    result = run()
    # Non-zero exit only for critical failures (article not published)
    # Log-update failures are non-critical — article is already live
    critical = any(
        any(p in m for p in _CRITICAL_PATTERNS)
        for msgs in result.errors.values()
        for m in msgs
        if "IS live" not in m and "Already published" not in m
    )
    sys.exit(1 if critical else 0)

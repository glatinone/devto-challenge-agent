"""
Morning pipeline: delegates to the autonomous morning agent.

The agent drives its own workflow — tool calls, retries, judging, review requests.
Run as: python -m pipelines.morning
"""

import sys
from datetime import date

from agents.morning_agent import run as agent_run
from tools.session import reset_session


def run() -> str:
    reset_session()  # clear any stale in-process state from previous runs
    print(f"[morning] {date.today()} — starting autonomous morning agent")
    summary = agent_run()
    print(f"[morning] Agent complete:\n{summary}")
    return summary


if __name__ == "__main__":
    run()
    sys.exit(0)

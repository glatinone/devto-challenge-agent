"""
Evening pipeline: delegates to the autonomous evening agent.

The agent analyzes today's metrics and updates memory for tomorrow.
Run as: python -m pipelines.evening
"""

import sys
from datetime import date

from agents.evening_agent import run as agent_run


def run() -> str:
    print(f"[evening] {date.today()} — starting autonomous evening agent")
    summary = agent_run()
    print(f"[evening] Agent complete:\n{summary}")
    return summary


if __name__ == "__main__":
    run()
    sys.exit(0)

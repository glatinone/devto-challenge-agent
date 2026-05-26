"""
Morning pipeline: delegates to the autonomous morning agent.

The agent drives its own workflow — tool calls, retries, judging, review requests.
Run as: python -m pipelines.morning
"""

import sys
from datetime import date

# ── DEBUG: trace which challenge.py is actually loaded ────────────────────
import tools.challenge as _ch
print(f"[debug] challenge.py path: {_ch.__file__}", flush=True)
with open(_ch.__file__, encoding="utf-8") as _f:
    _first = _f.readline().strip() + " | " + _f.readline().strip()
print(f"[debug] challenge.py first lines: {_first}", flush=True)
print(f"[debug] has 'discover v4': {'discover v4' in open(_ch.__file__).read()}", flush=True)
# ── END DEBUG ─────────────────────────────────────────────────────────────

from agents.morning_agent import run as agent_run


def run() -> str:
    print(f"[morning] {date.today()} — starting autonomous morning agent")
    summary = agent_run()
    print(f"[morning] Agent complete:\n{summary}")
    return summary


if __name__ == "__main__":
    run()
    sys.exit(0)

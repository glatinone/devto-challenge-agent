"""
Auto-approve pipeline: publish drafts not reviewed within AUTO_APPROVE_HOURS.

Run by auto_approve.yml on a schedule every 30 minutes.
Finds open 'needs-review' issues older than the threshold, publishes them
directly (same logic as pipelines/publish.py), then closes the issue.

Note: this pipeline runs publish directly rather than closing the issue to
trigger publish.yml — GITHUB_TOKEN cannot trigger other workflow runs.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

AUTO_APPROVE_HOURS = 5


def run() -> int:
    from core.github_client import GitHubClient
    from core.state import PipelineState
    from agents.publisher import run as publisher_run

    try:
        gh = GitHubClient()
    except Exception as exc:
        print(f"[auto-approve] GitHub client init failed: {exc}")
        return 1

    issues = gh.list_open_issues(label="needs-review")
    if not issues:
        print("[auto-approve] No open review issues — nothing to do")
        return 0

    now = datetime.now(timezone.utc)
    published = 0
    skipped = 0
    failed = 0

    for issue in issues:
        number = issue.get("number", "?")
        title = issue.get("title", "?")
        created_raw = issue.get("created_at", "")

        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            print(f"[auto-approve] Issue #{number}: could not parse created_at '{created_raw}' — skipping")
            skipped += 1
            continue

        age_hours = (now - created_at).total_seconds() / 3600

        if age_hours < AUTO_APPROVE_HOURS:
            remaining = AUTO_APPROVE_HOURS - age_hours
            print(f"[auto-approve] Issue #{number} '{title}': {age_hours:.1f}h old — {remaining:.1f}h until auto-approve")
            skipped += 1
            continue

        print(f"[auto-approve] Issue #{number} '{title}': {age_hours:.1f}h old — auto-approving now")

        os.environ["ISSUE_BODY"] = issue.get("body", "")
        os.environ["ISSUE_NUMBER"] = str(number)

        from datetime import date
        state = PipelineState(run_date=date.today())
        state = publisher_run(state)

        if state.errors:
            for agent, msgs in state.errors.items():
                for msg in msgs:
                    print(f"[auto-approve] {agent}: {msg}")
            failed += 1
            continue

        # Close the issue so it doesn't get re-processed next run
        try:
            gh._request("PATCH", f"/issues/{number}", {"state": "closed"})
            print(f"[auto-approve] Closed issue #{number}")
        except Exception as exc:
            print(f"[auto-approve] Warning: published but could not close issue #{number}: {exc}")

        published += 1

    print(f"[auto-approve] Done: {published} published, {skipped} not yet due, {failed} failed")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(run())

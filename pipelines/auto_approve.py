"""
Auto-approve pipeline: publish drafts not reviewed within AUTO_APPROVE_HOURS.

Run by auto_approve.yml on a schedule every 30 minutes.
Finds open 'needs-review' issues older than the threshold, publishes them
directly (same logic as pipelines/publish.py), then closes the issue.

Score gate: issues with a self-judged score below MIN_AUTO_APPROVE_SCORE are
closed WITHOUT publishing — they are below quality threshold regardless of age.

Note: this pipeline runs publish directly rather than closing the issue to
trigger publish.yml — GITHUB_TOKEN cannot trigger other workflow runs.
"""

import os
import re
import sys
from datetime import datetime, timezone, timedelta

AUTO_APPROVE_HOURS = 5
_MIN_AUTO_APPROVE_SCORE = 30  # must match morning_agent._PASSING_SCORE


def _extract_score(issue_body: str) -> int | None:
    """Parse self-judged score from issue body. Returns None if not found."""
    m = re.search(r"\*\*Self-judged score:\*\*\s*(\d+)/40", issue_body)
    if m:
        return int(m.group(1))
    # Fallback: plain "score: N/40" format
    m = re.search(r"score[:\s]+(\d+)\s*/\s*40", issue_body, re.IGNORECASE)
    return int(m.group(1)) if m else None


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

        print(f"[auto-approve] Issue #{number} '{title}': {age_hours:.1f}h old — checking score")

        issue_body = issue.get("body", "")
        score = _extract_score(issue_body)

        if score is not None and score < _MIN_AUTO_APPROVE_SCORE:
            print(
                f"[auto-approve] Issue #{number}: score {score}/40 is below "
                f"minimum {_MIN_AUTO_APPROVE_SCORE} — closing WITHOUT publishing"
            )
            try:
                gh._request(
                    "PATCH", f"/issues/{number}",
                    {
                        "state": "closed",
                        "body": issue_body + (
                            f"\n\n---\n**Auto-approve rejected:** score {score}/40 is below "
                            f"the minimum {_MIN_AUTO_APPROVE_SCORE}/40. Article not published."
                        ),
                    }
                )
            except Exception as exc:
                print(f"[auto-approve] Warning: could not close low-score issue #{number}: {exc}")
            skipped += 1
            continue

        if score is None:
            print(f"[auto-approve] Issue #{number}: could not parse score — proceeding with publish")
        else:
            print(f"[auto-approve] Issue #{number}: score {score}/40 >= {_MIN_AUTO_APPROVE_SCORE} — auto-approving now")

        os.environ["ISSUE_BODY"] = issue_body
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

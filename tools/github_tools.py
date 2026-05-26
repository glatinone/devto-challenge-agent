"""
GitHub tools: open review issues and read stored challenge state.
"""

import json
from datetime import date

from core.github_client import GitHubClient

_CHALLENGE_PATH = "data/challenge.json"


def request_human_review(
    draft_path: str,
    title: str,
    score: int,
    angle: str,
    score_breakdown: str,
) -> str:
    """
    Open a GitHub Issue for human review. Kiel closes the issue to approve
    and trigger publishing. Returns the issue URL.
    """
    body = f"""## Article Draft Ready for Review

**Title:** {title}
**Angle:** {angle}
**Self-judged score:** {score}/40
**Draft file:** `{draft_path}`

### Score Breakdown
{score_breakdown}

---

**To approve:** close this issue — publishing triggers automatically.
**To revise:** edit `{draft_path}` directly in GitHub, then close this issue.
"""
    try:
        gh = GitHubClient()
        url = gh.create_issue(
            title=f"[Review] {title}",
            body=body,
            labels=["needs-review"],
        )
        return f"Review issue created: {url}"
    except Exception as exc:
        return f"Error creating review issue: {exc}"


def save_challenge_state(challenge_url: str, challenge_title: str) -> str:
    """Persist the current challenge URL so the evening agent can find it."""
    import json
    from datetime import datetime, timezone

    payload = {
        "url": challenge_url,
        "title": challenge_title,
        "last_confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        gh = GitHubClient()
        gh.commit_file(
            _CHALLENGE_PATH,
            json.dumps(payload, indent=2),
            f"data: active challenge — {challenge_title[:50]}",
        )
        return f"Challenge state saved: {challenge_url}"
    except Exception as exc:
        return f"Error saving challenge state: {exc}"


def load_challenge_state() -> str:
    """Load the last known challenge URL (used by evening agent)."""
    try:
        gh = GitHubClient()
        raw = gh.read_file(_CHALLENGE_PATH)
        if not raw:
            return "No stored challenge state found"
        data = json.loads(raw)
        return f"Stored challenge: '{data.get('title')}' at {data.get('url')}"
    except Exception as exc:
        return f"Error loading challenge state: {exc}"

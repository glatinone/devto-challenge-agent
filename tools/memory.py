"""
Memory tools: read and update the angle memory files.
"""

import json
from datetime import datetime, timezone

from core.github_client import GitHubClient

_SATURATED_PATH = "data/memory/angles_saturated.json"
_PERFORMING_PATH = "data/memory/angles_performing.json"


def read_memory() -> str:
    """Read current angle memory: what's saturated and what's performing."""
    try:
        gh = GitHubClient()
        saturated = gh.read_file(_SATURATED_PATH)
        performing = gh.read_file(_PERFORMING_PATH)
    except Exception as exc:
        return f"Error reading memory: {exc}"

    return (
        f"=== Saturated angles (avoid) ===\n"
        f"{saturated or 'None recorded yet.'}\n\n"
        f"=== Performing patterns (lean into) ===\n"
        f"{performing or 'None recorded yet.'}"
    )


def update_memory(
    saturated_angles: list[str],
    performing_patterns: list[str],
    brief: str,
) -> str:
    """
    Update angle memory after analysis.

    saturated_angles: list of angle descriptions now oversaturated
    performing_patterns: list of pattern descriptions that drove reactions
    brief: 2-3 sentence summary for tomorrow's agent
    """
    try:
        gh = GitHubClient()
        now = datetime.now(timezone.utc).isoformat()

        # Update saturated
        raw = gh.read_file(_SATURATED_PATH)
        sat_data = json.loads(raw) if raw else {"angles": []}
        existing_sat = {a["angle"] for a in sat_data.get("angles", [])}
        for angle in saturated_angles:
            if angle not in existing_sat:
                sat_data.setdefault("angles", []).append({"angle": angle})
        sat_data["updated_at"] = now
        gh.commit_file(_SATURATED_PATH, json.dumps(sat_data, indent=2), "data: update saturated angles")

        # Update performing
        raw = gh.read_file(_PERFORMING_PATH)
        perf_data = json.loads(raw) if raw else {"patterns": [], "briefs": []}
        existing_perf = {p["pattern"] for p in perf_data.get("patterns", [])}
        for pattern in performing_patterns:
            if pattern not in existing_perf:
                perf_data.setdefault("patterns", []).append({"pattern": pattern})
        perf_data.setdefault("briefs", []).append({"date": now[:10], "text": brief})
        perf_data["briefs"] = perf_data["briefs"][-7:]  # keep last 7 days
        perf_data["updated_at"] = now
        gh.commit_file(_PERFORMING_PATH, json.dumps(perf_data, indent=2), "data: update performing patterns")

    except Exception as exc:
        return f"Error updating memory: {exc}"

    return f"Memory updated. Saturated: +{len(saturated_angles)}, Performing: +{len(performing_patterns)}"

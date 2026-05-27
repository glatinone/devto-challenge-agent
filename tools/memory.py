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
        sat_raw = gh.read_file(_SATURATED_PATH)
        perf_raw = gh.read_file(_PERFORMING_PATH)
    except Exception as exc:
        return f"Error reading memory: {exc}"

    lines = ["=== MEMORY: Angle Intelligence ===\n"]

    # Saturated angles
    lines.append("AVOID these saturated angles (overdone in recent feeds):")
    if sat_raw:
        try:
            sat_data = json.loads(sat_raw)
            angles = sat_data.get("angles", [])
            if angles:
                for a in angles:
                    lines.append(f"  - {a['angle']}")
            else:
                lines.append("  (none recorded yet)")
        except (json.JSONDecodeError, KeyError):
            lines.append("  (none recorded yet)")
    else:
        lines.append("  (none recorded yet)")

    lines.append("")

    # Performing patterns
    lines.append("LEAN INTO these performing patterns (drove high reactions):")
    if perf_raw:
        try:
            perf_data = json.loads(perf_raw)
            patterns = perf_data.get("patterns", [])
            if patterns:
                for p in patterns:
                    lines.append(f"  + {p['pattern']}")
            else:
                lines.append("  (none recorded yet)")

            # Latest brief
            briefs = perf_data.get("briefs", [])
            if briefs:
                latest = briefs[-1]
                lines.append(f"\nLatest brief ({latest.get('date', '?')}): {latest.get('text', '')}")
        except (json.JSONDecodeError, KeyError):
            lines.append("  (none recorded yet)")
    else:
        lines.append("  (none recorded yet)")

    return "\n".join(lines)


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

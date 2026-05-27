"""
Memory tools: read and update angle memory and voice fingerprint files.
"""

import json
from datetime import date, datetime, timezone

from core.github_client import GitHubClient

_SATURATED_PATH = "data/memory/angles_saturated.json"
_PERFORMING_PATH = "data/memory/angles_performing.json"
_VOICE_PATH = "data/memory/voice_fingerprint.json"


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


# ── Voice fingerprint ──────────────────────────────────────────────────────

def read_voice_fingerprint() -> str:
    """
    Read Kiel's voice fingerprint: approved hooks, quotable lines,
    working title formulas, and voice notes from published/performing articles.

    Call this BEFORE writing any article to calibrate your voice against
    real examples — not just abstract style rules.
    """
    try:
        gh = GitHubClient()
        raw = gh.read_file(_VOICE_PATH)
    except Exception as exc:
        return f"Error reading voice fingerprint: {exc}"

    if not raw:
        return (
            "No voice fingerprint yet — this is the first run. "
            "Write per the system prompt style rules. "
            "The evening agent will record what works after articles get reactions."
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "Voice fingerprint file is malformed. Write per system prompt style rules."

    lines = ["=== VOICE FINGERPRINT: Kiel's Approved Style ===\n"]

    hooks = data.get("approved_hooks", [])
    if hooks:
        lines.append("APPROVED OPENING HOOKS (first sentences from articles that performed):")
        for h in hooks[-5:]:
            lines.append(f'  • "{h["text"]}"')
            if h.get("article"):
                lines.append(f'    from: {h["article"]}')
    else:
        lines.append("APPROVED HOOKS: none yet — write a strong Specific Moment + Reversal hook.")

    quotes = data.get("quotable_lines", [])
    lines.append("")
    if quotes:
        lines.append("QUOTABLE LINES (screenshot-worthy, stood alone without context):")
        for q in quotes[-5:]:
            lines.append(f'  • "{q["text"]}"')
    else:
        lines.append("QUOTABLE LINES: none yet — aim for one line that survives screenshot.")

    formulas = data.get("working_formulas", [])
    lines.append("")
    if formulas:
        lines.append("TITLE FORMULAS THAT GOT APPROVED (use these patterns):")
        for f in formulas:
            lines.append(f"  Pattern {f['pattern']}: \"{f['example']}\"")
    else:
        lines.append("WORKING FORMULAS: none yet — try Pattern A (Cost-Benefit Tension) or C (Number Shock).")

    notes = data.get("voice_notes", [])
    if notes:
        lines.append("")
        lines.append("VOICE NOTES (specific observations about what sounded like Kiel):")
        for n in notes[-3:]:
            lines.append(f"  [{n.get('date', '?')}] {n['note']}")

    return "\n".join(lines)


def update_voice_fingerprint(
    approved_hooks: list[str],
    quotable_lines: list[str],
    formula_used: str,
    formula_example: str,
    notes: str = "",
) -> str:
    """
    Update voice fingerprint after an article performs well (5+ reactions).

    approved_hooks: list of first sentence(s) from the article
    quotable_lines: lines that stood alone and could be screenshot-shared
    formula_used: which title pattern was used (A/B/C/D/E)
    formula_example: the actual title text
    notes: any specific observation about what sounded authentic vs AI-generated
    """
    try:
        gh = GitHubClient()
        raw = gh.read_file(_VOICE_PATH)
        data = json.loads(raw) if raw else {
            "approved_hooks": [],
            "quotable_lines": [],
            "working_formulas": [],
            "voice_notes": [],
        }
        today = date.today().isoformat()
        now = datetime.now(timezone.utc).isoformat()

        for hook in approved_hooks:
            data.setdefault("approved_hooks", []).append({"text": hook, "date": today})
        data["approved_hooks"] = data["approved_hooks"][-20:]  # keep last 20

        for line in quotable_lines:
            data.setdefault("quotable_lines", []).append({"text": line, "date": today})
        data["quotable_lines"] = data["quotable_lines"][-20:]

        existing_examples = {f["example"] for f in data.get("working_formulas", [])}
        if formula_example and formula_example not in existing_examples:
            data.setdefault("working_formulas", []).append({
                "pattern": formula_used,
                "example": formula_example,
                "date": today,
            })

        if notes:
            data.setdefault("voice_notes", []).append({"note": notes, "date": today})
            data["voice_notes"] = data["voice_notes"][-10:]

        data["updated_at"] = now
        gh.commit_file(
            _VOICE_PATH,
            json.dumps(data, indent=2),
            f"data: voice fingerprint — +{len(approved_hooks)} hooks, +{len(quotable_lines)} quotes",
        )
        return (
            f"Voice fingerprint updated: "
            f"+{len(approved_hooks)} hooks, "
            f"+{len(quotable_lines)} quotable lines, "
            f"formula {formula_used} recorded."
        )
    except Exception as exc:
        return f"Error updating voice fingerprint: {exc}"

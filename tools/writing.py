"""
Writing tools: save drafts to GitHub and self-judge them.

The agent writes article content itself. These tools handle persistence,
anti-pattern scanning, and structured scoring — they don't generate content.
"""

import json
import re
from datetime import date

from core.github_client import GitHubClient
from core.llm import LLMClient
from skills.devto_writer import JUDGE_SYSTEM, build_judge_prompt


_MIN_WORDS = 800
_MAX_WORDS = 1200

# ── Anti-pattern scanner ───────────────────────────────────────────────────

# Em dashes (unicode variants + double-hyphen used as em dash)
_EM_DASH_RE = re.compile(r"[—–‒―]")

# Structural meta-labels the agent sometimes writes literally
# e.g. "**Hook**:", "### The Conflict", "**What I Built**:"
_LABEL_RE = re.compile(
    r"^\s*(\*{1,3})?\s*"
    r"(Hook|Conflict|Resolution|What I Built|How It Works|What Happened|"
    r"Meta.?Lesson|Narrative Arc|The Setup|The Problem|The Fix|The Lesson|"
    r"Section \d+|Step \d+)"
    r"\s*(\*{1,3})?[:\s]*$",
    re.IGNORECASE | re.MULTILINE,
)

# Section headers that are just template element names
_HEADER_LABEL_RE = re.compile(
    r"^#{1,4}\s*(Hook|Conflict|Resolution|What I Built|How It Works|What Happened|"
    r"The Conflict|The Resolution|The Hook|The Setup|The Problem|The Fix|The Lesson)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Signposting phrases (hard block if in first 300 chars of body)
_SIGNPOSTING = [
    "let's dive in", "lets dive in", "let's dive into",
    "without further ado", "without further ado",
    "in this article", "in this post", "in this tutorial",
    "here's what you need to know", "here is what you need to know",
    "let me walk you through", "i'll walk you through",
    "today we'll", "today we will", "today i'll show",
]

# Forbidden AI filler phrases
_FORBIDDEN = [
    "game-changer", "game changer",
    "revolutionary", "revolutionize",
    "unlock the potential", "unlock your potential",
    "seamlessly integrat", "works seamlessly",
    "it's worth noting", "its worth noting",
    "needless to say",
    "i hope you found this helpful", "hope you found this helpful",
    "i hope this was helpful", "hope this was useful",
    "exciting times ahead", "the future looks bright",
    "can't wait to see what comes next",
    "in conclusion,", "to summarize,", "as we have seen",
]

# Generic soft hook openers (first 200 chars)
_SOFT_HOOKS = [
    "have you ever ",
    "today i want to share",
    "i recently learned",
    "recently, i was",
    "ai is changing everything",
    "like many developers",
    "i've been working with",
    "i have been working with",
    "as a developer",
    "if you're a developer",
]


def _bullets_outside_fences(body: str) -> list[str]:
    """Return first 3 bullet-point lines found outside code fences."""
    in_fence = False
    violations = []
    for i, line in enumerate(body.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^[-*]\s+\S", stripped):
            violations.append(f"line {i}: {stripped[:70]}")
        if len(violations) >= 3:
            break
    return violations


def _find_em_dashes(body: str) -> list[str]:
    """Return up to 3 em dash contexts."""
    results = []
    for m in _EM_DASH_RE.finditer(body):
        start = max(0, m.start() - 30)
        end = min(len(body), m.end() + 30)
        snippet = body[start:end].replace("\n", " ").strip()
        results.append(f'"{snippet}"')
        if len(results) >= 3:
            break
    return results


def scan_draft(body: str, title: str = "") -> list[str]:
    """
    Scan article body for anti-patterns. Returns a list of violation strings.
    Empty list means the draft is clean.

    Hard violations (must fix before publishing):
    - Em dashes
    - Structural meta-labels written literally
    - Bullet points in body (outside code fences)
    - Signposting opener in first 300 chars
    - Forbidden filler phrases
    - Soft hook openers
    """
    violations: list[str] = []
    body_lower = body.lower()
    opening = body_lower[:300]

    # 1. Em dashes
    em_contexts = _find_em_dashes(body)
    for ctx in em_contexts:
        violations.append(f"[EM_DASH] Replace with comma, colon, or period: {ctx}")

    # 2. Structural meta-labels written literally as lines
    for m in _LABEL_RE.finditer(body):
        label = m.group(0).strip()
        violations.append(
            f"[STRUCTURAL_LABEL] Remove this template label from the article body: '{label}' "
            f"— write prose directly, no section names"
        )
    for m in _HEADER_LABEL_RE.finditer(body):
        label = m.group(0).strip()
        violations.append(
            f"[STRUCTURAL_LABEL] Remove this header — it reveals the template: '{label}'"
        )

    # 3. Bullet points outside fences
    bullets = _bullets_outside_fences(body)
    for b in bullets:
        violations.append(f"[BULLET_POINT] Convert to prose paragraph: {b}")

    # 4. Signposting in opener
    for phrase in _SIGNPOSTING:
        if phrase in opening:
            idx = opening.find(phrase)
            snippet = body[max(0, idx - 10):idx + len(phrase) + 20].replace("\n", " ")
            violations.append(f"[SIGNPOSTING] Remove opener: '...{snippet}...'")
            break  # one report is enough

    # 5. Soft hook opener (first 200 chars)
    first_200 = body_lower[:200]
    for phrase in _SOFT_HOOKS:
        if phrase in first_200:
            violations.append(
                f"[SOFT_HOOK] Weak opener detected: '{phrase}' — "
                f"replace with a specific moment, number, or direct claim"
            )
            break

    # 6. Forbidden filler phrases
    found_forbidden = []
    for phrase in _FORBIDDEN:
        if phrase in body_lower:
            found_forbidden.append(phrase)
    if found_forbidden:
        violations.append(
            f"[FORBIDDEN_PHRASE] Remove these AI filler phrases: "
            + ", ".join(f"'{p}'" for p in found_forbidden[:4])
        )

    return violations


def write_and_save_draft(
    title: str,
    tags: list[str],
    body_markdown: str,
    article_number: int = 1,
) -> str:
    """
    Save a draft to GitHub at drafts/draft_YYYY-MM-DD_{article_number}.md.

    Pipeline:
    1. Word count check (800 minimum)
    2. Anti-pattern scan (em dashes, labels, bullets, signposting, forbidden phrases)
    3. Save if both pass
    """
    word_count = len(body_markdown.split())

    # Step 1: word count
    if word_count < _MIN_WORDS:
        return (
            f"DRAFT REJECTED — too short: {word_count} words. "
            f"Minimum is {_MIN_WORDS} words. "
            f"Rewrite with {_MIN_WORDS - word_count} more words of real substance: "
            f"a failure moment, real code, specific numbers, a quotable line. "
            f"Do NOT add filler sentences. Add substance."
        )

    # Step 2: anti-pattern scan
    violations = scan_draft(body_markdown, title)
    if violations:
        lines = ["DRAFT BLOCKED — anti-patterns detected. Fix ALL before retrying:\n"]
        for v in violations:
            lines.append(f"  • {v}")
        lines.append(
            f"\nFix every item above, then call write_and_save_draft again with the corrected body."
        )
        return "\n".join(lines)

    # Step 3: save
    over_limit = word_count > _MAX_WORDS
    tags_str = ", ".join(tags[:4])
    content = f"---\ntitle: {title}\ntags: {tags_str}\n---\n\n{body_markdown.strip()}\n"
    path = f"drafts/draft_{date.today().isoformat()}_{article_number}.md"

    try:
        gh = GitHubClient()
        gh.commit_file(
            path=path,
            content=content,
            message=f"feat: draft {article_number} — {title[:60]}",
        )
    except Exception as exc:
        return f"Error saving draft: {exc}"

    length_note = (
        f" (over {_MAX_WORDS} — consider trimming for better punch)" if over_limit else ""
    )
    return f"Draft saved to {path} ({word_count} words{length_note})"


def self_judge_draft(draft_path: str) -> str:
    """
    Read a saved draft from GitHub and score it on the rubric (0-40).

    Returns a JSON string with:
    - scores per dimension (0-10 each)
    - composite (sum)
    - weakest_dimension
    - top_week_gaps (list of specific missing elements for top/week)
    - improvement_suggestion (exact fix to apply)
    """
    try:
        gh = GitHubClient()
        content = gh.read_file(draft_path)
    except Exception as exc:
        return f"Error reading draft for judging: {exc}"

    if not content:
        return f"Draft not found: {draft_path}"

    try:
        result = LLMClient().complete_json(build_judge_prompt(content), JUDGE_SYSTEM)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error during judging: {exc}"

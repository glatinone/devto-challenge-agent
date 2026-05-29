"""
Writing tools: save drafts to GitHub and self-judge them.

The agent writes article content itself. These tools handle persistence,
anti-pattern scanning, and structured scoring — they don't generate content.
"""

import json
import os
import re
from datetime import date

from core.github_client import GitHubClient
from core.llm import LLMClient
from skills.devto_writer import JUDGE_SYSTEM, build_judge_prompt
from tools.session import is_reconnaissance_done


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

# ── Title validators ───────────────────────────────────────────────────────

# Generic openers that signal zero curiosity gap
_GENERIC_TITLE_RE = re.compile(
    r"^(how (i|to|we|you)\s+|getting started with\b|a guide to\b|"
    r"the (ultimate|complete|comprehensive) guide\b|introduction to\b|"
    r"my (journey|experience|thoughts) (with|on|about)\b|"
    r"top \d+\b|\d+ (best|ways to|tips for|reasons (to|why))\b|"
    r"everything you need to know\b|what is\b|"
    r"exploring\b|an? (beginner'?s?|overview of|deep.?dive into|look at)\b)",
    re.IGNORECASE,
)

# The 5 formula patterns — at least one must be present
_TITLE_FORMULA_PATTERNS = [
    # A: Cost-Benefit Tension — temporal reversal (". Then", ". But")
    re.compile(r"[.!,]\s*(then|but then|until)\b", re.IGNORECASE),
    # B: Day-N Turning Point — specific day/week count
    re.compile(r"\b(\d+\s+days?|day\s+\d+|\d+\s+weeks?|week\s+\d+)\b", re.IGNORECASE),
    # C: Number Shock — dollar amount or percentage in title
    re.compile(r"(\$[\d,]+|\d+[\s-]*%|^\d+\s)", re.IGNORECASE),
    # D: Contrarian — opens with strong claim against convention
    re.compile(r"^(stop\b|never\b|don'?t\b|quit\b|against\b|the case against\b|why you should (stop|never)\b)", re.IGNORECASE),
    # E: Caught-Something — surfaced a hidden issue
    re.compile(r"\b(caught|flagged|spotted|discovered|had missed|went unnoticed|been ignoring)\b", re.IGNORECASE),
    # Bonus: "I Was Wrong" pattern
    re.compile(r"\bi was wrong\b", re.IGNORECASE),
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
    Scan article body AND title for anti-patterns. Returns a list of violation strings.
    Empty list means the draft is clean.

    Hard violations (must fix before publishing):
    - Title is generic (no curiosity gap formula)
    - Title has no formula pattern match (A/B/C/D/E)
    - Title over 80 characters
    - Em dashes in body
    - Structural meta-labels written literally
    - Bullet points in body (outside code fences)
    - Signposting opener in first 300 chars
    - Forbidden filler phrases
    - Soft hook openers
    """
    violations: list[str] = []
    body_lower = body.lower()
    opening = body_lower[:300]

    # 0. Title checks (only if a title was provided)
    if title:
        title_stripped = title.strip()

        # 0a. Length
        if len(title_stripped) > 80:
            violations.append(
                f"[TITLE_TOO_LONG] Title is {len(title_stripped)} chars — max 80. "
                f"Trim without losing the curiosity gap."
            )

        # 0b. Generic opener
        if _GENERIC_TITLE_RE.match(title_stripped):
            violations.append(
                f"[TITLE_GENERIC] '{title_stripped[:70]}' — "
                f"generic opener detected (How I / Getting Started / Guide / Top N). "
                f"Use one of the 5 formula patterns: "
                f"A=Cost-Benefit Tension, B=Day-N Turning Point, C=Number Shock, "
                f"D=Contrarian, E=Caught-Something."
            )

        # 0c. No formula pattern matched — title has no curiosity gap
        elif not any(p.search(title_stripped) for p in _TITLE_FORMULA_PATTERNS):
            violations.append(
                f"[TITLE_NO_FORMULA] '{title_stripped[:70]}' — "
                f"no curiosity gap formula detected. Apply one of: "
                f"A='X. Then Y.' (tension), "
                f"B='N Days / Day N' (turning point), "
                f"C='$X / N%' (number shock), "
                f"D='Stop / Never / Don't' (contrarian), "
                f"E='Caught / Flagged / Missed' (caught-something)."
            )

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
    1. Reconnaissance gate (must call mark_reconnaissance_done first)
    2. Word count check (800 minimum)
    3. Anti-pattern scan (em dashes, labels, bullets, signposting, title formula)
    4. Save if all pass
    """
    # Step 1: reconnaissance gate
    if not is_reconnaissance_done():
        return (
            "DRAFT REJECTED — reconnaissance not completed. "
            "You must call read_feed_article at least 3 times (reading competitor articles), "
            "then call mark_reconnaissance_done(articles_read=N) before writing. "
            "This prevents writing angles that already exist in the feed."
        )

    word_count = len(body_markdown.split())

    # Step 2: word count
    if word_count < _MIN_WORDS:
        shortage = _MIN_WORDS - word_count
        # Diagnose which sections are likely missing based on word count
        missing = []
        if word_count < 200:
            missing.append("HOOK + WHAT I BUILT: barely started — write the opening 2 sections first")
        if word_count < 500:
            missing.append(
                "CODE SECTION (missing or thin): add 2 real code blocks with real imports "
                "and 2-3 sentences of explanation between them — aim for 200+ words here"
            )
        if word_count < 650:
            missing.append(
                "NARRATIVE ARC (missing or thin): add a specific failure moment "
                "(exact timestamp/error/cost) + a specific aha moment — aim for 200+ words here"
            )
        if word_count < 750:
            missing.append(
                "META-LESSON (missing): add the generalizable principle + ONE quotable line "
                "that stands alone without context — aim for 100+ words here"
            )
        if word_count < _MIN_WORDS:
            missing.append(
                "CLOSING QUESTION (missing): dual-prompt + author stake — "
                "'If you had to automate one thing, what would it be — and what would you never automate?'"
            )

        return (
            f"DRAFT REJECTED — {word_count} words, need {_MIN_WORDS}. Missing ~{shortage} words.\n\n"
            f"WRITE THE COMPLETE ARTICLE FRESH in one pass, hitting ALL 6 sections below.\n"
            f"Do NOT patch the previous draft — write the whole thing from the opening sentence.\n\n"
            f"REQUIRED SECTIONS WITH WORD TARGETS (total 800-1200 words):\n"
            f"  1. HOOK (80-100w): Specific moment or number. First sentence must name a real cost,\n"
            f"     failure, or timestamp. NOT 'Have you ever' or 'GitHub is powerful'.\n"
            f"  2. WHAT I BUILT (100-120w): 2-4 sentences naming the tool/workflow plainly.\n"
            f"  3. CODE SECTION (200-250w): TWO real code blocks with real imports and real API\n"
            f"     syntax. 2-3 sentences of explanation between them. No pseudocode.\n"
            f"  4. NARRATIVE ARC (200-250w): One specific failure moment (exact error/cost/timestamp)\n"
            f"     then one aha moment. Real names, real numbers throughout.\n"
            f"  5. META-LESSON (120-150w): The generalizable principle. ONE quotable standalone line.\n"
            f"     ONE bold claim backed by evidence in the article.\n"
            f"  6. CLOSING QUESTION (60-80w): Dual-prompt + author stake.\n"
            f"     'If you had to automate one thing, what would it be — and what would you never\n"
            f"     automate? The most interesting answer I'll build as my next post and credit you.'\n\n"
            f"Write ALL 6 sections now, then call write_and_save_draft."
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

    Uses a SEPARATE judge model (JUDGE_MODEL_NAME env var, default gpt-4o-mini)
    so the writer and judge are different models. A model judging its own output
    is systematically too lenient — a different model provides a more honest score.

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

    # Use a dedicated judge model — separate from the writer model.
    # JUDGE_MODEL_NAME defaults to gpt-4o-mini: faster, cheaper, and less
    # biased toward the output of whatever model wrote the article.
    judge_model = os.getenv("JUDGE_MODEL_NAME", "gpt-4o-mini")
    judge_client = LLMClient(model=judge_model, temperature=0.2)

    try:
        result = judge_client.complete_json(build_judge_prompt(content), JUDGE_SYSTEM)
        result["judge_model"] = judge_model  # log which model judged
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"Error during judging: {exc}"

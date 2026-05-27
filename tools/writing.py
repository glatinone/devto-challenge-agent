"""
Writing tools: save drafts to GitHub and self-judge them.

The agent writes article content itself. These tools handle persistence
and structured scoring — they don't generate content.
"""

import json
from datetime import date

from core.github_client import GitHubClient
from core.llm import LLMClient
from skills.devto_writer import JUDGE_SYSTEM, build_judge_prompt


_MIN_WORDS = 800
_MAX_WORDS = 1200


def write_and_save_draft(
    title: str,
    tags: list[str],
    body_markdown: str,
    article_number: int = 1,
) -> str:
    """
    Save a draft to GitHub at drafts/draft_YYYY-MM-DD_{article_number}.md.

    HARD REQUIREMENT: body_markdown must be 800-1200 words.
    Top/week posts cluster at 800 words. Under 800 is REJECTED.
    Over 1200 is accepted but flagged — depth beats padding.
    """
    word_count = len(body_markdown.split())

    if word_count < _MIN_WORDS:
        return (
            f"DRAFT REJECTED — too short: {word_count} words. "
            f"Minimum is {_MIN_WORDS} words. "
            f"Rewrite with {_MIN_WORDS - word_count} more words of real substance: "
            f"a failure moment, real code, specific numbers, a quotable line. "
            f"Do NOT retry with filler. Do NOT call this tool again until the article "
            f"is at least {_MIN_WORDS} words of actual content."
        )

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

    length_note = f" (over {_MAX_WORDS} — consider trimming for better punch)" if over_limit else ""
    return f"Draft saved to {path} ({word_count} words{length_note})"


def self_judge_draft(draft_path: str) -> str:
    """
    Read a saved draft from GitHub and score it on the rubric (0-40).

    Returns a JSON string with scores per dimension, composite, weakest
    dimension, and a specific improvement suggestion.
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

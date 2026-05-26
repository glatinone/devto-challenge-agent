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


def write_and_save_draft(
    title: str,
    tags: list[str],
    body_markdown: str,
    article_number: int = 1,
) -> str:
    """
    Save a draft to GitHub at drafts/draft_YYYY-MM-DD_{article_number}.md.

    The agent provides the complete article body. This tool adds frontmatter
    and persists the file. Call with article_number=1 for first article,
    article_number=2 for second, etc.
    """
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

    return f"Draft saved to {path} ({len(body_markdown.split())} words)"


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

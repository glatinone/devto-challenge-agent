"""
PublishAgent: Publish an approved draft to dev.to.

Triggered when Kiel closes a "needs-review" issue. Reads the draft path
from the issue body, fetches the draft from GitHub, POSTs to dev.to API,
and records the result in published/published_log.json.

No LLM. The draft is published as-is — any revisions Kiel wants should
be made by editing the draft file directly in GitHub before closing the issue.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from core.github_client import GitHubClient
from core.state import PipelineState

_DEVTO_API_BASE = "https://dev.to/api"
_PUBLISHED_LOG_PATH = "published/published_log.json"


def _extract_draft_path(issue_body: str) -> Optional[str]:
    """Parse the draft file path from the issue body written by WriterAgent."""
    m = re.search(r"`(drafts/draft_[\d-]+\.md)`", issue_body)
    return m.group(1) if m else None


def _parse_frontmatter(content: str) -> tuple[str, list[str], str]:
    """Return (title, tags, body_markdown) from a draft with YAML frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not m:
        return "", [], content.strip()

    frontmatter = m.group(1)
    body = m.group(2).strip()

    title_m = re.search(r"^title:\s*(.+)$", frontmatter, re.MULTILINE)
    tags_m = re.search(r"^tags:\s*(.+)$", frontmatter, re.MULTILINE)

    title = title_m.group(1).strip() if title_m else ""
    tags_raw = tags_m.group(1).strip().strip("[]") if tags_m else ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    return title, tags, body


def _already_published(gh: GitHubClient, draft_path: str) -> bool:
    """Check published log to avoid double-publishing."""
    raw = gh.read_file(_PUBLISHED_LOG_PATH)
    if not raw:
        return False
    try:
        log: list[dict] = json.loads(raw)
        return any(entry.get("draft_path") == draft_path for entry in log)
    except json.JSONDecodeError:
        return False


def _publish_to_devto(
    title: str, body: str, tags: list[str], api_key: str
) -> dict:
    payload = {
        "article": {
            "title": title,
            "body_markdown": body,
            "published": True,
            "tags": tags[:4],  # dev.to allows max 4 tags
        }
    }
    response = requests.post(
        f"{_DEVTO_API_BASE}/articles",
        json=payload,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _update_published_log(gh: GitHubClient, entry: dict) -> None:
    raw = gh.read_file(_PUBLISHED_LOG_PATH)
    try:
        log: list[dict] = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        log = []
    log.append(entry)
    gh.commit_file(
        path=_PUBLISHED_LOG_PATH,
        content=json.dumps(log, indent=2, ensure_ascii=False),
        message=f"feat: published — {entry['title'][:60]}",
    )


def run(state: PipelineState) -> PipelineState:
    api_key = os.getenv("DEVTO_API_KEY", "").strip()
    if not api_key:
        state.add_error("PublishAgent", "DEVTO_API_KEY is not set")
        return state

    issue_body = os.getenv("ISSUE_BODY", "").strip()
    if not issue_body:
        state.add_error("PublishAgent", "ISSUE_BODY env var is empty")
        return state

    draft_path = _extract_draft_path(issue_body)
    if not draft_path:
        state.add_error(
            "PublishAgent", "Could not extract draft path from issue body"
        )
        return state

    try:
        gh = GitHubClient()
    except Exception as exc:
        state.add_error("PublishAgent", f"GitHub client init failed: {exc}")
        return state

    # Idempotency check
    if _already_published(gh, draft_path):
        state.add_error(
            "PublishAgent", f"Already published: {draft_path} — skipping"
        )
        return state

    # Read draft
    draft_content = gh.read_file(draft_path)
    if not draft_content:
        state.add_error("PublishAgent", f"Draft file not found: {draft_path}")
        return state

    title, tags, body = _parse_frontmatter(draft_content)
    if not title or not body:
        state.add_error(
            "PublishAgent", f"Could not parse frontmatter from {draft_path}"
        )
        return state

    # Publish
    try:
        result = _publish_to_devto(title, body, tags, api_key)
    except requests.HTTPError as exc:
        state.add_error("PublishAgent", f"dev.to API error: {exc}")
        return state
    except requests.RequestException as exc:
        state.add_error("PublishAgent", f"Network error publishing to dev.to: {exc}")
        return state

    published_url = result.get("url", "")
    article_id = result.get("id", "")

    print(f"[publish] Published: {published_url}")

    # Update log — non-fatal if this fails (article is already live)
    try:
        _update_published_log(
            gh,
            {
                "id": article_id,
                "title": title,
                "url": published_url,
                "draft_path": draft_path,
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        state.add_error(
            "PublishAgent",
            f"Failed to update published log (article IS live at {published_url}): {exc}",
        )

    return state

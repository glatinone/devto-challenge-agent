"""
Backlog tools: manage the topic backlog for freeform (non-challenge) writing.

When no active challenge is found, the morning agent pulls from here instead
of stopping. The evening agent refills the backlog with underexplored angles
it discovers in the challenge feed. The backlog is self-sustaining.
"""

import json
from datetime import date, datetime, timezone

from core.github_client import GitHubClient

_BACKLOG_PATH = "data/backlog.json"


def read_backlog() -> str:
    """
    Return the current topic backlog.

    Call this when no active challenge is found. Pick the first (or most
    relevant) topic, then call pop_topic to claim it before writing.
    """
    try:
        gh = GitHubClient()
        raw = gh.read_file(_BACKLOG_PATH)
    except Exception as exc:
        return f"Error reading backlog: {exc}"

    if not raw:
        return (
            "Backlog is empty. No topics available for freeform writing. "
            "Consider writing about a recent engineering experience or tool you've used this week."
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "Backlog file is malformed. Write a freeform article on any senior-engineer topic."

    topics = data.get("topics", [])
    if not topics:
        return (
            "Backlog is empty. No topics available for freeform writing. "
            "Write about a real engineering experience from the past month."
        )

    lines = [f"Topic backlog ({len(topics)} available):\n"]
    for t in topics[:10]:
        tags = ", ".join(t.get("tags", [])) or "no tags yet"
        notes = f" — {t['notes']}" if t.get("notes") else ""
        lines.append(f'  [{t["id"]}] "{t["title"]}" [{tags}]{notes}')

    lines.append("\nCall pop_topic to claim the first topic before writing.")
    return "\n".join(lines)


def pop_topic() -> str:
    """
    Claim and remove the first topic from the backlog.

    Call this ONCE per freeform run, right before writing the article.
    Removes the topic so the next run gets a fresh one. Returns the full
    topic details to use as writing guidance.
    """
    try:
        gh = GitHubClient()
        raw = gh.read_file(_BACKLOG_PATH)
        if not raw:
            return "Backlog is empty. Cannot pop topic."

        data = json.loads(raw)
        topics = data.get("topics", [])
        if not topics:
            return "Backlog is empty. Cannot pop topic."

        topic = topics.pop(0)
        data["topics"] = topics
        data["last_popped_at"] = datetime.now(timezone.utc).isoformat()

        gh.commit_file(
            _BACKLOG_PATH,
            json.dumps(data, indent=2),
            f"data: pop topic — {topic['title'][:55]}",
        )

        tags = ", ".join(topic.get("tags", [])) or "choose relevant tags"
        notes = topic.get("notes", "none")
        return (
            f"Topic claimed: \"{topic['title']}\"\n"
            f"Suggested tags: {tags}\n"
            f"Notes: {notes}\n"
            f"Backlog remaining: {len(topics)} topics"
        )
    except Exception as exc:
        return f"Error popping topic: {exc}"


def add_topics(topics: list[str]) -> str:
    """
    Add new topic ideas to the backlog.

    The evening agent calls this after analyzing the challenge feed to add
    underexplored angles for future freeform use. Each string in topics is
    a plain-language description of the angle — the morning agent will
    develop it into a full article when it pops the topic.

    topics: list of angle descriptions, e.g.
      ["What happens when GitHub Actions rate-limits your deploy at midnight",
       "The one config line I missed that doubled my CI costs"]
    """
    if not topics:
        return "No topics provided."

    try:
        gh = GitHubClient()
        raw = gh.read_file(_BACKLOG_PATH)
        data = json.loads(raw) if raw else {"topics": []}

        existing_titles = {t["title"].lower() for t in data.get("topics", [])}
        all_ids = [t.get("id", 0) for t in data.get("topics", [])]
        next_id = max(all_ids, default=0) + 1

        added = 0
        for topic_str in topics:
            if topic_str.lower() not in existing_titles:
                data.setdefault("topics", []).append({
                    "id": next_id,
                    "title": topic_str,
                    "tags": [],
                    "notes": "",
                    "added_at": date.today().isoformat(),
                })
                existing_titles.add(topic_str.lower())
                added += 1
                next_id += 1

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        gh.commit_file(
            _BACKLOG_PATH,
            json.dumps(data, indent=2),
            f"data: add {added} topic(s) to backlog",
        )
        return f"Added {added} topic(s). Backlog total: {len(data['topics'])}"
    except Exception as exc:
        return f"Error adding topics: {exc}"

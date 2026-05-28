"""
Session state: in-process flags that tools share within a single agent run.

This module uses Python module-level state — it resets automatically with
each fresh process (each GitHub Actions job). No files, no GitHub API calls.

Used to enforce workflow ordering:
- Reconnaissance must be completed before write_and_save_draft is allowed.
"""

_state: dict = {
    "recon_done": False,
    "recon_count": 0,
    "freeform_mode": False,  # True when running without an active challenge
}


def reset_session() -> None:
    """Call at the start of each pipeline run to ensure clean state."""
    _state["recon_done"] = False
    _state["recon_count"] = 0
    _state["freeform_mode"] = False


def mark_reconnaissance_done(articles_read: int) -> str:
    """
    Signal that reconnaissance is complete. Call this AFTER reading at least
    3 competitor articles with read_feed_article — before calling write_and_save_draft.

    articles_read: how many full articles you read via read_feed_article.
    """
    if articles_read < 3:
        return (
            f"RECONNAISSANCE INCOMPLETE — you read {articles_read} article(s), "
            f"minimum is 3. Call read_feed_article for at least {3 - articles_read} more "
            f"article(s) from the feed before marking done."
        )
    _state["recon_done"] = True
    _state["recon_count"] = articles_read
    return (
        f"Reconnaissance marked complete. {articles_read} articles read. "
        f"You may now call write_and_save_draft."
    )


def set_freeform_mode() -> None:
    """Mark this run as freeform (no active challenge). Skips recon gate."""
    _state["freeform_mode"] = True
    _state["recon_done"] = True  # freeform doesn't need competitor recon


def is_reconnaissance_done() -> bool:
    """True if reconnaissance is complete or freeform mode is active."""
    return _state["recon_done"]


def get_recon_count() -> int:
    return _state["recon_count"]

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChallengeStatus(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class Article(BaseModel):
    title: str
    url: str
    author: str
    tags: list[str] = Field(default_factory=list)
    reactions: int = 0
    comments_count: int = 0
    reading_time_minutes: int = 0
    published_at: str = ""
    description: Optional[str] = None


class IdeaCandidate(BaseModel):
    rank: int
    title: str
    angle: str
    gap_reasoning: str
    estimated_score: int = 0


class DraftResult(BaseModel):
    title: str
    content: str  # full markdown including frontmatter
    tags: list[str] = Field(default_factory=list)
    score: int = 0  # self-judged composite (0-40)
    draft_path: str = ""


class PerformanceMetrics(BaseModel):
    article_url: str
    title: str
    author: str
    reactions: int = 0
    comments_count: int = 0
    captured_at: str = ""


class PipelineState(BaseModel):
    # Set by orchestrator before first agent
    run_date: Optional[date] = None
    challenge_url: Optional[str] = None

    # Set by MonitorAgent
    challenge_status: Optional[ChallengeStatus] = None
    challenge_title: Optional[str] = None

    # Set by ReconAgent
    articles: list[Article] = Field(default_factory=list)

    # Set by AnalystAgent
    idea_candidates: list[IdeaCandidate] = Field(default_factory=list)
    selected_idea: Optional[IdeaCandidate] = None

    # Set by WriterAgent
    draft: Optional[DraftResult] = None
    github_issue_url: Optional[str] = None

    # Set by ScraperAgent / PerformanceAgent
    performance_metrics: list[PerformanceMetrics] = Field(default_factory=list)

    # Error tracking: {agent_name: [messages]}
    errors: dict[str, list[str]] = Field(default_factory=dict)

    def add_error(self, agent: str, message: str) -> None:
        self.errors.setdefault(agent, []).append(message)

    def should_continue(self) -> bool:
        return self.challenge_status != ChallengeStatus.CLOSED

    def summary(self) -> str:
        draft_info = (
            f"yes (score={self.draft.score}/40)" if self.draft else "no"
        )
        lines = [
            f"Run date:         {self.run_date}",
            f"Challenge status: {self.challenge_status}",
            f"Articles fetched: {len(self.articles)}",
            f"Idea candidates:  {len(self.idea_candidates)}",
            f"Draft:            {draft_info}",
            f"GitHub issue:     {self.github_issue_url or 'none'}",
        ]
        if self.errors:
            lines.append(f"Errors:           {self.errors}")
        return "\n".join(lines)

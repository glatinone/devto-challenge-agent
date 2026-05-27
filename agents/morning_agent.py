"""
Morning Agent: autonomously write 2 competitive dev.to challenge articles.

The LLM decides the full workflow: which angles to pursue, when to revise,
how to sequence the two articles. Python only provides tools and a goal.
"""

from core.agent_loop import AgentLoop, Tool
from skills.devto_writer import STYLE_RULES, RUBRIC
from tools.challenge import find_current_challenge, fetch_challenge_feed
from tools.github_tools import request_human_review, save_challenge_state
from tools.memory import read_memory, update_memory
from tools.writing import self_judge_draft, write_and_save_draft

_PASSING_SCORE = 28

SYSTEM_PROMPT = f"""You are an autonomous dev.to challenge agent. Your mission is to publish \
articles that win top/week. You write in first person, with strong opinions and real numbers.

{STYLE_RULES}

Scoring rubric (0-10 each, need 28+ composite to pass):
{chr(10).join(f"- {dim}: {info['description']}" for dim, info in RUBRIC.items())}

You will complete the full workflow autonomously using your tools. Think through each \
decision. When you judge an article and it scores below {_PASSING_SCORE}, rewrite and \
save it again — you already know the content and what to improve.
"""

GOAL = f"""Today's task: write 2 competitive articles for the open dev.to challenge.

CRITICAL RULES — read before starting:
- Every article MUST be 900-1400 words. The tool will REJECT anything under 900.
- Score < {_PASSING_SCORE}/40 means you MUST rewrite immediately — no exceptions.
- Never publish a draft that was rejected for word count or scored below {_PASSING_SCORE}.
- Write like a senior developer who lived through this problem, not like a tutorial.

Workflow:
1. Call find_current_challenge — get the active challenge URL and title
2. Save the challenge state with save_challenge_state
3. Fetch the challenge feed — understand what angles are already covered (avoid repeats)
4. Read memory — avoid saturated angles, lean into performing patterns
5. For EACH of 2 unique articles (article_number=1, then article_number=2):
   a. Choose a specific angle that fills a real gap in the feed
   b. Write the COMPLETE article body — minimum 900 words, no bullet points, no em dashes.
      Start with a hook that names a real problem with real stakes.
      Include specific numbers, real examples, and at least one counterintuitive insight.
   c. Call write_and_save_draft — if it returns REJECTED, immediately rewrite with more depth
   d. Call self_judge_draft — read the score carefully
   e. If composite < {_PASSING_SCORE} OR improvement_suggestion starts with "REWRITE:":
      rewrite the article (same article_number), save again, judge again
   f. Call request_human_review with the final score and breakdown
6. Update memory with feed observations
7. Summarize: what angles you chose, final scores, and why they're competitive

If no open challenge is found, explain the failure and stop."""


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="find_current_challenge",
            description=(
                "Find the currently active dev.to challenge. "
                "Tries scraping dev.to/challenges, then falls back to searching "
                "devteam's recent article announcements via API. "
                "Returns: 'Active challenge: <title> at <url>' or a failure message."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            func=find_current_challenge,
        ),
        Tool(
            name="save_challenge_state",
            description="Persist the challenge URL and title so the evening agent can find it.",
            parameters={
                "type": "object",
                "properties": {
                    "challenge_url": {"type": "string"},
                    "challenge_title": {"type": "string"},
                },
                "required": ["challenge_url", "challenge_title"],
            },
            func=save_challenge_state,
        ),
        Tool(
            name="fetch_challenge_feed",
            description="Fetch the top articles from the challenge feed (last 7 days). Returns list with reactions, author, tags.",
            parameters={
                "type": "object",
                "properties": {
                    "challenge_url": {"type": "string", "description": "e.g. https://dev.to/challenges/ai"},
                    "per_page": {"type": "integer", "default": 50},
                },
                "required": ["challenge_url"],
            },
            func=fetch_challenge_feed,
        ),
        Tool(
            name="read_memory",
            description="Read the angle memory: saturated angles to avoid and performing patterns to lean into.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=read_memory,
        ),
        Tool(
            name="write_and_save_draft",
            description=(
                "Save an article draft to GitHub. You provide the complete body_markdown. "
                "Use article_number=1 for first article, 2 for second. "
                "Calling again with the same article_number overwrites the previous draft."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                    "body_markdown": {"type": "string", "description": "Full article body, no frontmatter"},
                    "article_number": {"type": "integer", "enum": [1, 2]},
                },
                "required": ["title", "tags", "body_markdown", "article_number"],
            },
            func=write_and_save_draft,
        ),
        Tool(
            name="self_judge_draft",
            description="Score a saved draft on the rubric (Creativity, Technical, Writing Quality, Knowledge). Returns JSON with scores and improvement suggestion.",
            parameters={
                "type": "object",
                "properties": {
                    "draft_path": {"type": "string", "description": "e.g. drafts/draft_2026-05-26_1.md"},
                },
                "required": ["draft_path"],
            },
            func=self_judge_draft,
        ),
        Tool(
            name="request_human_review",
            description="Open a GitHub Issue for Kiel to review. Kiel closes it to approve publishing.",
            parameters={
                "type": "object",
                "properties": {
                    "draft_path": {"type": "string"},
                    "title": {"type": "string"},
                    "score": {"type": "integer"},
                    "angle": {"type": "string"},
                    "score_breakdown": {"type": "string", "description": "Human-readable score breakdown"},
                },
                "required": ["draft_path", "title", "score", "angle", "score_breakdown"],
            },
            func=request_human_review,
        ),
        Tool(
            name="update_memory",
            description="Update the angle memory with today's observations from the feed.",
            parameters={
                "type": "object",
                "properties": {
                    "saturated_angles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Angles now oversaturated in the feed",
                    },
                    "performing_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns that drive high reactions",
                    },
                    "brief": {
                        "type": "string",
                        "description": "2-3 sentence brief for tomorrow's agent",
                    },
                },
                "required": ["saturated_angles", "performing_patterns", "brief"],
            },
            func=update_memory,
        ),
    ]


def run() -> str:
    agent = AgentLoop(tools=build_tools(), system=SYSTEM_PROMPT, max_iterations=60)
    return agent.run(GOAL)

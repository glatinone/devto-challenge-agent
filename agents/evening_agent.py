"""
Evening Agent: analyze today's article performance and update memory.

The LLM decides how to interpret the metrics, what patterns to record,
and how to frame the brief for tomorrow's morning agent.
"""

from core.agent_loop import AgentLoop, Tool
from tools.backlog import add_topics
from tools.challenge import fetch_recent_published_metrics, fetch_today_metrics, read_feed_article
from tools.github_tools import load_challenge_state
from tools.memory import read_memory, update_memory, update_voice_fingerprint

SYSTEM_PROMPT = """You are a performance analyst for a competitive dev.to challenge agent.

Your job: look at today's article data, understand what drove high reactions, \
and update the memory so tomorrow's agent can write better articles.

Be specific. "Benchmarks with real numbers drove engagement" beats "good content performed well." \
Identify actual patterns: opening hooks, article length, technical depth, personal story elements, \
angle uniqueness. Look for what differentiates the top 3 articles from the rest.
"""

GOAL = """Today's task: analyze performance, update memory, and prepare tomorrow's pipeline.

Workflow:
1. Load the stored challenge state to find today's challenge URL
2. Fetch today's challenge feed metrics (what is performing in the feed right now)
3. Fetch recent published metrics — check Kiel's OWN articles from the last 3 days:
   — These articles needed 24-48h to accumulate real reactions
   — If any article has 5+ reactions, it is a HIGH PERFORMER
4. Read current memory for context
5. Analyze:
   — In the challenge feed: what hooks, title formulas, angles drove highest reactions?
   — What angles are overcrowded (3+ articles on same topic)?
   — What underexplored angles exist nobody wrote about?
6. Update memory with your findings (saturated_angles, performing_patterns, brief)
7. For each HIGH PERFORMER from step 3:
   — Call read_feed_article(article_id) to retrieve the body
   — Extract: first sentence (hook), one quotable line that stands alone
   — Identify which title formula (A/B/C/D/E) was used
   — Call update_voice_fingerprint with those details
   — This builds Kiel's voice fingerprint from REAL performance data, not guesses
8. Identify 2-3 underexplored angles from the feed:
   — Call add_topics with those angles as plain-language descriptions
9. Summarize: feed patterns, Kiel's article performance, voice fingerprint updated (yes/no),
   topics added to backlog

Be honest. If all reactions are low, say so. Don't pad the brief with optimism."""


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="load_challenge_state",
            description="Load the stored challenge URL from this morning's run.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=load_challenge_state,
        ),
        Tool(
            name="fetch_today_metrics",
            description="Fetch articles published today with their reaction and comment counts.",
            parameters={
                "type": "object",
                "properties": {
                    "challenge_url": {"type": "string"},
                },
                "required": ["challenge_url"],
            },
            func=fetch_today_metrics,
        ),
        Tool(
            name="fetch_recent_published_metrics",
            description=(
                "Fetch current reaction counts for Kiel's articles published in the last 3 days. "
                "Call this every evening — reactions take 24-48h to accumulate so yesterday's "
                "articles now have honest data. Flags high performers (5+ reactions) for "
                "voice fingerprint update."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            func=fetch_recent_published_metrics,
        ),
        Tool(
            name="read_feed_article",
            description=(
                "Read the full body of a single article by its dev.to article ID. "
                "Use this to extract the hook and quotable line from a high-performing article "
                "before calling update_voice_fingerprint."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "dev.to article ID"},
                },
                "required": ["article_id"],
            },
            func=read_feed_article,
        ),
        Tool(
            name="read_memory",
            description="Read current angle memory for context.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=read_memory,
        ),
        Tool(
            name="update_memory",
            description="Update memory with today's performance insights.",
            parameters={
                "type": "object",
                "properties": {
                    "saturated_angles": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "performing_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "brief": {
                        "type": "string",
                        "description": "2-3 sentence summary for tomorrow's morning agent",
                    },
                },
                "required": ["saturated_angles", "performing_patterns", "brief"],
            },
            func=update_memory,
        ),
        Tool(
            name="update_voice_fingerprint",
            description=(
                "Record voice patterns from an article that performed well (5+ reactions). "
                "Saves approved hooks, quotable lines, and title formula for tomorrow's agent. "
                "Call this when a top-performing article has a strong hook or quotable line."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "approved_hooks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "First sentence(s) from the performing article",
                    },
                    "quotable_lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lines that stand alone without context (screenshot-worthy)",
                    },
                    "formula_used": {
                        "type": "string",
                        "description": "Which title pattern was used: A, B, C, D, or E",
                    },
                    "formula_example": {
                        "type": "string",
                        "description": "The actual title of the performing article",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional: what specifically made this sound authentic vs AI-generated",
                    },
                },
                "required": ["approved_hooks", "quotable_lines", "formula_used", "formula_example"],
            },
            func=update_voice_fingerprint,
        ),
        Tool(
            name="add_topics",
            description=(
                "Add underexplored topic ideas to the freeform backlog. "
                "Call this with 2-3 angles nobody wrote about today — "
                "the morning agent will use these when no challenge is active."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Plain-language angle descriptions, e.g. 'What happens when GitHub Actions rate-limits your deploy at 2am'",
                    },
                },
                "required": ["topics"],
            },
            func=add_topics,
        ),
    ]


def run() -> str:
    agent = AgentLoop(tools=build_tools(), system=SYSTEM_PROMPT, max_iterations=20)
    return agent.run(GOAL)

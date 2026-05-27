"""
Evening Agent: analyze today's article performance and update memory.

The LLM decides how to interpret the metrics, what patterns to record,
and how to frame the brief for tomorrow's morning agent.
"""

from core.agent_loop import AgentLoop, Tool
from tools.backlog import add_topics
from tools.challenge import fetch_today_metrics
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
2. Fetch today's article metrics
3. Read current memory for context
4. Analyze the data:
   — What hooks, title formulas, and angles drove the highest reactions?
   — What angles are now overcrowded (3+ articles on same topic)?
   — What underexplored angles exist that nobody has written about yet?
5. Update memory with your findings (saturated_angles, performing_patterns, brief)
6. If any article in today's feed scored 5+ reactions AND used a strong hook or quotable line:
   — Call update_voice_fingerprint with that article's opening sentence, a quotable line
     from it (if visible), the title formula it used (A/B/C/D/E), and the actual title.
   — This builds Kiel's voice fingerprint so tomorrow's agent writes with proven patterns.
7. Identify 2-3 underexplored angles from the feed that nobody wrote about today:
   — Call add_topics with those angles as plain-language descriptions.
   — These become tomorrow's freeform backlog if no challenge is active.
8. Summarize: top article patterns, voice fingerprint updated (yes/no), topics added to backlog

Be honest about what the data shows. If reactions are all low, say so — don't pad the brief."""


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

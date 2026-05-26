"""
Evening Agent: analyze today's article performance and update memory.

The LLM decides how to interpret the metrics, what patterns to record,
and how to frame the brief for tomorrow's morning agent.
"""

from core.agent_loop import AgentLoop, Tool
from tools.challenge import fetch_today_metrics
from tools.github_tools import load_challenge_state
from tools.memory import read_memory, update_memory

SYSTEM_PROMPT = """You are a performance analyst for a competitive dev.to challenge agent.

Your job: look at today's article data, understand what drove high reactions, \
and update the memory so tomorrow's agent can write better articles.

Be specific. "Benchmarks with real numbers drove engagement" beats "good content performed well." \
Identify actual patterns: opening hooks, article length, technical depth, personal story elements, \
angle uniqueness. Look for what differentiates the top 3 articles from the rest.
"""

GOAL = """Today's task: analyze performance and update memory for tomorrow.

Workflow:
1. Load the stored challenge state to find today's challenge URL
2. Fetch today's article metrics
3. Read current memory for context
4. Analyze the data: what patterns drove high reactions? What angles flooded the feed?
5. Update memory with your findings
6. Summarize what you found and what tomorrow's agent should focus on

Be honest about what the data shows. If nothing stood out today, say so."""


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
    ]


def run() -> str:
    agent = AgentLoop(tools=build_tools(), system=SYSTEM_PROMPT, max_iterations=20)
    return agent.run(GOAL)

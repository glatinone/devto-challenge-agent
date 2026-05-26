"""
Dev.to Writer Skill: Prompt templates, rubric, and style guide for competitive articles.

Port of Kiel's writing methodology. All WriterAgent LLM prompts live here.
"""

# ── Style ──────────────────────────────────────────────────────────────────

STYLE_RULES = """
Writing style rules (non-negotiable):
- First person, opinionated. "I think X is wrong" not "X has tradeoffs."
- Specific over abstract. "It took 3.2 seconds" not "it was slow."
- Real numbers wherever possible. Benchmark it, measure it, count it.
- Self-deprecating humor in moderation — once or twice per article, max.
- No em dashes. Use commas, periods, colons, or parentheses instead.
- Never open with "let's dive in", "in this article", or "without further ado."
- No bullet points in the body — prose only.
- No generic positive endings like "X is a great tool, give it a try!"
- Hook the reader in the first two sentences. State the problem with stakes.
- Target length: 900–1400 words.
""".strip()

# ── Rubric ─────────────────────────────────────────────────────────────────

RUBRIC = {
    "creativity": {
        "description": "Fresh angle, unexpected take, not a tutorial rehash",
        "high": "Angle no one in the feed covers. Counterintuitive or surprising.",
        "low": "Generic tutorial, 'getting started', or listicle comparison.",
    },
    "technical_execution": {
        "description": "Code quality, accuracy, practical implementation",
        "high": "Working code with real benchmarks. Handles edge cases. Production-grade.",
        "low": "Pseudo-code, hello world examples, or inaccurate claims.",
    },
    "writing_quality": {
        "description": "Voice, flow, zero AI writing patterns",
        "high": "Reads like a person. Opinionated. Specific. No em dashes or AI filler.",
        "low": "Passive voice, bullet points in body, filler phrases, sounds like GPT.",
    },
    "wealth_of_knowledge": {
        "description": "Depth, real-world insights, beyond the obvious",
        "high": "Shows lived experience. Counterexamples. Non-obvious insights.",
        "low": "Surface-level. Restates the docs. No original insight.",
    },
}

PASSING_SCORE = 28  # minimum composite before publishing without revision

# ── System prompts ─────────────────────────────────────────────────────────

DRAFT_SYSTEM = f"""You are a competitive dev.to author writing to win top/week in a challenge.
You write in Kiel's voice: direct, opinionated, specific, sometimes self-deprecating.

{STYLE_RULES}"""

JUDGE_SYSTEM = """You are a strict rubric judge scoring a dev.to article.
Be harsh. A score above 8 in any dimension requires exceptional quality.
Most AI-generated text scores 5-6 in writing_quality by default — penalize patterns."""

REVISION_SYSTEM = DRAFT_SYSTEM

# ── Prompt builders ────────────────────────────────────────────────────────

def build_draft_prompt(idea_title: str, angle: str, gap_reasoning: str) -> str:
    return f"""Write a full dev.to article for this idea:

Title: {idea_title}
Angle: {angle}
Why this gap exists: {gap_reasoning}

Return the complete article in this exact format (frontmatter + body):

---
title: {idea_title}
tags: tag1, tag2, tag3, tag4
---

[Article body starts here. First paragraph hooks the reader immediately.]"""


def build_judge_prompt(content: str) -> str:
    rubric_text = "\n".join(
        f"- {dim} (0-10): {info['description']}"
        for dim, info in RUBRIC.items()
    )
    return f"""Score this dev.to article on 4 dimensions:

{rubric_text}

Article:
---
{content}
---

Return JSON:
{{
  "creativity": 7,
  "technical_execution": 8,
  "writing_quality": 6,
  "wealth_of_knowledge": 7,
  "composite": 28,
  "weakest_dimension": "writing_quality",
  "improvement_suggestion": "One specific, actionable change to raise the weakest dimension."
}}"""


def build_revision_prompt(
    content: str, score: int, weakest: str, suggestion: str
) -> str:
    return f"""This article scored {score}/40. The weakest dimension is "{weakest}".
Specific improvement: {suggestion}

Revise the article to address this. Keep the title, angle, and structure intact.
Only strengthen the weakest dimension. Do not add bullet points or change the core argument.

Original article:
---
{content}
---

Return the full revised article in the same format (frontmatter + body)."""

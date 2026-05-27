"""
Morning Agent: autonomously write 2 competitive dev.to challenge articles.

The LLM decides the full workflow: which angles to pursue, when to revise,
how to sequence the two articles. Python only provides tools and a goal.
"""

from core.agent_loop import AgentLoop, Tool
from skills.devto_writer import STYLE_RULES, RUBRIC, TOP_WEEK_SCORE
from tools.challenge import find_current_challenge, fetch_challenge_feed, read_feed_article
from tools.github_tools import request_human_review, save_challenge_state
from tools.memory import read_memory, update_memory
from tools.writing import self_judge_draft, write_and_save_draft

_PASSING_SCORE = 30   # 30+ = solid. 32+ = top/week candidate. Target 32.

SYSTEM_PROMPT = f"""You are an autonomous dev.to challenge agent. You write like a principal \
engineer with 15+ years of production experience — someone who has shipped to production, \
watched it break at 2am, and adjusted their opinions accordingly.

Your articles do not explain tools. They explain what you learned when the tool did not work \
the way the docs said it would. Every article contains: one "I was wrong about X" moment, \
one specific failure with a real cost or real number, and at least one insight that cannot \
be found in any official documentation. These are non-negotiable.

{STYLE_RULES}

Scoring rubric (0-10 each, need {_PASSING_SCORE}+ to pass, target {TOP_WEEK_SCORE}+ for top/week):
{chr(10).join(f"- {dim}: {info['description']}" for dim, info in RUBRIC.items())}

When an article scores below {_PASSING_SCORE}, apply the improvement_suggestion immediately \
and save the revision. No explanation. No commentary. Just fix it and save.
"""

GOAL = f"""Today's task: write 2 competitive articles for the open dev.to challenge.
Target: composite score {TOP_WEEK_SCORE}/40 or above (top/week candidate tier).

HARD CONSTRAINTS:
- write_and_save_draft rejects under 800 words. Do not retry with thin content — write more.
- Score < {_PASSING_SCORE}/40 means REWRITE immediately. No exceptions.
- Never call request_human_review on any draft below {_PASSING_SCORE}.

BEFORE WRITING — PICK A TITLE USING ONE OF THESE FORMULAS:
  A. Cost-Benefit Tension: "Tool X Saved Me Y Hours. Then It Burned $Z in 72 Hours."
  B. Day-N Turning Point: "I Used X for 7 Days. Something Changed on Day 4."
  C. Number Shock: "$0.42 Found a Bug My Team Had Ignored for 9 Days."
  D. Contrarian (only if you have evidence): "Stop Using X Like Y. Here's Why."
  E. Caught-Something: "I Built X. On Day 4 It Caught Something I Had Missed for Weeks."
Title must be under 80 characters, no em dashes, creates a curiosity gap.

HOW TO WRITE EACH ARTICLE — READ THIS CAREFULLY:

WARNING: The numbered elements below are INSTRUCTIONS FOR YOU, not labels to write in
the article. Do NOT write "**Hook**:" or "### What I Built" or "## The Conflict" in the
article body. Write PROSE directly. The article must look like a published blog post,
not a filled-in template. The scanner will REJECT any article with structural labels.

The 6 elements your article must CONTAIN (write as seamless prose, not labeled sections):

  First paragraph: Open with a specific moment, failure, or number that creates urgency.
  Use Specific Moment + Reversal (strongest): vivid moment → emotional peak → reversal.
  Example: "My deploy pipeline reported 3 failures at 8 AM Sunday. I felt like a genius.
  By evening I'd checked the bill and the feeling was gone."
  First sentence must be specific — NOT "GitHub is a powerful platform" or "Have you ever".

  Second section (no label): 2-4 sentences stating what you built/tested, plainly.

  Third section (no label): Two real code blocks. Real imports, real APIs, not pseudocode.
  2-3 sentences of explanation between them.

  Fourth section (no label): Narrative arc — frustration, then breakthrough.
  One specific failure moment. One specific aha moment. Real names, real numbers.

  Fifth section (no label): The generalizable principle — what this means beyond this story.
  Write ONE sentence that stands alone without context (quotable, screenshot-worthy).
  Write ONE bold/controversial statement backed by evidence in the article.

  Final paragraph: Closing question with dual-prompt + author stake.
  "If you had to automate one thing, what would it be — and what would you never automate?
  The most interesting answer I'll build as my next post and credit you."

PRE-SAVE CHECKLIST (check every item before calling write_and_save_draft):
  [ ] Title uses one of the 5 formula patterns and has a curiosity gap
  [ ] First sentence is a specific moment, number, or direct claim (NOT a setup)
  [ ] At least one "I was wrong about X" moment
  [ ] Real numbers throughout (no "reasonable", "manageable", "a bit faster")
  [ ] Every code block uses real imports and real API syntax
  [ ] ONE quotable line present (could be screenshot-shared standalone)
  [ ] Closing question uses dual-prompt + author stake
  [ ] ZERO em dashes
  [ ] ZERO bullet points in body (convert to prose)
  [ ] ZERO rule-of-three adjective stacks ("fast, reliable, scalable" — pick one or two)
  [ ] ZERO negative parallelism ("not just X; it's Y")
  [ ] ZERO signposting ("let's dive in", "in this article", "without further ado")
  [ ] 800-1200 words

JUDGE INTERPRETATION:
  {TOP_WEEK_SCORE}+ = top/week candidate. Move to request_human_review.
  {_PASSING_SCORE}-{TOP_WEEK_SCORE-1} = solid. Apply one fix from top_week_gaps, save, judge again.
  <{_PASSING_SCORE} = apply improvement_suggestion immediately. Rewrite. Judge again.
  improvement_suggestion starts with "REWRITE:" = rebuild the full article, same angle.

Workflow:
1. Call find_current_challenge — get the active challenge URL and title
2. Save the challenge state with save_challenge_state
3. Fetch the challenge feed — get titles, reactions, and article IDs of top posts
4. Read the top 3-5 articles in FULL using read_feed_article (use IDs from feed output).
   For each article note: the hook style used, the angle taken, code shown, the conclusion drawn.
   This is reconnaissance — you need to know EXACTLY what's already been written, not just topics.
5. Read memory — avoid saturated angles, lean into performing patterns
6. For EACH of 2 unique articles (article_number=1, then article_number=2):
   a. Choose an angle that fills a real gap in what you just read. The angle must NOT overlap
      with any article you read in step 4. Pick the angle a senior dev would stop scrolling for.
      Run through the title formulas — which creates the most irresistible curiosity gap?
   b. Write the complete article following all 6 elements. Run the pre-save checklist.
   c. Call write_and_save_draft
   d. Call self_judge_draft — read composite, weakest_dimension, AND top_week_gaps
   e. If composite < {_PASSING_SCORE} OR "REWRITE:" in suggestion: fix and judge again
   f. If composite is {_PASSING_SCORE}-{TOP_WEEK_SCORE-1}: apply one fix from top_week_gaps, save, judge again
   g. Call request_human_review with final score and breakdown
7. Update memory with feed observations
8. Summarize: titles chosen, final scores, which title formula used, why each is competitive

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
            description="Fetch the top articles from the challenge feed (last 7 days). Returns list with reactions, author, tags, and article IDs.",
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
            name="read_feed_article",
            description=(
                "Read the full body of a single article from the challenge feed. "
                "Use this BEFORE writing to understand what angles and content already exist. "
                "Call this for the top 3-5 articles after fetch_challenge_feed returns IDs. "
                "Returns title, author, reactions, tags, and full article body (truncated to 2000 chars)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "Article ID from fetch_challenge_feed output"},
                },
                "required": ["article_id"],
            },
            func=read_feed_article,
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
                "Calling again with the same article_number overwrites the previous draft. "
                "REJECTS if body_markdown is under 800 words."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Use a title formula with curiosity gap"},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                    "body_markdown": {"type": "string", "description": "Full article body, no frontmatter. Must be 800-1200 words."},
                    "article_number": {"type": "integer", "enum": [1, 2]},
                },
                "required": ["title", "tags", "body_markdown", "article_number"],
            },
            func=write_and_save_draft,
        ),
        Tool(
            name="self_judge_draft",
            description=(
                "Score a saved draft on the rubric (Creativity, Technical, Writing Quality, Knowledge). "
                "Returns JSON with scores, composite, weakest_dimension, top_week_gaps, and improvement_suggestion. "
                "Read ALL fields — top_week_gaps shows specific elements missing for top/week."
            ),
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
            description="Open a GitHub Issue for Kiel to review. Kiel closes it to approve publishing. Only call this when composite >= 30.",
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
    # max_tokens=16384 gives the LLM room to write a full 1000-word article in one pass
    # without hitting output limits and padding incrementally.
    agent = AgentLoop(tools=build_tools(), system=SYSTEM_PROMPT, max_iterations=60, max_tokens=16384)
    return agent.run(GOAL)

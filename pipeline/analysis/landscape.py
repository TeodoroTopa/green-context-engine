"""Landscape analysis — maps key players, recent developments, and implementation state.

Given a story and its data context, uses Claude to identify who is working on
the relevant problem, what stage they're at, and what recent policy or industry
moves are shaping the space. Strictly grounded — no fabricated names or dates.
"""

import json
import logging

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

LANDSCAPE_PROMPT = """\
You are an energy policy and industry analyst. Given a news story and electricity data,
map the landscape: who are the key players, what's the implementation state, and what
recent developments shape this space.

Rules:
- ONLY reference facts from the Story and Data sections below.
- Do NOT invent company names, policy names, dates, or statistics.
- If the story mentions specific actors, policies, or projects, analyze those.
- If it doesn't, describe the landscape qualitatively (what types of actors are involved,
  what stage of implementation, what the typical policy environment looks like).
- Focus on: government policy, industry players, financing/investment, technology readiness.
- Be specific where the data allows; be honest about gaps where it doesn't.

Return JSON:
{{
  "key_players": ["player 1 — role/relevance", "player 2 — role/relevance"],
  "implementation_state": "1-2 sentence summary of where things stand",
  "recent_developments": ["development 1", "development 2"],
  "policy_context": "1-2 sentence summary of the policy environment"
}}

## Story
Title: {title}
Summary: {summary}

## Data
{data_text}
"""


def analyze_landscape(
    client,
    model: str,
    title: str,
    summary: str,
    data_text: str,
    tracker: UsageTracker | None = None,
) -> dict:
    """Map the competitive/policy landscape around an energy story.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        title: Story title.
        summary: Story summary text.
        data_text: Formatted data string.
        tracker: Optional usage tracker.

    Returns:
        Dict with keys: key_players, implementation_state,
        recent_developments, policy_context. Empty dict on failure.
    """
    prompt = LANDSCAPE_PROMPT.format(title=title, summary=summary, data_text=data_text)

    response = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "landscape")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        return {
            "key_players": result.get("key_players", []),
            "implementation_state": result.get("implementation_state", ""),
            "recent_developments": result.get("recent_developments", []),
            "policy_context": result.get("policy_context", ""),
        }
    except json.JSONDecodeError:
        logger.warning(f"Could not parse landscape analysis: {text[:200]}")
        return {}

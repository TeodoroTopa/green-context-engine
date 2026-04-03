"""Trade-offs analysis — surfaces what's gained and lost in energy stories.

Given a story and its data context, uses Claude to identify the tensions
and trade-offs. Every energy decision has costs — this module makes them explicit.
"""

import json
import logging

from anthropic import Anthropic

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

TRADEOFFS_PROMPT = """\
You are an energy policy analyst. Given a news story and electricity data,
identify 1-2 core trade-offs that the story implies but may not state explicitly.

Rules:
- ONLY reference numbers that appear in the Story or Data sections below.
- Do NOT invent or recall any statistics.
- A trade-off has two sides: what is gained and what is lost. Present both with equal weight.
- Consider: economic vs. environmental, short-term vs. long-term, local vs. global,
  energy security vs. emissions, jobs vs. transition costs.
- If the story is positive (new renewables), note what's lost (land, materials, cost).
  If negative (plant closure), note what's gained (emissions, health).

Return JSON:
{{
  "tradeoffs": [
    {{
      "tension": "short label for the trade-off",
      "gained": "what is gained (1-2 sentences)",
      "lost": "what is lost (1-2 sentences)"
    }}
  ]
}}

## Story
Title: {title}
Summary: {summary}

## Data
{data_text}
"""


def analyze_tradeoffs(
    client: Anthropic,
    model: str,
    title: str,
    summary: str,
    data_text: str,
    tracker: UsageTracker | None = None,
) -> list[dict]:
    """Identify trade-offs in an energy story.

    Args:
        client: Anthropic API client.
        model: Model ID to use.
        title: Story title.
        summary: Story summary text.
        data_text: Formatted Ember data string.
        tracker: Optional usage tracker.

    Returns:
        List of dicts with keys: tension, gained, lost.
    """
    prompt = TRADEOFFS_PROMPT.format(title=title, summary=summary, data_text=data_text)

    response = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "tradeoffs")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        return result.get("tradeoffs", [])
    except json.JSONDecodeError:
        logger.warning(f"Could not parse tradeoffs: {text[:200]}")
        return []

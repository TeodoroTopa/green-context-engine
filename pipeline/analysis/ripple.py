"""Ripple effects analysis — traces second and third-order consequences.

Given a story and its data context, uses Claude to identify cascading effects
across energy, economics, land use, and policy domains. Only references
data that was provided — never invents statistics.
"""

import json
import logging

from anthropic import Anthropic

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

RIPPLE_PROMPT = """\
You are an energy systems analyst. Given a news story and electricity data,
identify 2-3 second or third-order consequences that are NOT obvious from the headline.

Rules:
- ONLY reference numbers that appear in the Story or Data sections below.
- Do NOT invent or recall any statistics. If you lack data for a ripple effect, describe
  the mechanism qualitatively without fabricating figures.
- Focus on cross-domain connections: energy → economics, energy → land use,
  energy → grid stability, energy → public health, policy → investment.
- Each ripple effect should be 2-3 sentences: state the effect, explain the mechanism,
  note what data would confirm or refute it.

Return JSON: {{"ripple_effects": ["effect 1", "effect 2", ...]}}

## Story
Title: {title}
Summary: {summary}

## Data
{data_text}
"""


def analyze_ripple_effects(
    client: Anthropic,
    model: str,
    title: str,
    summary: str,
    data_text: str,
    tracker: UsageTracker | None = None,
) -> list[str]:
    """Identify second/third-order consequences of an energy story.

    Args:
        client: Anthropic API client.
        model: Model ID to use.
        title: Story title.
        summary: Story summary text.
        data_text: Formatted Ember data string.
        tracker: Optional usage tracker.

    Returns:
        List of ripple effect descriptions.
    """
    prompt = RIPPLE_PROMPT.format(title=title, summary=summary, data_text=data_text)

    response = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "ripple_effects")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        return result.get("ripple_effects", [])
    except json.JSONDecodeError:
        logger.warning(f"Could not parse ripple effects: {text[:200]}")
        return []

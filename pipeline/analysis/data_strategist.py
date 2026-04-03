"""Data strategist — AI agent that decides what data to fetch for each article.

Given an article and the full data catalog, returns a fetch plan specifying
which sources and entities to query. This replaces hardcoded benchmark logic
and makes the pipeline source-agnostic.
"""

import json
import logging

from pipeline.analysis.utils import strip_code_fences
from pipeline.monitors.rss_monitor import Story
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

STRATEGIST_PROMPT = """\
You are a data strategist for an energy intelligence pipeline. Given a news story
and a catalog of available data sources, decide what data to fetch.

Rules:
- Pick 1-3 PRIMARY entities — the countries/regions the story is about.
- Pick 2-4 BENCHMARK entities — comparison groups that contextualize the primary data.
  Choose the most relevant: if the story is about Indonesia, compare to Asia and ASEAN,
  not EU. Always include World as a baseline.
- For each fetch, specify which SOURCE to use (ember, eia, etc.).
- Only request entities that exist in the catalog for that source.
- EIA only covers the US — don't request non-US entities from EIA.
- Prefer fewer, more relevant comparisons over many generic ones.

Return JSON only:
{{
  "fetches": [
    {{"source": "ember", "entity": "Indonesia", "role": "primary"}},
    {{"source": "ember", "entity": "Asia", "role": "benchmark"}},
    {{"source": "ember", "entity": "ASEAN", "role": "benchmark"}},
    {{"source": "ember", "entity": "World", "role": "benchmark"}}
  ],
  "reasoning": "Brief explanation of why these comparisons were chosen"
}}

## Story
Title: {title}
Summary: {summary}

## Available Data Sources
{catalog}
"""


def plan_data_fetch(
    client,
    model: str,
    story: Story,
    catalog_text: str,
    tracker: UsageTracker | None = None,
) -> dict:
    """Ask Claude what data to fetch for this story.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        story: The news story to plan for.
        catalog_text: Formatted catalog from catalog.load_catalog().
        tracker: Optional usage tracker.

    Returns:
        Dict with keys: fetches (list of {source, entity, role}), reasoning (str).
        Returns a minimal default plan on failure.
    """
    prompt = STRATEGIST_PROMPT.format(
        title=story.title,
        summary=story.summary,
        catalog=catalog_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "data_strategist")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        fetches = result.get("fetches", [])
        reasoning = result.get("reasoning", "")

        # Validate structure
        valid_fetches = []
        for f in fetches:
            if isinstance(f, dict) and "source" in f and "entity" in f:
                f.setdefault("role", "primary")
                valid_fetches.append(f)

        if not valid_fetches:
            logger.warning("Strategist returned no valid fetches, using default")
            return _default_plan(story)

        logger.info(
            f"Strategist plan: {len(valid_fetches)} fetches — {reasoning[:100]}"
        )
        return {"fetches": valid_fetches, "reasoning": reasoning}

    except json.JSONDecodeError:
        logger.warning(f"Could not parse strategist response: {text[:200]}")
        return _default_plan(story)


def _default_plan(story: Story) -> dict:
    """Fallback plan when the strategist fails — fetch World data from Ember."""
    return {
        "fetches": [
            {"source": "ember", "entity": "World", "role": "primary"},
        ],
        "reasoning": "Fallback: strategist failed, fetching World data only.",
    }

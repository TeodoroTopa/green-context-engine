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
Pick what data to fetch for this story. Always use 2+ sources for cross-domain synthesis.

<examples>

Indonesia deforestation story:
{{
  "fetches": [
    {{"source": "ember", "entity": "Indonesia", "role": "primary"}},
    {{"source": "gfw", "entity": "Indonesia", "role": "primary", "data_types": ["tree_cover_loss", "deforestation_drivers"]}},
    {{"source": "ember", "entity": "ASEAN", "role": "benchmark"}},
    {{"source": "ember", "entity": "World", "role": "benchmark"}},
    {{"source": "gfw", "entity": "Brazil", "role": "benchmark", "data_types": ["tree_cover_loss"]}}
  ],
  "reasoning": "Ember for grid carbon intensity + GFW for deforestation rates and drivers. Compare to ASEAN/World on energy, Brazil on deforestation."
}}

US Port of LA electrification story:
{{
  "fetches": [
    {{"source": "ember", "entity": "United States", "role": "primary"}},
    {{"source": "eia", "entity": "California", "role": "primary"}},
    {{"source": "noaa", "entity": "California", "role": "primary", "data_types": ["cooling_degree_days"]}},
    {{"source": "ember", "entity": "World", "role": "benchmark"}}
  ],
  "reasoning": "EIA for California grid mix (the grid these trucks charge on), NOAA for cooling demand, Ember for US/global comparison."
}}

</examples>

<rules>
- 2+ different sources per story (mandatory).
- 1-3 primary entities (the story's subjects), 2-4 benchmarks (comparisons).
- Use "data_types" to request specific data when you don't need everything from a source.
- Always include Ember World as a global baseline.
- EIA is US-only. Map US cities to their state: Port of LA → California, NYC → New York.
- Only request entities listed in the catalog below.
</rules>

Return JSON only: {{"fetches": [...], "reasoning": "..."}}

<story>
Title: {title}
Summary: {summary}
</story>

<catalog>
{catalog}
</catalog>
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

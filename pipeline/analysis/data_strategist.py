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
You are a data strategist for an energy intelligence pipeline. Your job is to
decide what data to fetch from MULTIPLE sources to enable cross-domain synthesis.

The pipeline's core value is connecting disparate data: energy grids + deforestation,
electricity mix + biodiversity, US state data + global benchmarks. Single-source
analysis is not enough — always pull from multiple sources to create a richer picture.

Rules:
- ALWAYS fetch from at least 2 different sources. This is mandatory.
- Pick 1-3 PRIMARY entities — the countries/regions the story is about.
- Pick 2-4 BENCHMARK entities — comparison groups from relevant sources.
- For each fetch, you can optionally specify "data_types" — a list of specific
  data to request from that source. Check the catalog for available data_types
  per source. If omitted, the source returns all available data.
- For any story with a geographic location:
  * Ember: electricity generation, carbon intensity, emissions (always relevant)
  * GFW: tree cover loss, deforestation drivers (WHY forests are lost), carbon emissions
  * NOAA: temperature trends, precipitation, heating/cooling degree days (energy demand)
  * IUCN: threatened species if biodiversity angle exists
  * EIA: US-specific electricity data (only for US stories)
  * Electricity Maps: real-time carbon intensity (if key configured)
- Always include Ember World as a global baseline.
- EIA only covers the US — don't request non-US entities from EIA.
- Only request entities that exist in the catalog for that source.

Example — Indonesia deforestation story:
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

Example — US heat wave + energy demand story:
{{
  "fetches": [
    {{"source": "ember", "entity": "United States", "role": "primary"}},
    {{"source": "noaa", "entity": "Texas", "role": "primary", "data_types": ["yearly_temperature", "cooling_degree_days"]}},
    {{"source": "eia", "entity": "Texas", "role": "primary"}},
    {{"source": "ember", "entity": "World", "role": "benchmark"}}
  ],
  "reasoning": "EIA for Texas grid mix, NOAA for temperature + cooling demand, Ember for US/global comparison."
}}

Return JSON only:
{{
  "fetches": [...],
  "reasoning": "Explain the cross-source synthesis angle"
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

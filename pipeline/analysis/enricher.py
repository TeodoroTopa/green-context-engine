"""Enricher — connects news stories to energy data via the data strategist.

Flow: Story → strategist picks data to fetch → fetch from multiple sources
→ format data with benchmarks → EnrichedStory ready for drafting.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.analysis.catalog import load_catalog, get_available_sources
from pipeline.analysis.data_strategist import plan_data_fetch
from pipeline.analysis.utils import strip_code_fences
from pipeline.monitors.rss_monitor import Story
from pipeline.sources.base import BaseSource
from pipeline.sources.ember import EmberSource
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

COUNTRIES_FILE = Path("data/reference/countries.json")


@dataclass
class EnrichedStory:
    """A story with attached data context and analysis."""

    story: Story
    entities: list[str]
    ember_data: dict
    data_summary: str
    suggested_angles: list[str] = field(default_factory=list)
    fetch_plan: dict = field(default_factory=dict)
    benchmark_data: dict = field(default_factory=dict)


class Enricher:
    """Enriches stories with energy data using AI-driven data selection."""

    def __init__(self, sources: dict[str, BaseSource], client, model: str = "claude-sonnet-4-6"):
        self.sources = sources  # {"ember": EmberSource, "eia": EIASource, ...}
        self.client = client
        self.model = model
        self._countries = self._load_countries()
        self._catalog_text = load_catalog()

    def _load_countries(self) -> dict[str, str]:
        """Load country name → canonical name mapping."""
        if COUNTRIES_FILE.exists():
            return json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))
        logger.warning(f"Countries file not found: {COUNTRIES_FILE}")
        return {}

    def enrich(self, story: Story, tracker: UsageTracker | None = None) -> EnrichedStory:
        """Full enrichment pipeline for a single story."""
        # 1. Strategist decides what data to fetch
        fetch_plan = plan_data_fetch(
            self.client, self.model, story, self._catalog_text, tracker,
        )

        # 2. Execute the fetch plan
        primary_data, benchmark_data = self._execute_plan(fetch_plan)

        # 3. Build entities list from primary fetches
        entities = [f["entity"] for f in fetch_plan["fetches"] if f["role"] == "primary"]
        if not entities:
            entities = self._extract_entities_local(story) or ["World"]

        # 4. Format data and analyze
        if primary_data:
            data_text = self._format_primary_data(primary_data)
            if benchmark_data:
                data_text += "\n\n" + self._format_benchmark_data(
                    benchmark_data, fetch_plan.get("reasoning", "")
                )
            data_summary, angles = self._analyze(story, data_text, tracker)
        else:
            data_summary = ""
            angles = []

        return EnrichedStory(
            story=story,
            entities=entities,
            ember_data=primary_data,
            data_summary=data_summary,
            suggested_angles=angles,
            fetch_plan=fetch_plan,
            benchmark_data=benchmark_data,
        )

    def _execute_plan(self, plan: dict) -> tuple[dict, dict]:
        """Execute the strategist's fetch plan, dispatching to the right source."""
        primary_data = {}
        benchmark_data = {}

        for fetch in plan.get("fetches", []):
            source_name = fetch.get("source", "ember")
            entity = fetch.get("entity", "")
            role = fetch.get("role", "primary")

            source = self.sources.get(source_name)
            if not source:
                logger.warning(f"Source '{source_name}' not available, skipping {entity}")
                continue

            try:
                data = source.get_generation_context(entity)
                if role == "primary":
                    primary_data[entity] = data
                else:
                    benchmark_data[entity] = data
            except Exception as e:
                logger.warning(f"Failed to fetch {source_name}/{entity}: {e}")

        return primary_data, benchmark_data

    def _extract_entities_local(self, story: Story) -> list[str]:
        """Extract country/region names using local lookup. No API call."""
        text = f"{story.title} {story.summary}"
        found = []
        for name, canonical in self._countries.items():
            if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                if canonical not in found:
                    found.append(canonical)
        return found

    def _analyze(self, story: Story, data_text: str, tracker: UsageTracker | None = None) -> tuple[str, list[str]]:
        """Claude analyzes the story in context of the energy data."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    "You are an energy data analyst. Given this news story and electricity data, "
                    "provide:\n"
                    "1. A brief summary of what the data shows (2-3 sentences)\n"
                    "2. 2-3 suggested angles for an energy intelligence brief\n\n"
                    "Return JSON: {\"summary\": \"...\", \"angles\": [\"...\", \"...\"]}\n\n"
                    f"## Story\nTitle: {story.title}\nSummary: {story.summary}\n\n"
                    f"## Electricity Data\n{data_text}"
                ),
            }],
        )
        if tracker:
            tracker.track(response, "analysis")
        text = strip_code_fences(response.content[0].text)
        try:
            result = json.loads(text)
            return result.get("summary", ""), result.get("angles", [])
        except json.JSONDecodeError:
            logger.warning(f"Could not parse analysis: {text[:200]}")
            return text, []

    def _format_primary_data(self, data: dict) -> str:
        """Format primary entity data for the prompt."""
        if not data:
            return "No primary data available."
        parts = []
        for entity, context in data.items():
            lines = [f"### {entity} (primary)"]
            gen = context.get("generation", [])
            if gen:
                latest_year = max(r["date"] for r in gen)
                latest = [r for r in gen if r["date"] == latest_year]
                lines.append(f"Generation mix ({latest_year}):")
                for r in sorted(latest, key=lambda x: x.get("generation_twh", 0), reverse=True):
                    lines.append(f"  {r.get('series', '?')}: {r.get('generation_twh', '?')} TWh")

            carbon = context.get("carbon_intensity", [])
            if carbon:
                latest_c = max(carbon, key=lambda x: x["date"])
                lines.append(
                    f"Carbon intensity ({latest_c['date']}): "
                    f"{latest_c.get('emissions_intensity_gco2_per_kwh', '?')} gCO2/kWh"
                )
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def _format_benchmark_data(self, data: dict, reasoning: str) -> str:
        """Format benchmark/comparison data for the prompt."""
        lines = ["### Comparison Benchmarks"]
        if reasoning:
            lines.append(f"Context: {reasoning}")
        for entity, context in data.items():
            carbon = context.get("carbon_intensity", [])
            if carbon:
                latest_c = max(carbon, key=lambda x: x["date"])
                ci = latest_c.get("emissions_intensity_gco2_per_kwh", "?")
                lines.append(f"  {entity}: {ci} gCO2/kWh ({latest_c['date']})")
            # Also show generation if available (useful for comparing scale)
            gen = context.get("generation", [])
            if gen:
                latest_year = max(r["date"] for r in gen)
                total = sum(
                    r.get("generation_twh", 0) for r in gen
                    if r["date"] == latest_year and isinstance(r.get("generation_twh"), (int, float))
                )
                if total > 0:
                    lines.append(f"  {entity} total generation ({latest_year}): {total:.0f} TWh")
        return "\n".join(lines)

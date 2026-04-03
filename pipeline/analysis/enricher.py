"""Enricher — connects news stories to energy data via Claude.

Flow: Story → extract entities (local first, Claude fallback) → fetch Ember data
→ analyze (Claude) → EnrichedStory with data context and suggested angles.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic

from pipeline.monitors.rss_monitor import Story
from pipeline.sources.ember import EmberSource
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

COUNTRIES_FILE = Path("data/reference/countries.json")


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) that Claude sometimes wraps around JSON."""
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


@dataclass
class EnrichedStory:
    """A story with attached data context and analysis."""

    story: Story
    entities: list[str]
    ember_data: dict
    data_summary: str
    suggested_angles: list[str] = field(default_factory=list)


class Enricher:
    """Enriches stories with energy data and Claude-powered analysis."""

    def __init__(self, ember: EmberSource, client: Anthropic, model: str = "claude-sonnet-4-6"):
        self.ember = ember
        self.client = client
        self.model = model
        self._countries = self._load_countries()

    def _load_countries(self) -> dict[str, str]:
        """Load country name → canonical name mapping."""
        if COUNTRIES_FILE.exists():
            return json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))
        logger.warning(f"Countries file not found: {COUNTRIES_FILE}")
        return {}

    def enrich(self, story: Story, tracker: UsageTracker | None = None) -> EnrichedStory:
        """Full enrichment pipeline for a single story."""
        entities = self._extract_entities_local(story)
        if not entities:
            logger.info("No local entity match, falling back to Claude")
            entities = self._extract_entities_claude(story, tracker)
        ember_data = self._fetch_data(entities)

        # Only call Claude for analysis if we have actual data to analyze
        if ember_data:
            data_summary, angles = self._analyze(story, ember_data, tracker)
        else:
            data_summary = ""
            angles = []

        return EnrichedStory(
            story=story,
            entities=entities,
            ember_data=ember_data,
            data_summary=data_summary,
            suggested_angles=angles,
        )

    def _extract_entities_local(self, story: Story) -> list[str]:
        """Extract country/region names using local lookup. No API call."""
        text = f"{story.title} {story.summary}"
        found = []
        for name, canonical in self._countries.items():
            # Whole-word match, case-insensitive
            if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                if canonical not in found:
                    found.append(canonical)
        return found

    def _extract_entities_claude(self, story: Story, tracker: UsageTracker | None = None) -> list[str]:
        """Fallback: use Claude to extract country/region names from a story."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    "Extract country or region names from this news story. "
                    "Return ONLY a JSON array of strings, e.g. [\"Germany\", \"France\"]. "
                    "If no specific countries are mentioned, return [\"World\"].\n\n"
                    f"Title: {story.title}\n"
                    f"Summary: {story.summary}"
                ),
            }],
        )
        if tracker:
            tracker.track(response, "entity_extraction")
        text = _strip_code_fences(response.content[0].text)
        try:
            entities = json.loads(text)
            if isinstance(entities, list):
                return entities
        except json.JSONDecodeError:
            logger.warning(f"Could not parse entities from Claude response: {text}")
        return ["World"]

    def _fetch_data(self, entities: list[str]) -> dict:
        """Pull Ember data for each entity."""
        data = {}
        for entity in entities:
            try:
                data[entity] = self.ember.get_generation_context(entity)
            except Exception as e:
                logger.warning(f"Failed to fetch Ember data for '{entity}': {e}")
        return data

    def _analyze(self, story: Story, data: dict, tracker: UsageTracker | None = None) -> tuple[str, list[str]]:
        """Claude analyzes the story in context of the energy data."""
        data_text = self._format_data(data)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=800,
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
        text = _strip_code_fences(response.content[0].text)
        try:
            result = json.loads(text)
            return result.get("summary", ""), result.get("angles", [])
        except json.JSONDecodeError:
            logger.warning(f"Could not parse analysis from Claude response: {text}")
            return text, []

    def _format_data(self, data: dict) -> str:
        """Format Ember data into readable text for the prompt."""
        if not data:
            return "No electricity data available."
        parts = []
        for entity, context in data.items():
            lines = [f"### {entity}"]
            gen = context.get("generation", [])
            if gen:
                # Show most recent year's generation mix
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

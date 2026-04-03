"""Enricher — connects news stories to energy data via Claude.

Flow: Story → extract entities (Claude) → fetch Ember data → analyze (Claude)
→ EnrichedStory with data context and suggested angles.
"""

import json
import logging
from dataclasses import dataclass, field

from anthropic import Anthropic

from pipeline.monitors.rss_monitor import Story
from pipeline.sources.ember import EmberSource

logger = logging.getLogger(__name__)


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

    def __init__(self, ember: EmberSource, client: Anthropic, model: str = "claude-sonnet-4-6-20250514"):
        self.ember = ember
        self.client = client
        self.model = model

    def enrich(self, story: Story) -> EnrichedStory:
        """Full enrichment pipeline for a single story."""
        entities = self._extract_entities(story)
        ember_data = self._fetch_data(entities)
        data_summary, angles = self._analyze(story, ember_data)
        return EnrichedStory(
            story=story,
            entities=entities,
            ember_data=ember_data,
            data_summary=data_summary,
            suggested_angles=angles,
        )

    def _extract_entities(self, story: Story) -> list[str]:
        """Use Claude to extract country/region names from a story."""
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
        text = response.content[0].text.strip()
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

    def _analyze(self, story: Story, data: dict) -> tuple[str, list[str]]:
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
        text = response.content[0].text.strip()
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

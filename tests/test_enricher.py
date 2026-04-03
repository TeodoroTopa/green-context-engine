"""Tests for the enricher — story analysis via Claude + Ember data."""

from unittest.mock import MagicMock

from pipeline.analysis.enricher import Enricher, EnrichedStory
from pipeline.monitors.rss_monitor import Story

SAMPLE_STORY = Story(
    title="Solar capacity surges in Germany",
    url="https://example.com/solar-germany",
    summary="Germany added 10 GW of solar in 2025, a record year.",
    published="2026-03-30",
    source="mongabay",
    feed_name="mongabay_energy",
)


def _mock_claude_response(text: str) -> MagicMock:
    """Create a mock Anthropic messages.create() return value."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_enrich_full_pipeline():
    """enrich() extracts entities, fetches data, and analyzes."""
    client = MagicMock()
    ember = MagicMock()

    # First Claude call: entity extraction → returns ["Germany"]
    # Second Claude call: analysis → returns summary + angles
    client.messages.create.side_effect = [
        _mock_claude_response('["Germany"]'),
        _mock_claude_response('{"summary": "Germany solar is growing fast.", "angles": ["record capacity"]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "Germany",
        "generation": [{"series": "Solar", "generation_twh": 72, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 350, "date": "2025"}],
    }

    enricher = Enricher(ember, client)
    result = enricher.enrich(SAMPLE_STORY)

    assert isinstance(result, EnrichedStory)
    assert result.entities == ["Germany"]
    assert "Germany" in result.ember_data
    assert "solar" in result.data_summary.lower()
    assert len(result.suggested_angles) == 1
    ember.get_generation_context.assert_called_once_with("Germany")
    assert client.messages.create.call_count == 2

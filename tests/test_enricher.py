"""Tests for the enricher with data strategist integration."""

from unittest.mock import MagicMock

from pipeline.analysis.enricher import Enricher, EnrichedStory
from pipeline.monitors.rss_monitor import Story

STORY = Story(
    title="Solar capacity surges in Germany",
    url="https://example.com/solar-germany",
    summary="Germany added 10 GW of solar in 2025, a record year.",
    published="2026-03-30",
    source="mongabay",
    feed_name="mongabay_energy",
)


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_enrich_uses_strategist_and_fetches_data():
    """Enricher calls strategist, fetches from sources, and analyzes."""
    client = MagicMock()
    ember = MagicMock()

    # Call 1: strategist returns fetch plan
    # Call 2: analysis returns summary + angles
    client.messages.create.side_effect = [
        _mock_response('{"fetches": [{"source": "ember", "entity": "Germany", "role": "primary"}, {"source": "ember", "entity": "World", "role": "benchmark"}], "reasoning": "Compare to global"}'),
        _mock_response('{"summary": "Germany solar growing fast.", "angles": ["Record capacity"]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "Germany",
        "generation": [{"series": "Solar", "generation_twh": 72, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 350, "date": "2025"}],
    }

    sources = {"ember": ember}
    enricher = Enricher(sources, client)
    result = enricher.enrich(STORY)

    assert result.entities == ["Germany"]
    assert "Germany" in result.ember_data
    assert "World" in result.benchmark_data
    assert result.fetch_plan["reasoning"] == "Compare to global"
    # 2 Claude calls: strategist + analysis
    assert client.messages.create.call_count == 2


def test_enrich_falls_back_on_strategist_failure():
    """Enricher uses default plan when strategist returns bad JSON."""
    client = MagicMock()
    ember = MagicMock()

    client.messages.create.side_effect = [
        _mock_response("not valid json"),  # strategist fails
        _mock_response('{"summary": "World data.", "angles": ["Global trends"]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [{"series": "Total", "generation_twh": 29000, "date": "2024"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 471, "date": "2024"}],
    }

    sources = {"ember": ember}
    enricher = Enricher(sources, client)
    result = enricher.enrich(STORY)

    # Falls back to World
    assert "World" in result.ember_data
    assert "Fallback" in result.fetch_plan["reasoning"]

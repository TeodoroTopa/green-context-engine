"""Tests for the enricher — story analysis via Claude + Ember data."""

from unittest.mock import MagicMock

from pipeline.analysis.enricher import Enricher, EnrichedStory
from pipeline.monitors.rss_monitor import Story

STORY_WITH_COUNTRY = Story(
    title="Solar capacity surges in Germany",
    url="https://example.com/solar-germany",
    summary="Germany added 10 GW of solar in 2025, a record year.",
    published="2026-03-30",
    source="mongabay",
    feed_name="mongabay_energy",
)

STORY_NO_COUNTRY = Story(
    title="New battery chemistry could halve costs",
    url="https://example.com/battery",
    summary="Researchers develop sodium-ion cells with higher energy density.",
    published="2026-03-30",
    source="mongabay",
    feed_name="mongabay_energy",
)


def _mock_claude_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_enrich_uses_local_extraction_when_country_found():
    """When a country is in the text, Claude is only called for analysis + ripple + tradeoffs."""
    client = MagicMock()
    ember = MagicMock()

    # 3 Claude calls: analysis, ripple_effects, tradeoffs (entity extraction is local)
    client.messages.create.side_effect = [
        _mock_claude_response('{"summary": "Germany solar is growing fast.", "angles": ["record capacity"]}'),
        _mock_claude_response('{"ripple_effects": ["Grid stability improves"]}'),
        _mock_claude_response('{"tradeoffs": [{"tension": "land use", "gained": "clean energy", "lost": "farmland"}]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "Germany",
        "generation": [{"series": "Solar", "generation_twh": 72, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 350, "date": "2025"}],
    }

    enricher = Enricher(ember, client)
    result = enricher.enrich(STORY_WITH_COUNTRY)

    assert result.entities == ["Germany"]
    assert "Germany" in result.ember_data
    assert len(result.ripple_effects) == 1
    assert len(result.tradeoffs) == 1
    # 3 Claude calls (analysis + ripple + tradeoffs), not 4 (entity extraction skipped)
    assert client.messages.create.call_count == 3


def test_enrich_falls_back_to_claude_when_no_country():
    """When no country found locally, falls back to Claude for entity extraction."""
    client = MagicMock()
    ember = MagicMock()

    # 4 Claude calls: entity extraction + analysis + ripple + tradeoffs
    client.messages.create.side_effect = [
        _mock_claude_response('["World"]'),
        _mock_claude_response('{"summary": "Battery tech advancing.", "angles": ["cost reduction"]}'),
        _mock_claude_response('{"ripple_effects": ["Supply chain shift"]}'),
        _mock_claude_response('{"tradeoffs": [{"tension": "cost vs performance", "gained": "cheaper", "lost": "energy density"}]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [],
        "carbon_intensity": [],
    }

    enricher = Enricher(ember, client)
    result = enricher.enrich(STORY_NO_COUNTRY)

    assert result.entities == ["World"]
    assert client.messages.create.call_count == 4

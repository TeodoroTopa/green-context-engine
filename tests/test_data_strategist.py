"""Tests for the data strategist."""

from unittest.mock import MagicMock

from pipeline.analysis.data_strategist import plan_data_fetch, _default_plan
from pipeline.monitors.rss_monitor import Story

STORY = Story(
    title="Indonesia deforestation surges",
    url="https://example.com",
    summary="Deforestation in Indonesia surged 66%.",
    published="2026-04-03",
    source="mongabay",
    feed_name="test",
)

CATALOG = "## EMBER: Global electricity data\nAsia: Indonesia, India, China"


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_plan_returns_fetches_and_reasoning():
    """Strategist returns structured fetch plan."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"fetches": [{"source": "ember", "entity": "Indonesia", "role": "primary"}, '
        '{"source": "ember", "entity": "Asia", "role": "benchmark"}], '
        '"reasoning": "Indonesia is in Asia"}'
    )

    plan = plan_data_fetch(client, "test-model", STORY, CATALOG)

    assert len(plan["fetches"]) == 2
    assert plan["fetches"][0]["entity"] == "Indonesia"
    assert plan["fetches"][1]["role"] == "benchmark"
    assert "Asia" in plan["reasoning"]


def test_plan_handles_bad_json():
    """Falls back to default plan on parse failure."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response("I think you should fetch Indonesia data")

    plan = plan_data_fetch(client, "test-model", STORY, CATALOG)

    assert len(plan["fetches"]) == 1
    assert plan["fetches"][0]["entity"] == "World"
    assert "Fallback" in plan["reasoning"]


def test_default_plan():
    """_default_plan returns World from Ember."""
    plan = _default_plan(STORY)
    assert plan["fetches"][0]["source"] == "ember"
    assert plan["fetches"][0]["entity"] == "World"

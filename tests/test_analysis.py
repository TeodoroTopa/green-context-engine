"""Tests for ripple effects, trade-offs, and landscape analysis modules."""

from unittest.mock import MagicMock

from pipeline.analysis.landscape import analyze_landscape
from pipeline.analysis.ripple import analyze_ripple_effects
from pipeline.analysis.tradeoffs import analyze_tradeoffs
from pipeline.analysis.utils import strip_code_fences


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_ripple_effects_parses_json():
    """analyze_ripple_effects returns a list of effect strings."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"ripple_effects": ["Grid stability improves", "Coal jobs decline"]}'
    )

    result = analyze_ripple_effects(
        client, "claude-sonnet-4-6",
        "Solar surges in Germany", "Record year for solar.",
        "Solar: 72 TWh",
    )

    assert len(result) == 2
    assert "Grid stability" in result[0]


def test_ripple_effects_handles_code_fences():
    """analyze_ripple_effects strips markdown code fences."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '```json\n{"ripple_effects": ["Effect one"]}\n```'
    )

    result = analyze_ripple_effects(
        client, "claude-sonnet-4-6", "Title", "Summary", "Data",
    )

    assert len(result) == 1


def test_ripple_effects_handles_bad_json():
    """analyze_ripple_effects returns empty list on malformed response."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response("Not valid JSON at all")

    result = analyze_ripple_effects(
        client, "claude-sonnet-4-6", "Title", "Summary", "Data",
    )

    assert result == []


def test_tradeoffs_parses_structured_json():
    """analyze_tradeoffs returns a list of trade-off dicts."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"tradeoffs": [{"tension": "land use vs clean energy", '
        '"gained": "Lower emissions", "lost": "Agricultural land"}]}'
    )

    result = analyze_tradeoffs(
        client, "claude-sonnet-4-6",
        "Solar farm proposal", "New 500MW solar park planned.",
        "Solar: 72 TWh",
    )

    assert len(result) == 1
    assert result[0]["tension"] == "land use vs clean energy"
    assert "emissions" in result[0]["gained"].lower()


def test_tradeoffs_handles_bad_json():
    """analyze_tradeoffs returns empty list on malformed response."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response("broken")

    result = analyze_tradeoffs(
        client, "claude-sonnet-4-6", "Title", "Summary", "Data",
    )

    assert result == []


def test_strip_code_fences():
    """strip_code_fences handles various fence formats."""
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'
    assert strip_code_fences('  ```json\n{"a": 1}\n```  ') == '{"a": 1}'


def test_ripple_effects_tracks_usage():
    """analyze_ripple_effects calls tracker.track when provided."""
    client = MagicMock()
    tracker = MagicMock()
    client.messages.create.return_value = _mock_response('{"ripple_effects": []}')

    analyze_ripple_effects(
        client, "claude-sonnet-4-6", "Title", "Summary", "Data", tracker=tracker,
    )

    tracker.track.assert_called_once()
    assert tracker.track.call_args.args[1] == "ripple_effects"


def test_landscape_parses_structured_json():
    """analyze_landscape returns a dict with key_players, implementation_state, etc."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"key_players": ["PLN — state utility"], '
        '"implementation_state": "Early stage", '
        '"recent_developments": ["New solar auction"], '
        '"policy_context": "Feed-in tariff under review"}'
    )

    result = analyze_landscape(
        client, "claude-sonnet-4-6",
        "Indonesia solar push", "Government announces new targets.",
        "Solar: 1.35 TWh",
    )

    assert result["key_players"] == ["PLN — state utility"]
    assert result["implementation_state"] == "Early stage"
    assert len(result["recent_developments"]) == 1
    assert "tariff" in result["policy_context"]


def test_landscape_handles_bad_json():
    """analyze_landscape returns empty dict on malformed response."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response("not json")

    result = analyze_landscape(
        client, "claude-sonnet-4-6", "Title", "Summary", "Data",
    )

    assert result == {}

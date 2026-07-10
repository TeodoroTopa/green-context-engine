"""Tests for the article selector agent."""

from unittest.mock import MagicMock

from pipeline.analysis.article_selector import cap_by_source, select_best_stories
from pipeline.monitors.rss_monitor import Story


def _make_stories(titles: list[str]) -> list[Story]:
    return [
        Story(title=t, url=f"https://example.com/{i}", summary=t,
              published="2026-04-05", source="test", feed_name="test")
        for i, t in enumerate(titles)
    ]


def _make_sourced_stories(sources: list[str]) -> list[Story]:
    return [
        Story(title=f"Story {i}", url=f"https://example.com/{i}", summary="s",
              published="2026-04-05", source=src, feed_name=src)
        for i, src in enumerate(sources)
    ]


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage.input_tokens = 100
    msg.usage.output_tokens = 50
    return msg


def test_selector_picks_by_indices():
    """Selector returns stories in the order Claude chose."""
    stories = _make_stories([
        "TCL acquires DAS Solar",
        "Indonesia deforestation surges 66%",
        "Podcast: EV deliveries roundup",
        "UK saved 1bn from wind and solar",
    ])

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"selected": [1, 3], "reasoning": "Indonesia has GFW+Ember, UK has Ember benchmarks"}'
    )

    result = select_best_stories(client, "claude-opus-4-6", stories, "catalog text", 2)

    assert len(result) == 2
    assert result[0].title == "Indonesia deforestation surges 66%"
    assert result[1].title == "UK saved 1bn from wind and solar"


def test_selector_falls_back_on_bad_json():
    """Falls back to first N stories when Claude returns unparseable response."""
    stories = _make_stories(["Story A", "Story B", "Story C"])

    client = MagicMock()
    client.messages.create.return_value = _mock_response("not valid json")

    result = select_best_stories(client, "claude-opus-4-6", stories, "catalog", 2)

    assert len(result) == 2
    assert result[0].title == "Story A"


def test_selector_handles_out_of_range_indices():
    """Ignores indices that are out of range."""
    stories = _make_stories(["Story A", "Story B"])

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"selected": [99, 0], "reasoning": "test"}'
    )

    result = select_best_stories(client, "claude-opus-4-6", stories, "catalog", 2)

    assert len(result) == 1
    assert result[0].title == "Story A"


def test_selector_tracks_usage():
    """Usage tracker records the selector call."""
    stories = _make_stories(["Story A", "Story B", "Story C"])

    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        '{"selected": [0, 2], "reasoning": "test"}'
    )

    tracker = MagicMock()
    select_best_stories(client, "claude-opus-4-6", stories, "catalog", 2, tracker)

    tracker.track.assert_called_once()
    assert tracker.track.call_args[0][1] == "article_selector"


def test_cap_by_source_enforces_per_source_limit():
    """No source may supply more than max_per_source, even if it ranked higher."""
    # 4 from A (best-ranked first), 2 from B
    stories = _make_sourced_stories(["A", "A", "A", "A", "B", "B"])

    result = cap_by_source(stories, max_stories=5, max_per_source=2)

    # Only 2 A + 2 B = 4, NOT backfilled to 5 from A.
    assert len(result) == 4
    assert sum(1 for s in result if s.source == "A") == 2
    assert sum(1 for s in result if s.source == "B") == 2


def test_cap_by_source_disabled_when_none():
    """max_per_source=None disables the cap (plain first-N slice)."""
    stories = _make_sourced_stories(["A", "A", "A"])
    result = cap_by_source(stories, max_stories=2, max_per_source=None)
    assert len(result) == 2


def test_selector_applies_source_cap_to_ai_ranking():
    """The AI's ranked order is still source-capped after selection."""
    stories = _make_sourced_stories(["A", "A", "A", "B"])

    client = MagicMock()
    # Claude ranks all 4, A-heavy, best first.
    client.messages.create.return_value = _mock_response(
        '{"selected": [0, 1, 2, 3], "reasoning": "test"}'
    )

    result = select_best_stories(
        client, "claude-opus-4-6", stories, "catalog", max_stories=3,
        max_per_source=1,
    )

    assert len(result) == 2  # 1 A + 1 B, not backfilled to 3
    assert sum(1 for s in result if s.source == "A") == 1
    assert sum(1 for s in result if s.source == "B") == 1


def test_selector_fallback_applies_source_cap():
    """Fallback path (bad JSON) is also source-capped, not raw feed order."""
    stories = _make_sourced_stories(["A", "A", "B"])

    client = MagicMock()
    client.messages.create.return_value = _mock_response("not valid json")

    result = select_best_stories(
        client, "claude-opus-4-6", stories, "catalog", max_stories=3,
        max_per_source=1,
    )

    assert len(result) == 2
    assert {s.source for s in result} == {"A", "B"}

"""Tests for the article selector agent."""

from unittest.mock import MagicMock

from pipeline.analysis.article_selector import select_best_stories
from pipeline.monitors.rss_monitor import Story


def _make_stories(titles: list[str]) -> list[Story]:
    return [
        Story(title=t, url=f"https://example.com/{i}", summary=t,
              published="2026-04-05", source="test", feed_name="test")
        for i, t in enumerate(titles)
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

"""Tests for the RSS feed monitor."""

from unittest.mock import patch

import feedparser

from pipeline.monitors.rss_monitor import RSSMonitor, Story

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Mongabay Energy</title>
    <item>
      <title>Solar capacity surges in Southeast Asia</title>
      <link>https://news.mongabay.com/2026/03/solar-southeast-asia</link>
      <guid>https://news.mongabay.com/2026/03/solar-southeast-asia</guid>
      <description>Vietnam and Thailand lead regional solar expansion.</description>
      <pubDate>Mon, 30 Mar 2026 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Wind farm impacts on migratory birds</title>
      <link>https://news.mongabay.com/2026/03/wind-birds</link>
      <guid>https://news.mongabay.com/2026/03/wind-birds</guid>
      <description>New study maps collision risks along flyways.</description>
      <pubDate>Sun, 29 Mar 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

# Parse once at module level, before any patching
PARSED_FEED = feedparser.parse(SAMPLE_RSS)
FEED_CFG = [{"name": "test_feed", "url": "https://fake.com/feed", "source": "test"}]


@patch("pipeline.monitors.rss_monitor.feedparser.parse", return_value=PARSED_FEED)
def test_check_feeds_returns_stories(mock_parse, tmp_path):
    """Parses feed and returns Story objects with correct fields."""
    monitor = RSSMonitor(FEED_CFG, seen_file=tmp_path / "seen.json")
    stories = monitor.check_feeds()

    assert len(stories) == 2
    assert isinstance(stories[0], Story)
    assert stories[0].title == "Solar capacity surges in Southeast Asia"
    assert stories[0].source == "test"
    assert "mongabay.com" in stories[1].url


@patch("pipeline.monitors.rss_monitor.feedparser.parse", return_value=PARSED_FEED)
def test_deduplication(mock_parse, tmp_path):
    """Second call with same feed returns no new stories."""
    seen_file = tmp_path / "seen.json"
    monitor = RSSMonitor(FEED_CFG, seen_file=seen_file)

    first = monitor.check_feeds()
    assert len(first) == 2

    # Same feed again — should be deduplicated
    second = monitor.check_feeds()
    assert len(second) == 0
    assert seen_file.exists()


# RSS with one energy story and one unrelated story
MIXED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Solar capacity surges in Southeast Asia</title>
      <link>https://example.com/solar</link>
      <guid>solar-1</guid>
      <description>Vietnam leads solar expansion.</description>
    </item>
    <item>
      <title>New frog species discovered in Borneo</title>
      <link>https://example.com/frog</link>
      <guid>frog-1</guid>
      <description>Researchers found a tiny amphibian in peat swamp forest.</description>
    </item>
  </channel>
</rss>"""

PARSED_MIXED = feedparser.parse(MIXED_RSS)


@patch("pipeline.monitors.rss_monitor.feedparser.parse", return_value=PARSED_MIXED)
def test_keyword_filter_removes_irrelevant_stories(mock_parse, tmp_path):
    """Stories without energy keywords are filtered out."""
    monitor = RSSMonitor(
        FEED_CFG,
        seen_file=tmp_path / "seen.json",
        relevance_keywords=["solar", "wind", "energy"],
    )
    stories = monitor.check_feeds()

    assert len(stories) == 1
    assert stories[0].title == "Solar capacity surges in Southeast Asia"


# Empty feed
EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""

PARSED_EMPTY = feedparser.parse(EMPTY_RSS)


@patch("pipeline.monitors.rss_monitor.feedparser.parse", return_value=PARSED_EMPTY)
def test_empty_feed_returns_no_stories(mock_parse, tmp_path):
    """An empty feed returns zero stories without crashing."""
    monitor = RSSMonitor(FEED_CFG, seen_file=tmp_path / "seen.json")
    stories = monitor.check_feeds()
    assert len(stories) == 0


@patch("pipeline.monitors.rss_monitor.feedparser.parse", return_value=PARSED_FEED)
def test_multiple_feeds_combine(mock_parse, tmp_path):
    """Stories from multiple feed configs are combined."""
    two_feeds = [
        {"name": "feed_a", "url": "https://fake.com/a", "source": "source_a"},
        {"name": "feed_b", "url": "https://fake.com/b", "source": "source_b"},
    ]
    monitor = RSSMonitor(two_feeds, seen_file=tmp_path / "seen.json")
    stories = monitor.check_feeds()
    # Same parsed feed returned for both, but GUIDs dedup across feeds
    assert len(stories) == 2  # 2 unique GUIDs, not 4

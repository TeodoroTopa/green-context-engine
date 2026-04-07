"""RSS feed monitor — parses feeds and returns new (unseen) stories.

Uses feedparser to pull articles from configured RSS feeds (Mongabay, etc.).
Deduplicates against a local JSON file of previously seen article GUIDs.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import feedparser

logger = logging.getLogger(__name__)

SEEN_FILE = Path("data/reference/seen_articles.json")


@dataclass
class Story:
    """A news story extracted from an RSS feed."""

    title: str
    url: str
    summary: str
    published: str  # raw date string from feed
    source: str  # e.g. "mongabay"
    feed_name: str  # e.g. "mongabay_energy"
    full_text: str = ""  # Full article text, fetched separately


class RSSMonitor:
    """Monitors RSS feeds and returns new stories since last check."""

    def __init__(
        self,
        feeds: list[dict],
        seen_file: Path = SEEN_FILE,
        relevance_keywords: list[str] | None = None,
        skip_dedup: bool = False,
    ):
        self.feeds = feeds
        self.seen_file = seen_file
        self.skip_dedup = skip_dedup
        self.seen: set[str] = set() if skip_dedup else self._load_seen()
        self.keywords = [k.lower() for k in (relevance_keywords or [])]

    def _load_seen(self) -> set[str]:
        if self.seen_file.exists():
            return set(json.loads(self.seen_file.read_text(encoding="utf-8")))
        return set()

    def _save_seen(self) -> None:
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        self.seen_file.write_text(
            json.dumps(sorted(self.seen)), encoding="utf-8"
        )

    def check_feeds(self) -> list[Story]:
        """Parse all configured feeds, return new (unseen) stories."""
        new_stories = []
        for feed_cfg in self.feeds:
            try:
                stories = self._parse_feed(feed_cfg)
                new_stories.extend(stories)
            except Exception as e:
                logger.error(f"Failed to parse feed '{feed_cfg.get('name')}': {e}")
                continue
        if new_stories and not self.skip_dedup:
            self._save_seen()
        logger.info(f"Found {len(new_stories)} new stories across {len(self.feeds)} feeds")
        return new_stories

    def _parse_feed(self, feed_cfg: dict) -> list[Story]:
        """Parse a single feed and return unseen stories."""
        parsed = feedparser.parse(feed_cfg["url"])
        stories = []
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link", "")
            if guid in self.seen:
                continue
            story = Story(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                summary=entry.get("summary", ""),
                published=entry.get("published", ""),
                source=feed_cfg["source"],
                feed_name=feed_cfg["name"],
            )
            if self.keywords and not self._is_relevant(story):
                logger.debug(f"Filtered out (no keyword match): {story.title}")
                self.seen.add(guid)  # still mark seen so we don't re-check
                continue
            stories.append(story)
            self.seen.add(guid)
        return stories

    def _is_relevant(self, story: Story) -> bool:
        """Check if story title or summary contains any relevance keyword."""
        text = f"{story.title} {story.summary}".lower()
        return any(kw in text for kw in self.keywords)

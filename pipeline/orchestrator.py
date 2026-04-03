"""Orchestrator — wires the full pipeline: monitor → enrich → draft.

Usage:
    from pipeline.orchestrator import Pipeline
    pipeline = Pipeline()
    drafts = pipeline.run()  # or pipeline.run(source="mongabay")
"""

import logging
import os
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

from pipeline.analysis.enricher import Enricher
from pipeline.generation.drafter import Drafter
from pipeline.monitors.rss_monitor import RSSMonitor
from pipeline.sources.ember import EmberSource

logger = logging.getLogger(__name__)


class Pipeline:
    """End-to-end pipeline: discover stories → enrich with data → draft posts."""

    def __init__(self):
        load_dotenv()
        self.ember = EmberSource(api_key=os.getenv("EMBER_API_KEY"))
        self.client = Anthropic()
        self.enricher = Enricher(self.ember, self.client)
        self.drafter = Drafter(self.client)

    def run(self, source: str | None = None, max_stories: int = 5) -> list[Path]:
        """Run the full pipeline.

        Args:
            source: Filter to feeds from this source (e.g. "mongabay")
            max_stories: Cap on stories to process per run (saves API calls)

        Returns:
            List of paths to generated draft files.
        """
        feeds = self._load_feeds(source)
        monitor = RSSMonitor(feeds)
        stories = monitor.check_feeds()
        logger.info(f"Found {len(stories)} new stories")

        if not stories:
            return []

        stories = stories[:max_stories]
        drafts = []
        for story in stories:
            try:
                enriched = self.enricher.enrich(story)
                draft_path = self.drafter.draft(enriched)
                drafts.append(draft_path)
                logger.info(f"Drafted: {draft_path.name}")
            except Exception as e:
                logger.error(f"Failed to process '{story.title}': {e}")
                continue
        return drafts

    def _load_feeds(self, source: str | None = None) -> list[dict]:
        """Load feed config, optionally filtering by source."""
        config_path = Path("config/feeds.yaml")
        feeds_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        feeds = feeds_cfg.get("feeds", [])
        if source:
            feeds = [f for f in feeds if f["source"] == source]
        return feeds

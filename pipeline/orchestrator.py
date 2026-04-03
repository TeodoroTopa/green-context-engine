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
from pipeline.publishing.notion import NotionPublisher
from pipeline.sources.ember import EmberSource
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)


class Pipeline:
    """End-to-end pipeline: discover stories → enrich with data → draft posts."""

    def __init__(self):
        load_dotenv()
        self.ember = EmberSource(api_key=os.getenv("EMBER_API_KEY"))
        self.client = Anthropic()
        self.enricher = Enricher(self.ember, self.client)
        self.drafter = Drafter(self.client)
        # Notion is optional — skip if no token configured
        try:
            self.notion = NotionPublisher()
        except ValueError:
            self.notion = None
            logger.info("Notion token not configured — drafts will be saved locally only")

    def run(self, source: str | None = None, max_stories: int = 5) -> list[Path]:
        """Run the full pipeline.

        Args:
            source: Filter to feeds from this source (e.g. "mongabay")
            max_stories: Cap on stories to process per run (saves API calls)

        Returns:
            List of paths to generated draft files.
        """
        feeds, keywords = self._load_feeds(source)
        monitor = RSSMonitor(feeds, relevance_keywords=keywords)
        stories = monitor.check_feeds()
        logger.info(f"Found {len(stories)} new stories")

        if not stories:
            return []

        stories = stories[:max_stories]
        drafts = []
        run_tracker = UsageTracker()  # accumulates across all stories
        for story in stories:
            notion_page_id = None
            try:
                # Queue in Notion
                if self.notion:
                    notion_page_id = self.notion.create_story(
                        story.title, source_url=story.url, source_name=story.source,
                    )

                # Enrich
                if self.notion and notion_page_id:
                    self.notion.update_status(notion_page_id, "Enriching")
                tracker = UsageTracker()
                enriched = self.enricher.enrich(story, tracker)
                if not enriched.ember_data:
                    logger.warning(f"Skipping '{story.title}' — no Ember data available")
                    if self.notion and notion_page_id:
                        self.notion.update_status(notion_page_id, "Queued")  # reset back
                    continue

                # Draft
                draft_path = self.drafter.draft(enriched, tracker)
                drafts.append(draft_path)
                logger.info(f"Drafted: {draft_path.name}")
                logger.info(f"  {tracker.summary()}")
                if self.notion and notion_page_id:
                    self.notion.update_status(notion_page_id, "Drafted")

                # merge per-story calls into run total
                run_tracker.calls.extend(tracker.calls)
            except Exception as e:
                logger.error(f"Failed to process '{story.title}': {e}")
                continue

        if run_tracker.calls:
            logger.info(f"=== Run total ===\n{run_tracker.summary()}")
        return drafts

    def _load_feeds(self, source: str | None = None) -> tuple[list[dict], list[str]]:
        """Load feed config, optionally filtering by source. Returns (feeds, keywords)."""
        config_path = Path("config/feeds.yaml")
        feeds_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        feeds = feeds_cfg.get("feeds", [])
        keywords = feeds_cfg.get("relevance_keywords", [])
        if source:
            feeds = [f for f in feeds if f["source"] == source]
        return feeds, keywords

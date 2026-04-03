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
from pipeline.claude_code_client import ClaudeCodeClient
from pipeline.generation.drafter import Drafter
from pipeline.generation.editor import check_draft
from pipeline.monitors.rss_monitor import RSSMonitor
from pipeline.publishing.notion import NotionPublisher
from pipeline.sources.eia import EIASource
from pipeline.sources.ember import EmberSource
from pipeline.sources.gfw import GFWSource
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)


class Pipeline:
    """End-to-end pipeline: discover stories → enrich with data → draft posts."""

    def __init__(self):
        load_dotenv()

        # Claude client (dev/local mode uses CLI proxy, prod uses API)
        mode = os.getenv("PIPELINE_MODE", "prod")
        if mode in ("dev", "local"):
            logger.info(f"{mode.capitalize()} mode: routing Claude calls through claude CLI")
            self.client = ClaudeCodeClient()
        else:
            self.client = Anthropic()

        # Build source registry — each source keyed by its catalog name
        sources = {}
        ember_key = os.getenv("EMBER_API_KEY")
        if ember_key:
            sources["ember"] = EmberSource(api_key=ember_key)
            logger.info("Ember source enabled")
        eia_key = os.getenv("EIA_API_KEY")
        if eia_key:
            sources["eia"] = EIASource(api_key=eia_key)
            logger.info("EIA source enabled")
        gfw_key = os.getenv("GFW_API_KEY")
        if gfw_key:
            sources["gfw"] = GFWSource(api_key=gfw_key)
            logger.info("GFW source enabled")

        self.enricher = Enricher(sources, self.client)
        self.drafter = Drafter(self.client)

        # Notion is optional
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
        run_tracker = UsageTracker()
        for story in stories:
            notion_page_id = None
            try:
                # Queue in Notion
                if self.notion:
                    notion_page_id = self.notion.create_story(
                        story.title, source_url=story.url, source_name=story.source,
                    )

                # Enrich (strategist + data fetch + analysis)
                if self.notion and notion_page_id:
                    self.notion.update_status(notion_page_id, "Enriching")
                tracker = UsageTracker()
                enriched = self.enricher.enrich(story, tracker)
                if not enriched.ember_data:
                    logger.warning(f"Skipping '{story.title}' — no data available")
                    if self.notion and notion_page_id:
                        self.notion.update_status(notion_page_id, "Queued")
                    continue

                # Draft → Edit → Revise loop (max 2 revision attempts)
                draft_path = self.drafter.draft(enriched, tracker)
                drafts.append(draft_path)
                logger.info(f"Drafted: {draft_path.name}")

                max_revisions = 2
                for attempt in range(max_revisions + 1):
                    edit_result = check_draft(
                        self.client, self.drafter.model, draft_path,
                        story_title=story.title,
                        story_summary=story.summary,
                        story_source=story.source,
                        data_text=enriched.data_text,
                        tracker=tracker,
                    )
                    if edit_result["pass"]:
                        logger.info(f"Editor PASSED: {draft_path.name}")
                        break
                    if attempt < max_revisions:
                        logger.info(
                            f"Editor found errors (attempt {attempt + 1}/{max_revisions}), revising..."
                        )
                        self.drafter.revise(
                            draft_path, edit_result.get("errors", []),
                            enriched.data_text, tracker,
                        )
                    else:
                        logger.warning(
                            f"Editor still failing after {max_revisions} revisions: "
                            f"{edit_result['summary']}"
                        )

                logger.info(f"  {tracker.summary()}")
                if self.notion and notion_page_id:
                    status = "Review" if edit_result["pass"] else "Drafted"
                    self.notion.update_status(notion_page_id, status)
                    self.notion.append_content(notion_page_id, draft_path)

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

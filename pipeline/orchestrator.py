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
from pipeline.sources.electricity_maps import ElectricityMapsSource
from pipeline.sources.ember import EmberSource
from pipeline.sources.gfw import GFWSource
from pipeline.sources.iucn import IUCNSource
from pipeline.sources.noaa import NOAASource
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
        iucn_key = os.getenv("IUCN_API_KEY")
        if iucn_key:
            sources["iucn"] = IUCNSource(api_key=iucn_key)
            logger.info("IUCN source enabled")
        noaa_key = os.getenv("NOAA_API_KEY")
        if noaa_key:
            sources["noaa"] = NOAASource(api_key=noaa_key)
            logger.info("NOAA source enabled")
        emaps_key = os.getenv("ELECTRICITY_MAPS_API_KEY")
        if emaps_key:
            sources["electricity_maps"] = ElectricityMapsSource(api_key=emaps_key)
            logger.info("Electricity Maps source enabled")

        self.enricher = Enricher(sources, self.client)
        self.drafter = Drafter(self.client)

        # Notion is optional
        try:
            self.notion = NotionPublisher()
        except ValueError:
            self.notion = None
            logger.info("Notion token not configured — drafts will be saved locally only")

    def research_and_draft(
        self, story, tracker: UsageTracker | None = None,
    ) -> tuple:
        """Core pipeline: enrich a story with data, draft a brief, and edit it.

        This method has NO publishing side effects (no Notion, no GitHub).

        Args:
            story: A Story object (from RSS or constructed manually).
            tracker: Optional usage tracker. A new one is created if None.

        Returns:
            Tuple of (EnrichedStory, Path, edit_result dict).

        Raises:
            ValueError: If no data is available for this story.
        """
        if tracker is None:
            tracker = UsageTracker()

        enriched = self.enricher.enrich(story, tracker)
        if not enriched.ember_data:
            raise ValueError(f"No data available for '{story.title}'")

        draft_path = self.drafter.draft(enriched, tracker)
        logger.info(f"Drafted: {draft_path.name}")

        max_revisions = 2
        edit_result = {"pass": False, "summary": "Not checked"}
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
        return enriched, draft_path, edit_result

    def run(self, source: str | None = None, max_stories: int = 5) -> list[Path]:
        """Run the full pipeline: discover stories via RSS, enrich, draft, and publish.

        Deduplication uses Notion as the single source of truth — if a story URL
        already exists in Notion, it is skipped. No local seen-articles file needed.

        Args:
            source: Filter to feeds from this source (e.g. "mongabay")
            max_stories: Cap on stories to process per run (saves API calls)

        Returns:
            List of paths to generated draft files.
        """
        feeds, keywords = self._load_feeds(source)
        monitor = RSSMonitor(feeds, relevance_keywords=keywords, skip_dedup=True)
        stories = monitor.check_feeds()
        logger.info(f"Found {len(stories)} candidate stories from RSS")

        if not stories:
            return []

        # Deduplicate against Notion (single source of truth)
        new_stories = []
        for story in stories:
            if self.notion and self.notion.find_page_by_url(story.url):
                logger.debug(f"Already in Notion, skipping: {story.title}")
                continue
            new_stories.append(story)
            if len(new_stories) >= max_stories:
                break

        logger.info(f"{len(new_stories)} new stories after Notion dedup (capped at {max_stories})")
        if not new_stories:
            return []

        drafts = []
        run_tracker = UsageTracker()
        for story in new_stories:
            notion_page_id = None
            try:
                # Queue in Notion
                if self.notion:
                    notion_page_id = self.notion.create_story(
                        story.title, source_url=story.url, source_name=story.source,
                    )
                    self.notion.update_status(notion_page_id, "Enriching")

                tracker = UsageTracker()
                try:
                    enriched, draft_path, edit_result = self.research_and_draft(
                        story, tracker,
                    )
                except ValueError:
                    logger.warning(f"Skipping '{story.title}' — no data available")
                    if self.notion and notion_page_id:
                        self.notion.update_status(notion_page_id, "Queued")
                    continue

                drafts.append(draft_path)

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

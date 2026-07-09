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

from pipeline.analysis.article_selector import select_best_stories
from pipeline.analysis.enricher import Enricher
from pipeline.claude_code_client import ClaudeCodeClient
from pipeline.content.fetcher import fetch_article_text
from pipeline.generation.drafter import Drafter
from pipeline.generation.editor import check_draft, verify_draft
from pipeline.model_config import model_for
from pipeline.monitors.rss_monitor import RSSMonitor
from pipeline.publishing.notion import NotionPublisher
from pipeline.sources.eia import EIASource
from pipeline.sources.ember import EmberSource
from pipeline.sources.gfw import GFWSource
from pipeline.sources.iucn import IUCNSource
from pipeline.sources.noaa import NOAASource
from pipeline.sources.nlr import NLRSource
from pipeline.sources.openmeteo import OpenMeteoSource
from pipeline.sources.uk_carbon import UKCarbonSource
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

        nlr_key = os.getenv("NLR_API_KEY")
        if nlr_key:
            sources["nlr"] = NLRSource(api_key=nlr_key)
            logger.info("NLR source enabled")

        # Free sources — no API key needed, always enabled
        sources["openmeteo"] = OpenMeteoSource()
        logger.info("Open-Meteo source enabled")
        sources["uk_carbon"] = UKCarbonSource()
        logger.info("UK Carbon Intensity source enabled")

        self.enricher = Enricher(sources, self.client)
        self.drafter = Drafter(self.client)
        self._feeds_config = []  # loaded lazily in run()

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

        # Fetch full article text if not already populated
        if not story.full_text:
            story.full_text = fetch_article_text(story, self._feeds_config)

        enriched = self.enricher.enrich(story, tracker)
        if not enriched.ember_data:
            raise ValueError(f"No data available for '{story.title}'")

        max_draft_attempts = 2
        edit_result = {"verdict": "fail", "summary": "Not checked"}
        editor_kwargs = dict(
            story_title=story.title,
            story_summary=story.summary,
            story_source=story.source,
            data_text=enriched.data_text,
            story_full_text=story.full_text,
        )

        for draft_attempt in range(max_draft_attempts):
            if draft_attempt == 0:
                draft_path = self.drafter.draft(enriched, tracker)
            else:
                logger.info(f"Redrafting from scratch (attempt {draft_attempt + 1})")
                draft_path = self.drafter.draft(
                    enriched, tracker,
                    feedback=edit_result.get("summary", ""),
                )
            logger.info(f"Drafted: {draft_path.name}")

            # Editor: pass / fix / fail
            edit_result = check_draft(
                self.client, model_for("editor"), draft_path,
                tracker=tracker, **editor_kwargs,
            )
            verdict = edit_result.get("verdict", "fail")

            if verdict == "pass":
                logger.info(f"  {tracker.summary()}")
                return enriched, draft_path, edit_result

            if verdict == "fix":
                # Editor fixed the draft — write corrected version
                fixed_draft = edit_result.get("fixed_draft", "")
                if fixed_draft:
                    draft_path.write_text(fixed_draft, encoding="utf-8")
                    logger.info(f"Editor fixed draft, verifying...")

                    # Verification pass — pass/fail only, no more fixes
                    verify_result = verify_draft(
                        self.client, model_for("verifier"), draft_path,
                        tracker=tracker, **editor_kwargs,
                    )
                    if verify_result.get("verdict") == "pass":
                        logger.info(f"  {tracker.summary()}")
                        return enriched, draft_path, verify_result
                    else:
                        logger.warning(
                            f"Verification failed after fix: {verify_result.get('summary', '')[:100]}"
                        )
                        edit_result = verify_result  # use as feedback for redraft

            logger.warning(
                f"Draft attempt {draft_attempt + 1} failed: {edit_result.get('summary', '')[:100]}"
            )

        # All attempts exhausted — skip this story
        logger.info(f"  {tracker.summary()}")
        raise ValueError(
            f"Could not produce editor-passing draft for '{story.title}' "
            f"after {max_draft_attempts} draft attempts"
        )

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
        self._feeds_config = feeds  # store for content fetcher
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

        logger.info(f"{len(new_stories)} new stories after Notion dedup")
        if not new_stories:
            return []

        # Select best stories based on data fit (if more candidates than needed)
        run_tracker = UsageTracker()
        if len(new_stories) > max_stories:
            new_stories = select_best_stories(
                self.client, model_for("selector"),
                new_stories, self.enricher._catalog_text,
                max_stories, run_tracker,
            )
        else:
            new_stories = new_stories[:max_stories]

        drafts = []
        for story in new_stories:
            try:
                tracker = UsageTracker()
                try:
                    enriched, draft_path, edit_result = self.research_and_draft(
                        story, tracker,
                    )
                except ValueError as e:
                    logger.warning(f"Skipping '{story.title}' — {e}")
                    continue

                # Only create Notion page for editor-passed stories
                drafts.append(draft_path)
                if self.notion:
                    notion_page_id = self.notion.create_story(
                        story.title, source_url=story.url, source_name=story.source,
                        published_date=story.published,
                        topics=story.topics[:5] if story.topics else None,
                    )
                    if notion_page_id:
                        self.notion.update_status(notion_page_id, "Review")
                        self.notion.append_content(notion_page_id, draft_path)

                run_tracker.calls.extend(tracker.calls)
            except Exception:
                logger.exception(f"Failed to process '{story.title}'")
                continue

        if run_tracker.calls:
            logger.info(f"=== Run total ===\n{run_tracker.summary()}")
        return drafts

    # ------------------------------------------------------------------ #
    # Batched morning run (API-only): the two Sonnet stages (drafter and  #
    # editor) go through the Message Batches API (50% off); the cheap     #
    # Haiku stages (selector, strategist, verifier) stay synchronous.     #
    # ------------------------------------------------------------------ #
    def run_batched(self, source: str | None = None, max_stories: int = 5) -> list[Path]:
        """Batched, budget-guarded pipeline for the scheduled 7am run.

        Requires the real Anthropic API (Batch is unavailable via the CLI proxy).
        Deduplicates against Notion, drafts and edits via batches, and creates
        Notion "Review" pages for editor-passing stories.
        """
        from pipeline.analysis.article_selector import select_best_stories
        from pipeline.batch_client import BatchClient
        from pipeline.generation.drafter import DRAFT_MAX_TOKENS
        from pipeline.generation.editor import (
            EDITOR_MAX_TOKENS, build_editor_prompt, parse_editor_response, verify_draft,
        )
        from pipeline.generation.prompts.energy_brief import SYSTEM_PROMPT as DRAFT_SYSTEM
        from pipeline.usage import BudgetExceeded, BudgetGuard, UsageTracker

        run_tracker = UsageTracker()
        guard = BudgetGuard()
        batch = BatchClient(self.client)
        draft_model = self.drafter.model
        editor_model = model_for("editor")
        verifier_model = model_for("verifier")

        # 1. Gather candidates → dedup against Notion (sync).
        feeds, keywords = self._load_feeds(source)
        self._feeds_config = feeds
        monitor = RSSMonitor(feeds, relevance_keywords=keywords, skip_dedup=True)
        stories = monitor.check_feeds()
        logger.info(f"Found {len(stories)} candidate stories from RSS")
        new_stories = [
            s for s in stories
            if not (self.notion and self.notion.find_page_by_url(s.url))
        ]
        logger.info(f"{len(new_stories)} new stories after Notion dedup")
        if not new_stories:
            return []

        # 2. Select best N (sync Haiku).
        if len(new_stories) > max_stories:
            new_stories = select_best_stories(
                self.client, model_for("selector"), new_stories,
                self.enricher._catalog_text, max_stories, run_tracker,
            )
        else:
            new_stories = new_stories[:max_stories]

        # 3. Fetch article text + strategist + enrich (sync).
        enriched_by_id: dict[str, object] = {}
        for i, story in enumerate(new_stories):
            sid = f"s{i}"
            try:
                if not story.full_text:
                    story.full_text = fetch_article_text(story, self._feeds_config)
                enriched = self.enricher.enrich(story, run_tracker)
                if not enriched.ember_data:
                    logger.warning(f"No data for '{story.title}', skipping")
                    continue
                enriched_by_id[sid] = enriched
            except Exception:
                logger.exception(f"Enrich failed for '{story.title}'")
        if not enriched_by_id:
            return []

        def _ekwargs(en):
            return dict(
                story_title=en.story.title, story_summary=en.story.summary,
                story_source=en.story.source, data_text=en.data_text,
                story_full_text=en.story.full_text,
            )

        passing: dict[str, tuple] = {}   # sid -> (enriched, path)
        feedback: dict[str, str] = {}
        pending = dict(enriched_by_id)   # sid -> enriched needing a draft

        try:
            for round_num in range(2):  # bounded, mirrors max_draft_attempts=2
                if not pending:
                    break
                ids = list(pending)

                # --- Batch: draft (Sonnet) ---
                draft_reqs = [{
                    "custom_id": sid,
                    "params": {
                        "model": draft_model, "max_tokens": DRAFT_MAX_TOKENS,
                        "system": DRAFT_SYSTEM,
                        "messages": [{
                            "role": "user",
                            "content": self.drafter.build_prompt(pending[sid], feedback.get(sid, "")),
                        }],
                    },
                } for sid in ids]
                draft_results = self._submit_batch(
                    batch, guard, draft_reqs, draft_model, DRAFT_MAX_TOKENS, run_tracker, "draft",
                )
                drafted: dict[str, Path] = {}
                for sid in ids:
                    r = draft_results.get(sid)
                    if r and r.ok:
                        drafted[sid] = self.drafter.finalize_from_text(
                            pending[sid], r.text, run_tracker,
                        )
                    else:
                        logger.warning(f"Draft batch failed for {sid}")

                if not drafted:
                    break

                # --- Batch: editor check/fix (Sonnet) ---
                editor_reqs = [{
                    "custom_id": sid,
                    "params": {
                        "model": editor_model, "max_tokens": EDITOR_MAX_TOKENS,
                        "messages": [{
                            "role": "user",
                            "content": build_editor_prompt(
                                path.read_text(encoding="utf-8"), **_ekwargs(pending[sid]),
                            ),
                        }],
                    },
                } for sid, path in drafted.items()]
                editor_results = self._submit_batch(
                    batch, guard, editor_reqs, editor_model, EDITOR_MAX_TOKENS, run_tracker, "editor",
                )

                next_pending: dict[str, object] = {}
                for sid, path in drafted.items():
                    er = editor_results.get(sid)
                    result = (
                        parse_editor_response(er.text, path.name)
                        if er and er.ok else {"verdict": "fail", "summary": "editor batch failed"}
                    )
                    verdict = result.get("verdict", "fail")
                    if verdict == "pass":
                        passing[sid] = (pending[sid], path)
                    elif verdict == "fix":
                        fixed = result.get("fixed_draft", "")
                        if fixed:
                            path.write_text(fixed, encoding="utf-8")
                        # Verify the fix (sync Haiku).
                        vr = verify_draft(
                            self.client, verifier_model, path,
                            tracker=run_tracker, **_ekwargs(pending[sid]),
                        )
                        if vr.get("verdict") == "pass":
                            passing[sid] = (pending[sid], path)
                        else:
                            feedback[sid] = vr.get("summary", "")
                            next_pending[sid] = pending[sid]
                    else:  # fail → redraft next round
                        feedback[sid] = result.get("summary", "")
                        next_pending[sid] = pending[sid]

                pending = next_pending
        except BudgetExceeded as e:
            logger.warning(f"Budget guard tripped, stopping further batches: {e}")

        # 4. Create Notion "Review" pages for accepted drafts (sync).
        drafts: list[Path] = []
        for sid, (enriched, path) in passing.items():
            story = enriched.story
            drafts.append(path)
            if self.notion:
                try:
                    page_id = self.notion.create_story(
                        story.title, source_url=story.url, source_name=story.source,
                        published_date=story.published,
                        topics=story.topics[:5] if story.topics else None,
                    )
                    if page_id:
                        self.notion.update_status(page_id, "Review")
                        self.notion.append_content(page_id, path)
                except Exception:
                    logger.exception(f"Notion publish failed for '{story.title}'")

        logger.info(f"=== Batched run total (spent ~${guard.spent:.4f}) ===\n{run_tracker.summary()}")
        return drafts

    def _submit_batch(self, batch, guard, reqs, model, max_tokens, tracker, label):
        """Estimate cost, enforce the budget cap, submit, and record actuals."""
        from pipeline.usage import estimate_cost

        if not reqs:
            return {}
        # Pre-submit estimate: char/4 heuristic for input, max_tokens for output.
        est = 0.0
        for r in reqs:
            params = r["params"]
            text = params.get("system", "") or ""
            text += "".join(m.get("content", "") for m in params.get("messages", []))
            in_tokens = max(1, len(text) // 4)
            est += estimate_cost(model, in_tokens, max_tokens, batch=True)
        guard.check(est)  # raises BudgetExceeded

        results = batch.run(reqs)

        actual = 0.0
        for r in results.values():
            if r.ok:
                tracker.track(r.message, label, model=model, batch=True)
                u = r.message.usage
                actual += estimate_cost(model, u.input_tokens, u.output_tokens, batch=True)
        guard.record(actual)
        return results

    def _load_feeds(self, source: str | None = None) -> tuple[list[dict], list[str]]:
        """Load feed config, optionally filtering by source. Returns (feeds, keywords)."""
        config_path = Path("config/feeds.yaml")
        feeds_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        feeds = feeds_cfg.get("feeds", [])
        keywords = feeds_cfg.get("relevance_keywords", [])
        if source:
            feeds = [f for f in feeds if f["source"] == source]
        return feeds, keywords

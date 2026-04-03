"""Drafter — generates markdown intelligence briefs from enriched stories.

Flow: EnrichedStory → Claude drafts post → voice check → fix if needed → save to content/drafts/
"""

import logging
import re
from datetime import date
from pathlib import Path

from anthropic import Anthropic

from pipeline.analysis.enricher import EnrichedStory
from pipeline.generation.prompts.energy_brief import SYSTEM_PROMPT, build_draft_prompt
from pipeline.generation.voice import check_voice
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

DRAFTS_DIR = Path("content/drafts")


class Drafter:
    """Generates draft posts from enriched stories."""

    def __init__(self, client: Anthropic, model: str = "claude-sonnet-4-6"):
        self.client = client
        self.model = model

    def draft(self, enriched: EnrichedStory, tracker: UsageTracker | None = None) -> Path:
        """Generate a draft post and save to content/drafts/.

        Returns the path to the saved draft file.
        """
        prompt = build_draft_prompt(enriched)
        draft_text = self._generate(prompt, tracker)

        violations = check_voice(draft_text)
        if violations:
            logger.info(f"Voice violations found: {violations}")
            draft_text = self._fix_violations(draft_text, violations, tracker)

        return self._save(enriched, draft_text)

    def _generate(self, prompt: str, tracker: UsageTracker | None = None) -> str:
        """Call Claude to generate a draft."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if tracker:
            tracker.track(response, "draft_generation")
        return response.content[0].text

    def _fix_violations(self, draft: str, violations: list[str], tracker: UsageTracker | None = None) -> str:
        """Ask Claude to fix editorial voice violations."""
        violations_text = "\n".join(f"- {v}" for v in violations)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=3000,
            system="You are an editor. Fix the listed violations without changing the substance.",
            messages=[{
                "role": "user",
                "content": (
                    f"Fix these editorial violations in the draft:\n\n"
                    f"{violations_text}\n\n"
                    f"---\n\n{draft}"
                ),
            }],
        )
        if tracker:
            tracker.track(response, "voice_fix")
        return response.content[0].text

    def _save(self, enriched: EnrichedStory, text: str) -> Path:
        """Save draft to content/drafts/ with a date-slug filename."""
        slug = re.sub(r"[^a-z0-9]+", "-", enriched.story.title.lower())[:50].strip("-")
        filename = f"{date.today().isoformat()}_{slug}.md"
        path = DRAFTS_DIR / filename
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        logger.info(f"Saved draft: {path}")
        return path

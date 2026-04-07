"""Editor agent — fact-checks drafts against source data.

Receives the draft AND the original source material (story + data),
verifies every claim traces back to the provided sources, and checks
editorial quality. Replaces the old quality_gate.py.
"""

import json
import logging
import re
from pathlib import Path

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

EDITOR_PROMPT = """\
Fact-check this draft against the source material. Every claim must trace to
the Story or Data below.

<checks>
CRITICAL — flag these:
- Any factual claim not in the Story or Data
- Any distortion (e.g., "multi-year decline" when data shows mixed trend)
- Data year ≠ story year without explicit label

HIGH — flag these:
- Trend words ("reversing," "first time," "steady") not supported by the data
- Numbers that can't be traced to source data or a labeled calculation

MEDIUM — flag these:
- Lazy adjectives without evidence, fluff phrases, missing frontmatter
</checks>

Return JSON only:
{{
  "pass": true/false,
  "errors": [{{"severity": "critical|high|medium", "claim": "...", "issue": "...", "fix": "..."}}],
  "summary": "1-2 sentence assessment"
}}

PASS = zero critical, zero high, ≤2 medium.

<source_material>
Story: {story_title} ({story_source})
Summary: {story_summary}
{article_text_block}
Data provided to writer:
{data_text}
</source_material>

<draft>
{draft_text}
</draft>
"""


def check_draft(
    client,
    model: str,
    draft_path: Path,
    story_title: str,
    story_summary: str,
    story_source: str,
    data_text: str,
    story_full_text: str = "",
    tracker: UsageTracker | None = None,
) -> dict:
    """Fact-check a draft against its source material.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        draft_path: Path to the draft markdown file.
        story_title: Original story title.
        story_summary: Original story summary.
        story_source: Source name (e.g., "Mongabay").
        data_text: The formatted data text the drafter received.
        tracker: Optional usage tracker.

    Returns:
        Dict with keys: pass (bool), errors (list), summary (str).
    """
    draft_text = draft_path.read_text(encoding="utf-8")
    article_text_block = ""
    if story_full_text:
        article_text_block = f"\nArticle excerpt:\n{story_full_text}\n"
    prompt = EDITOR_PROMPT.format(
        story_title=story_title,
        story_summary=story_summary,
        story_source=story_source,
        article_text_block=article_text_block,
        data_text=data_text,
        draft_text=draft_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "editor")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        passed = result.get("pass", False)
        errors = result.get("errors", [])
        summary = result.get("summary", "")

        if passed:
            logger.info(f"Editor PASSED: {draft_path.name}")
        else:
            critical = [e for e in errors if e.get("severity") == "critical"]
            high = [e for e in errors if e.get("severity") == "high"]
            logger.warning(
                f"Editor FAILED: {draft_path.name} — "
                f"{len(critical)} critical, {len(high)} high: {summary[:150]}"
            )

        return {"pass": passed, "errors": errors, "summary": summary}

    except json.JSONDecodeError:
        # Fallback: parse prose response (dev mode)
        return _parse_prose_response(text, draft_path.name)


def _parse_prose_response(text: str, filename: str) -> dict:
    """Best-effort parsing of a prose editor response (dev mode fallback)."""
    text_upper = text.upper()
    passed = "PASS" in text_upper and "NEEDS REVISION" not in text_upper and "FAIL" not in text_upper

    summary = ""
    summary_match = re.search(r"### Summary\s*\n(.+?)(?:\n###|\Z)", text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()[:300]

    if passed:
        logger.info(f"Editor PASSED (prose fallback): {filename}")
    else:
        logger.warning(f"Editor FAILED (prose fallback): {filename} — {summary[:100]}")

    return {"pass": passed, "errors": [], "summary": summary or "Parsed from prose response"}

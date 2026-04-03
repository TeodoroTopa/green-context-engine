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
You are a rigorous fact-checking editor for energy intelligence briefs.

You have TWO inputs:
1. The DRAFT — what the writer produced
2. The SOURCE MATERIAL — the story and data the writer was given

Your job: verify every claim in the draft against the source material.

## Checks (in order of severity)

### 1. Claim Verification (CRITICAL)
Every factual statement must trace to either the Story or the Data.
- If a claim doesn't appear in either source, flag it.
- If a claim oversimplifies a source (e.g., "multi-year decline" when the source
  says "decline 2017-2021, then moderate increases"), flag it as a distortion.

### 2. Temporal Accuracy (CRITICAL)
- If the data year differs from the story year, the draft MUST state this explicitly.
  Example: "Ember data from 2024 shows..." when the story event is from 2025.
- Flag any phrasing that implies data and story events are contemporaneous when they're not.

### 3. Trend Accuracy (HIGH)
- Words like "snapping," "reversing," "first time," "steady" make specific claims
  about patterns. Verify each against what the story actually says.
- An oversimplification that changes the meaning is an error, not a style choice.

### 4. Numerical Accuracy (HIGH)
- Every number in the draft must appear in the source data OR be a clearly labeled
  calculation from source numbers (e.g., "44% above" derived from 680 vs 471).
- Flag any number that can't be traced.

### 5. Editorial Quality (MEDIUM)
- No lazy adjectives without evidence
- No fluff phrases
- Active voice
- YAML frontmatter present with title, date, sources

## Return Format

Return JSON only:
{{
  "pass": true/false,
  "errors": [
    {{"severity": "critical|high|medium", "claim": "quoted text from draft",
      "issue": "what's wrong", "fix": "suggested correction"}}
  ],
  "summary": "1-2 sentence assessment"
}}

PASS = zero critical errors, zero high errors, and no more than 2 medium errors.

## Source Material

### Story
Title: {story_title}
Source: {story_source}
Summary: {story_summary}

### Data Provided to Writer
{data_text}

## Draft to Review

{draft_text}
"""


def check_draft(
    client,
    model: str,
    draft_path: Path,
    story_title: str,
    story_summary: str,
    story_source: str,
    data_text: str,
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
    prompt = EDITOR_PROMPT.format(
        story_title=story_title,
        story_summary=story_summary,
        story_source=story_source,
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

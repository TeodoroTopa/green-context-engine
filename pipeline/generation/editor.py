"""Editor agent — fact-checks drafts and fixes issues directly.

Three outcomes: pass (clean), fix (editor corrects issues itself), or fail
(needs full redraft). After a "fix", a verification pass confirms the
editor's corrections didn't introduce new problems.
"""

import json
import logging
import re
from pathlib import Path

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

EDITOR_PROMPT = """\
Fact-check this draft against the source material. Every NUMBER must trace to
the Story, Article, or Data below.

<reject>
Fix or fail these:
- Numbers not traceable to any source (fabricated data)
- Claims that contradict the source material
- Data years not labeled when they differ from the story year
- Factual statements about events not mentioned in the article
</reject>

<allow>
Do NOT flag these — they are normal editorial practice:
- Reasonable characterizations of sourced numbers: "nearly double" for 1.5x-2x,
  "more than half" for 51%+, "roughly" or "about" within 10%, "a fraction of"
- Derived calculations from sourced numbers (e.g., "44% above" from 680 vs 471)
- Rounding (e.g., "384" for 383.78, "210" for 209.9)
- Contextual interpretations that follow logically from the data
</allow>

<verdicts>
Return JSON with one of three verdicts:

1. PASS — draft is clean:
{{"verdict": "pass", "summary": "1-2 sentence assessment"}}

2. FIX — draft has fixable issues (unsourced claims, minor inaccuracies).
   Fix them yourself and return the corrected draft. Remove unsourced claims
   rather than guessing replacements. Only use numbers from the source material.
{{"verdict": "fix", "fixed_draft": "the complete corrected markdown including frontmatter", "changes": ["what you changed"], "summary": "..."}}

3. FAIL — draft has fundamental problems requiring a complete rewrite:
{{"verdict": "fail", "errors": [{{"severity": "...", "claim": "...", "issue": "...", "fix": "..."}}], "summary": "..."}}
</verdicts>

Prefer "fix" over "fail" whenever possible. Most issues (an unsourced number,
a claim from training data, a mislabeled year) can be fixed by removing or
correcting a single sentence. Only use "fail" when the entire structure or
angle is wrong.

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

VERIFY_PROMPT = """\
Verify that every NUMBER in this draft traces to the source material below.
This is a final check — pass or fail only.

Editorial characterizations of sourced numbers are acceptable and should NOT
be flagged (e.g., "nearly double" for 1.83x, "roughly a third" for 31%,
rounding 383.78 to 384). Only fail if you find fabricated numbers or claims
that directly contradict the sources.

Return JSON only:
{{"verdict": "pass", "summary": "..."}}
or
{{"verdict": "fail", "summary": "what's wrong"}}

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
    """Fact-check a draft. Returns pass/fix/fail verdict.

    Returns:
        Dict with keys: verdict ("pass"|"fix"|"fail"), summary (str),
        and optionally: fixed_draft (str), changes (list), errors (list).
    """
    draft_text = draft_path.read_text(encoding="utf-8")
    article_text_block = f"\nArticle excerpt:\n{story_full_text}\n" if story_full_text else ""

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
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "editor")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        verdict = result.get("verdict", "")

        # Handle legacy format (old "pass" boolean)
        if "pass" in result and "verdict" not in result:
            verdict = "pass" if result["pass"] else "fail"
            result["verdict"] = verdict

        if verdict == "pass":
            logger.info(f"Editor PASSED: {draft_path.name}")
        elif verdict == "fix":
            changes = result.get("changes", [])
            logger.info(f"Editor FIXED: {draft_path.name} — {', '.join(changes)[:100]}")
        else:
            summary = result.get("summary", "")
            logger.warning(f"Editor FAILED: {draft_path.name} — {summary[:150]}")

        return result

    except json.JSONDecodeError:
        return _parse_prose_response(text, draft_path.name)


def verify_draft(
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
    """Verification pass — pass or fail only, no fixes. Used after editor fixes."""
    draft_text = draft_path.read_text(encoding="utf-8")
    article_text_block = f"\nArticle excerpt:\n{story_full_text}\n" if story_full_text else ""

    prompt = VERIFY_PROMPT.format(
        story_title=story_title,
        story_summary=story_summary,
        story_source=story_source,
        article_text_block=article_text_block,
        data_text=data_text,
        draft_text=draft_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "verification")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        verdict = result.get("verdict", "fail")
        if verdict == "pass":
            logger.info(f"Verification PASSED: {draft_path.name}")
        else:
            logger.warning(f"Verification FAILED: {draft_path.name} — {result.get('summary', '')[:100]}")
        return result
    except json.JSONDecodeError:
        return _parse_prose_response(text, draft_path.name)


def _parse_prose_response(text: str, filename: str) -> dict:
    """Best-effort parsing of a prose editor response (dev mode fallback)."""
    text_upper = text.upper()
    passed = "PASS" in text_upper and "NEEDS REVISION" not in text_upper and "FAIL" not in text_upper

    summary = ""
    summary_match = re.search(r"### Summary\s*\n(.+?)(?:\n###|\Z)", text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()[:300]

    verdict = "pass" if passed else "fail"
    if passed:
        logger.info(f"Editor PASSED (prose fallback): {filename}")
    else:
        logger.warning(f"Editor FAILED (prose fallback): {filename} — {summary[:100]}")

    return {"verdict": verdict, "summary": summary or "Parsed from prose response"}

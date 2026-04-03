"""Automated quality gate — evaluates drafts against editorial guidelines.

Runs a second Claude call after draft generation to check for violations.
Based on the editorial review skill criteria but returns structured results
for pipeline automation.
"""

import json
import logging
from pathlib import Path

from pipeline.analysis.utils import strip_code_fences
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

QUALITY_PROMPT = """\
You are an editorial quality checker for energy intelligence briefs.
Evaluate the draft below against these criteria and return structured results.

## Criteria

1. **Source Grounding** — Every factual claim must cite a named, verifiable source.
   Flag: numbers without attribution, vague sourcing ("studies show", "experts say").

2. **Data Interpretation** — Numbers must be interpreted, not just stated.
   Flag: raw numbers without context, percentages without baselines.

3. **Trade-Off Presentation** — If trade-offs exist, both sides must be shown.
   Flag: one-sided framing, missing environmental/economic costs.

4. **Voice** — No lazy adjectives (unprecedented, important, critical, crucial,
   significant, transformative, revolutionary) unless earned through evidence.
   No fluff phrases (in an era of, it is worth noting, needless to say, etc.).

5. **Structure** — Must have YAML frontmatter, a Hook section, and a Data Context section.

## Return Format

Return JSON only:
{{
  "pass": true/false,
  "violations": [
    {{"category": "Source Grounding", "text": "quoted text", "issue": "what's wrong"}},
    ...
  ],
  "summary": "1-2 sentence overall assessment"
}}

PASS = zero violations in Source Grounding and Data Interpretation,
and no more than 2 minor violations total.

## Draft to Review

{draft_text}
"""


def run_quality_gate(
    client,
    model: str,
    draft_path: Path,
    tracker: UsageTracker | None = None,
) -> dict:
    """Run the quality gate on a draft file.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        draft_path: Path to the draft markdown file.
        tracker: Optional usage tracker.

    Returns:
        Dict with keys: pass (bool), violations (list), summary (str).
        Returns {"pass": False, "violations": [], "summary": "..."} on error.
    """
    draft_text = draft_path.read_text(encoding="utf-8")
    prompt = QUALITY_PROMPT.format(draft_text=draft_text)

    response = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "quality_gate")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        passed = result.get("pass", False)
        violations = result.get("violations", [])
        summary = result.get("summary", "")

        if passed:
            logger.info(f"Quality gate PASSED: {draft_path.name}")
        else:
            logger.warning(
                f"Quality gate FAILED: {draft_path.name} "
                f"({len(violations)} violation(s)): {summary}"
            )

        return {"pass": passed, "violations": violations, "summary": summary}
    except json.JSONDecodeError:
        logger.warning(f"Could not parse quality gate response: {text[:200]}")
        return {"pass": False, "violations": [], "summary": "Failed to parse quality check"}

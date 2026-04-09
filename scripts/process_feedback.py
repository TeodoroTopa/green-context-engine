#!/usr/bin/env python3
"""Process rejected drafts from Notion and extract reusable writing rules.

Two-phase approach:
  Phase 1 — Batch-extract candidate rules from ALL rejections at once.
            If multiple rejections raise the same issue, one rule is produced.
  Phase 2 — Merge candidates into the existing ruleset: keep valid rules,
            refine wording, add new ones, merge near-duplicates.

Rules are saved to config/feedback_rules.yaml and loaded into the drafter
prompt on subsequent runs, so the pipeline learns from mistakes.

Processed rejections are archived in Notion to avoid reprocessing.
"""

import json
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.claude_code_client import ClaudeCodeClient
from pipeline.publishing.notion import NotionPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

RULES_FILE = Path("config/feedback_rules.yaml")

BATCH_EXTRACTION_PROMPT = """\
You are extracting editorial rules from rejection feedback on AI-generated
energy briefs. A human editor rejected these drafts and wrote feedback
explaining why.

For each rejection below, extract the minimum number of concise, reusable
writing rules that would prevent similar mistakes in ANY future brief.
If multiple rejections raise the SAME underlying issue, produce ONE rule
that covers all of them.

{rejections_block}

<guidelines>
- Extract as FEW rules as possible — one rule per distinct issue across all
  rejections. One rule is ideal. Two or three is fine if the feedback raises
  genuinely distinct issues. Never pad with rules the feedback doesn't support.
- If two rejections both complain about the same kind of mistake, that is ONE
  rule, not two.
- Make each rule GENERAL, not article-specific. It should apply to all future
  briefs.
- Bad: "Don't mention Hurricane Maria in Puerto Rico articles"
- Good: "Don't reference historical events unless the source article mentions them"
- Bad: "Indonesia's deforestation should be explained more"
- Good: "Always explain what drives a trend, not just that the trend exists"
- Keep each rule to one sentence, actionable and clear.
- Focus on the underlying writing principle, not the specific facts or country.
</guidelines>

Return JSON only: {{"candidate_rules": ["first rule", "second rule if needed"]}}
"""

RULESET_MERGE_PROMPT = """\
You maintain a set of editorial writing rules for an AI energy brief pipeline.
Below are the CURRENT rules and CANDIDATE new rules extracted from recent
rejection feedback. Return the complete updated ruleset.

<current_rules>
{current_rules}
</current_rules>

<candidate_rules>
{candidate_rules}
</candidate_rules>

<instructions>
1. KEEP existing rules that are still valid and not affected by candidates.
2. REFINE an existing rule's wording when a candidate improves on it or
   makes the same point more clearly. Do not keep both — merge into one.
3. ADD candidates that are genuinely new and not already covered.
4. MERGE near-duplicate rules (existing or candidate) into a single clearer rule.
5. REMOVE an existing rule ONLY if a candidate explicitly contradicts it.
6. Each rule: one sentence, general (not article-specific), actionable.
7. Fewer rules is better. Merge when possible.
</instructions>

Return the COMPLETE updated ruleset as JSON only: {{"rules": ["rule one", "rule two", ...]}}
"""


def _format_rejections(rejections: list[dict]) -> str:
    """Format all rejections as XML blocks for the batch extraction prompt."""
    blocks = []
    for i, r in enumerate(rejections, 1):
        draft_text = r.get("draft_text", "")
        block = (
            f"<rejection_{i}>\n"
            f"<title>{r['title']}</title>\n"
            f"<draft>\n{draft_text}\n</draft>\n"
            f"<feedback>{r['feedback']}</feedback>\n"
            f"</rejection_{i}>"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _format_numbered(rules: list[str]) -> str:
    """Format rules as a numbered list for the merge prompt."""
    if not rules:
        return "(no existing rules yet)"
    return "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))


def _format_bulleted(rules: list[str]) -> str:
    """Format rules as a bulleted list for the merge prompt."""
    return "\n".join(f"- {r}" for r in rules)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from Claude response, stripping code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _diff_log(old_rules: list[str], new_rules: list[str]):
    """Log what changed between old and new ruleset."""
    old_set = set(old_rules)
    new_set = set(new_rules)
    added = new_set - old_set
    removed = old_set - new_set

    for rule in added:
        logger.info(f"  + Added: {rule}")
    for rule in removed:
        logger.info(f"  - Removed: {rule}")
    logger.info(
        f"  Ruleset: {len(old_rules)} rules → {len(new_rules)} rules "
        f"({len(added)} added, {len(removed)} removed)"
    )


def main():
    load_dotenv()

    notion = NotionPublisher()
    rejections = notion.get_rejected_feedback()

    if not rejections:
        logger.info("No rejected drafts with feedback to process")
        return

    logger.info(f"Found {len(rejections)} rejected draft(s) with feedback")

    # Load existing rules
    if RULES_FILE.exists():
        config = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8")) or {}
    else:
        config = {}
    rules = config.get("rules", [])

    # Set up Claude client
    mode = os.getenv("PIPELINE_MODE", "prod")
    if mode in ("dev", "local"):
        client = ClaudeCodeClient()
    else:
        from anthropic import Anthropic
        client = Anthropic()

    # --- Phase 1: Batch-extract candidate rules from all rejections ---
    logger.info("Phase 1: Extracting candidate rules from all rejections")
    rejections_block = _format_rejections(rejections)
    prompt1 = BATCH_EXTRACTION_PROMPT.format(rejections_block=rejections_block)

    try:
        response1 = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt1}],
        )
        result1 = _parse_json_response(response1.content[0].text)
        candidates = result1.get("candidate_rules", [])
        # Handle legacy single-rule format
        if not candidates and result1.get("rule"):
            candidates = [result1["rule"]]
    except Exception as e:
        logger.warning(f"Phase 1 failed: {e}")
        candidates = []

    if not candidates:
        logger.info("No candidate rules extracted from feedback")
        _mark_rejections_processed(notion)
        return

    for c in candidates:
        logger.info(f"  Candidate: {c}")

    # --- Phase 2: Merge candidates with existing ruleset ---
    logger.info("Phase 2: Merging candidates with existing ruleset")
    try:
        prompt2 = RULESET_MERGE_PROMPT.format(
            current_rules=_format_numbered(rules),
            candidate_rules=_format_bulleted(candidates),
        )
        response2 = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt2}],
        )
        result2 = _parse_json_response(response2.content[0].text)
        updated_rules = result2.get("rules", [])
        if not updated_rules:
            raise ValueError("Empty rules list returned from merge")
    except Exception as e:
        # Fallback: append candidates with simple dedup
        logger.warning(f"Phase 2 failed ({e}), falling back to simple append")
        updated_rules = rules[:]
        for c in candidates:
            if c not in updated_rules:
                updated_rules.append(c)

    # Diff log + save
    _diff_log(rules, updated_rules)
    config["rules"] = updated_rules
    RULES_FILE.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info(f"Updated {RULES_FILE}")

    # Mark processed rejections so they aren't reprocessed
    _mark_rejections_processed(notion)


def _mark_rejections_processed(notion: NotionPublisher):
    """Update rejected pages to 'Rejected - Processed' in Notion."""
    rejected_pages = notion.get_pages_by_status("Rejected")
    for page in rejected_pages:
        try:
            notion.update_status(page["id"], "Rejected - Processed")
            logger.info(f"Marked processed: {page['title'][:50]}")
        except Exception as e:
            logger.warning(f"Failed to update status for {page['title']}: {e}")


if __name__ == "__main__":
    main()

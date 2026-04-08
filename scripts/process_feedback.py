#!/usr/bin/env python3
"""Process rejected drafts from Notion and extract reusable writing rules.

Reads rejection feedback, uses Claude to distill it into generalized rules,
and appends them to config/feedback_rules.yaml. These rules are loaded into
the drafter prompt on subsequent runs, so the pipeline learns from mistakes.

Processed rejections are archived in Notion to avoid reprocessing.
"""

import json
import logging
import os
import sys
from pathlib import Path

import requests
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

RULE_EXTRACTION_PROMPT = """\
You are distilling editorial feedback into a generalized writing rule.

A human editor rejected an AI-generated energy brief and wrote feedback
explaining why. You have both the rejected draft and the feedback. Extract
the minimum number of concise, reusable rules that would prevent similar
mistakes in ANY future brief — not just this specific article.

<guidelines>
- Extract as FEW rules as possible — only what the feedback actually calls for.
  One rule is ideal. Two or three is fine if the feedback raises genuinely
  distinct issues. Never pad with rules the feedback doesn't support.
- Make each rule GENERAL, not article-specific. It should apply to all future briefs.
- Bad: "Don't mention Hurricane Maria in Puerto Rico articles"
- Good: "Don't reference historical events unless the source article mentions them"
- Bad: "Indonesia's deforestation should be explained more"
- Good: "Always explain what drives a trend, not just that the trend exists"
- Keep each rule to one sentence, actionable and clear.
- Focus on the underlying writing principle, not the specific facts or country involved.
</guidelines>

<draft>
{draft_text}
</draft>

<feedback>
Article: {title}
Editor feedback: {feedback}
</feedback>

Return JSON only: {{"rules": ["first rule", "second rule if needed"]}}
"""


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

    new_rules = []
    for rejection in rejections:
        title = rejection["title"]
        feedback = rejection["feedback"]
        logger.info(f"Processing: {title[:60]}")
        logger.info(f"  Feedback: {feedback[:100]}")

        draft_text = rejection.get("draft_text", "")
        prompt = RULE_EXTRACTION_PROMPT.format(
            title=title, feedback=feedback, draft_text=draft_text,
        )

        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(text)
            extracted = result.get("rules", [])
            # Handle legacy single-rule format
            if not extracted and result.get("rule"):
                extracted = [result["rule"]]
            for rule in extracted:
                if rule and rule not in rules:
                    rules.append(rule)
                    new_rules.append(rule)
                    logger.info(f"  New rule: {rule}")
                elif rule in rules:
                    logger.info(f"  Rule already exists, skipping")
        except Exception as e:
            logger.warning(f"  Failed to extract rule: {e}")

    # Save updated rules
    if new_rules:
        config["rules"] = rules
        RULES_FILE.write_text(
            yaml.dump(config, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        logger.info(f"Added {len(new_rules)} new rule(s) to {RULES_FILE}")

    # Archive processed rejections so they don't get reprocessed
    rejected_pages = notion.get_pages_by_status("Rejected")
    for page in rejected_pages:
        try:
            requests.patch(
                f"https://api.notion.com/v1/pages/{page['id']}",
                headers=notion.headers,
                json={"archived": True},
                timeout=15,
            )
            logger.info(f"Archived: {page['title'][:50]}")
        except requests.RequestException as e:
            logger.warning(f"Failed to archive {page['title']}: {e}")


if __name__ == "__main__":
    main()

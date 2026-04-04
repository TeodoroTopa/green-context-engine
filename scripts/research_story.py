#!/usr/bin/env python3
"""Standalone research tool — enrich and draft a brief for any story URL.

Usage:
    python scripts/research_story.py --url "https://..." --title "..." --summary "..."

This uses the core pipeline (enrich → draft → edit) without any Notion or
website publishing. Output is a markdown file in content/drafts/.
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.models import Story
from pipeline.orchestrator import Pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Research and draft a brief for a news story.",
    )
    parser.add_argument("--url", required=True, help="URL of the news story")
    parser.add_argument("--title", required=True, help="Story headline")
    parser.add_argument("--summary", default="", help="Brief summary of the story")
    parser.add_argument("--source", default="manual", help="Source name (default: manual)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    story = Story(
        title=args.title,
        url=args.url,
        summary=args.summary or args.title,
        published="",
        source=args.source,
        feed_name="manual",
    )

    pipeline = Pipeline()
    try:
        enriched, draft_path, edit_result = pipeline.research_and_draft(story)
        print(f"\nDraft saved: {draft_path}")
        print(f"Editor: {'PASSED' if edit_result['pass'] else 'FAILED'}")
        if not edit_result["pass"]:
            print(f"  Summary: {edit_result.get('summary', '')}")
    except ValueError as e:
        print(f"\nSkipped: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""CLI script to process approved drafts from the Notion editorial queue.

Polls Notion for pages with Status = "Approved", matches them to local
draft files, moves them to content/approved/, and updates Notion to "Published".

Usage:
    python scripts/publish_approved.py
    python scripts/publish_approved.py --dry-run   # show what would happen without changing anything
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.publishing.approval import (
    APPROVED_DIR,
    DRAFTS_DIR,
    find_matching_draft,
    process_approved,
)
from pipeline.publishing.notion import NotionPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Process approved drafts from Notion")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving files or updating Notion",
    )
    args = parser.parse_args()

    load_dotenv()

    try:
        notion = NotionPublisher()
    except ValueError as e:
        logger.error(f"Cannot connect to Notion: {e}")
        sys.exit(1)

    if args.dry_run:
        pages = notion.get_pages_by_status("Approved")
        if not pages:
            print("No approved pages found.")
            return

        print(f"\nFound {len(pages)} approved page(s):\n")
        for page in pages:
            draft = find_matching_draft(page["title"])
            status = f"→ {draft.name}" if draft else "⚠ No matching draft found"
            print(f"  [{page['source']}] {page['title']}")
            print(f"    {status}\n")
        return

    results = process_approved(notion)

    if not results:
        print("No approved pages to process.")
        return

    print(f"\nProcessed {len(results)} page(s):\n")
    for r in results:
        icon = "✓" if r["status"] == "published" else "✗"
        print(f"  {icon} {r['title']} — {r['status']}")
        if r.get("draft_path"):
            print(f"    → {r['draft_path']}")
    print()


if __name__ == "__main__":
    main()

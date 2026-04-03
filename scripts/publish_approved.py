"""CLI script to process approved drafts from the Notion editorial queue.

Polls Notion for pages with Status = "Approved", reads their content
directly from Notion, and updates status to "Published".

Usage:
    python scripts/publish_approved.py
    python scripts/publish_approved.py --dry-run   # show what would happen
"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.publishing.approval import process_approved
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
        help="Show what would happen without updating Notion",
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
            markdown = notion.get_page_as_markdown(page["id"])
            preview = markdown[:200].replace("\n", " ") + "..." if len(markdown) > 200 else markdown
            print(f"  [{page['source']}] {page['title']}")
            print(f"    Content: {len(markdown)} chars")
            print(f"    Preview: {preview[:100]}\n")
        return

    results = process_approved(notion)

    if not results:
        print("No approved pages to process.")
        return

    print(f"\nProcessed {len(results)} page(s):\n")
    for r in results:
        icon = "+" if r["status"] == "published" else "x"
        extra = f" ({r.get('content_length', 0)} chars)" if r.get("content_length") else ""
        print(f"  {icon} {r['title']} -- {r['status']}{extra}")
        if r.get("pr_url"):
            print(f"    PR: {r['pr_url']}")
    print()


if __name__ == "__main__":
    main()

"""Approval processing — detects approved drafts in Notion and prepares for publishing.

Polls the Notion editorial queue for pages with Status = "Approved",
matches them to local draft files, moves them to content/approved/,
and updates the Notion status to "Published".

The actual website publishing step is a placeholder — will be wired
to a GitHub API push once the website repo is ready.
"""

import logging
import re
import shutil
from pathlib import Path

from pipeline.publishing.notion import NotionPublisher

logger = logging.getLogger(__name__)

DRAFTS_DIR = Path("content/drafts")
APPROVED_DIR = Path("content/approved")


def find_matching_draft(title: str, drafts_dir: Path = DRAFTS_DIR) -> Path | None:
    """Find a draft file that matches a Notion page title.

    Matches by checking if a slugified version of the title appears
    in the draft filename, or by reading YAML frontmatter titles.

    Args:
        title: The story title from Notion.
        drafts_dir: Directory to search for draft files.

    Returns:
        Path to the matching draft, or None.
    """
    if not drafts_dir.exists():
        return None

    # Slugify the title the same way the drafter does
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")

    # Try filename match first (fastest)
    for draft in drafts_dir.glob("*.md"):
        if slug in draft.stem:
            return draft

    # Fallback: check YAML frontmatter title
    for draft in drafts_dir.glob("*.md"):
        text = draft.read_text(encoding="utf-8")
        match = re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        if match and _titles_match(title, match.group(1)):
            return draft

    return None


def _titles_match(notion_title: str, draft_title: str) -> bool:
    """Check if two titles are close enough to be the same story."""
    # Normalize: lowercase, strip punctuation, collapse whitespace
    def normalize(t):
        return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()
    # Check if one contains the other (titles may differ slightly)
    a, b = normalize(notion_title), normalize(draft_title)
    return a in b or b in a or a == b


def publish_to_website(draft_path: Path) -> bool:
    """Placeholder for publishing a draft to the website.

    Will be replaced with a GitHub API push once the website repo
    is configured. For now, just logs what would happen.

    Returns:
        True (always succeeds in placeholder mode).
    """
    logger.info(f"[PLACEHOLDER] Would publish to website: {draft_path.name}")
    return True


def process_approved(
    notion: NotionPublisher,
    drafts_dir: Path = DRAFTS_DIR,
    approved_dir: Path = APPROVED_DIR,
) -> list[dict]:
    """Process all approved pages: match drafts, move files, update Notion.

    Args:
        notion: NotionPublisher instance.
        drafts_dir: Where draft files live.
        approved_dir: Where to move approved files.

    Returns:
        List of dicts with processing results for each page.
    """
    approved_pages = notion.get_pages_by_status("Approved")
    if not approved_pages:
        logger.info("No approved pages found")
        return []

    approved_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for page in approved_pages:
        title = page["title"]
        page_id = page["id"]
        result = {"title": title, "page_id": page_id, "status": "skipped"}

        # Find the matching draft file
        draft_path = find_matching_draft(title, drafts_dir)
        if not draft_path:
            logger.warning(f"No local draft found for '{title}'")
            result["status"] = "no_draft_found"
            results.append(result)
            continue

        # Move to approved directory
        dest = approved_dir / draft_path.name
        shutil.move(str(draft_path), str(dest))
        logger.info(f"Moved {draft_path.name} → content/approved/")
        result["draft_path"] = str(dest)

        # Placeholder: publish to website
        publish_to_website(dest)

        # Update Notion status
        notion.update_status(page_id, "Published")
        result["status"] = "published"
        results.append(result)

    return results

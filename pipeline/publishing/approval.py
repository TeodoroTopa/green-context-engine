"""Approval processing — detects approved drafts in Notion and prepares for publishing.

Polls the Notion editorial queue for pages with Status = "Approved",
reads their content directly from Notion (single source of truth),
and updates the Notion status to "Published".

The actual website publishing step is a placeholder — will be wired
to a GitHub API push once the website repo is ready.
"""

import logging

from pipeline.publishing.notion import NotionPublisher

logger = logging.getLogger(__name__)


def publish_to_website(title: str, markdown: str) -> bool:
    """Placeholder for publishing a draft to the website.

    Will be replaced with a GitHub API push once the website repo
    is configured. For now, just logs what would happen.

    Args:
        title: The post title (used for commit message / filename).
        markdown: The full markdown content with frontmatter.

    Returns:
        True (always succeeds in placeholder mode).
    """
    logger.info(f"[PLACEHOLDER] Would publish to website: {title} ({len(markdown)} chars)")
    return True


def process_approved(notion: NotionPublisher) -> list[dict]:
    """Process all approved pages: read from Notion, publish, update status.

    Args:
        notion: NotionPublisher instance.

    Returns:
        List of dicts with processing results for each page.
    """
    approved_pages = notion.get_pages_by_status("Approved")
    if not approved_pages:
        logger.info("No approved pages found")
        return []

    results = []

    for page in approved_pages:
        title = page["title"]
        page_id = page["id"]
        result = {"title": title, "page_id": page_id, "status": "skipped"}

        # Read full markdown from Notion
        markdown = notion.get_page_as_markdown(page_id)
        if not markdown:
            logger.warning(f"Could not read content for '{title}' from Notion")
            result["status"] = "no_content"
            results.append(result)
            continue

        # Publish (placeholder)
        publish_to_website(title, markdown)

        # Update Notion status
        notion.update_status(page_id, "Published")
        result["status"] = "published"
        result["content_length"] = len(markdown)
        results.append(result)

    return results

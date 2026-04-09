"""Approval processing — detects approved drafts in Notion and publishes to the website.

Polls the Notion editorial queue for pages with Status = "Approved",
reads their content directly from Notion (single source of truth),
pushes the markdown to the website repo via GitHub API (as a PR),
and updates the Notion status to "Published".
"""

import base64
import logging
import os
import re

import requests

from pipeline.publishing.notion import NotionPublisher

logger = logging.getLogger(__name__)

WEBSITE_REPO = "TeodoroTopa/teodorotopa_personal_website"
WEBSITE_CONTENT_PATH = "content/energy"
GITHUB_API = "https://api.github.com"


def _slugify(title: str) -> str:
    """Convert a title to a filename slug (matches drafter convention)."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")


def _get_github_token() -> str | None:
    """Get the GitHub token for the website repo."""
    return os.getenv("WEBSITE_GITHUB_TOKEN")


def _find_existing_by_slug(slug: str, headers: dict) -> dict | None:
    """Check if a file with the same slug already exists in content/energy/.

    Filenames are {date}_{slug}.md. A story re-drafted on a different day
    gets a different date prefix but the same slug, so we match on slug only.

    Returns:
        Dict with 'path', 'sha', 'name' if found, None otherwise.
    """
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/contents/{WEBSITE_CONTENT_PATH}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        for item in resp.json():
            name = item.get("name", "")
            # Strip date prefix (YYYY-MM-DD_) and extension (.md) to get slug
            if name.endswith(".md") and "_" in name:
                existing_slug = name.split("_", 1)[1].removesuffix(".md")
                if existing_slug == slug:
                    return {"path": item["path"], "sha": item["sha"], "name": name}
    except requests.RequestException:
        pass
    return None


def publish_to_website(title: str, markdown: str, date_str: str = "") -> dict:
    """Publish a markdown post directly to main on the website repo.

    Commits the file to content/energy/ on main, which triggers
    an automatic Vercel rebuild. Post goes live within ~60 seconds.

    Deduplicates by slug: if a file with the same slugified title already
    exists (regardless of date prefix), it updates that file in place
    rather than creating a duplicate.

    Args:
        title: The post title.
        markdown: The full markdown content with frontmatter.
        date_str: Date string for the filename (YYYY-MM-DD). Defaults to today.

    Returns:
        Dict with keys: success (bool), url (str or None), error (str or None).
    """
    token = _get_github_token()
    if not token:
        logger.warning("WEBSITE_GITHUB_TOKEN not set — skipping website publish")
        return {"success": False, "url": None, "error": "No GitHub token configured"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    if not date_str:
        from datetime import date
        date_str = date.today().isoformat()
    slug = _slugify(title)
    filename = f"{date_str}_{slug}.md"
    file_path = f"{WEBSITE_CONTENT_PATH}/{filename}"

    try:
        content_b64 = base64.b64encode(markdown.encode("utf-8")).decode("ascii")
        payload = {
            "message": f"Publish: {title}",
            "content": content_b64,
            "branch": "main",
        }

        # Check if exact file already exists (need its SHA to update)
        existing = requests.get(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/contents/{file_path}",
            headers=headers,
            timeout=15,
        )
        if existing.status_code == 200:
            payload["sha"] = existing.json()["sha"]
            payload["message"] = f"Update: {title}"
            logger.info(f"File exists — updating {filename}")
        else:
            # Check for same slug with a different date prefix (re-draft dedup)
            match = _find_existing_by_slug(slug, headers)
            if match:
                file_path = match["path"]
                payload["sha"] = match["sha"]
                payload["message"] = f"Update: {title}"
                logger.info(
                    f"Found existing file with same slug: {match['name']} — "
                    f"updating in place instead of creating duplicate"
                )

        resp = requests.put(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/contents/{file_path}",
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()

        # URL uses the actual file path (may be the old date if updating in place)
        published_name = file_path.split("/")[-1].removesuffix(".md")
        post_url = f"https://teodorotopa.com/energy/{published_name}"
        logger.info(f"Published to website: {post_url}")

        return {"success": True, "url": post_url, "error": None}

    except requests.RequestException as e:
        logger.error(f"Failed to publish to website: {e}")
        return {"success": False, "url": None, "error": str(e)}


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

        # Publish to website
        pub_result = publish_to_website(title, markdown)
        result["url"] = pub_result.get("url")

        if pub_result["success"]:
            notion.update_status(page_id, "Published")
            result["status"] = "published"
            result["content_length"] = len(markdown)
        else:
            result["status"] = f"publish_failed: {pub_result.get('error', 'unknown')}"
            logger.error(f"Did not update Notion status — publish failed for '{title}'")

        results.append(result)

    return results

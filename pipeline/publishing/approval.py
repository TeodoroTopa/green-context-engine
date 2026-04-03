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

WEBSITE_REPO = "TeodoroTopa/simple-developer-portfolio-website"
WEBSITE_CONTENT_PATH = "content/energy"
GITHUB_API = "https://api.github.com"


def _slugify(title: str) -> str:
    """Convert a title to a filename slug (matches drafter convention)."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")


def _get_github_token() -> str | None:
    """Get the GitHub token for the website repo."""
    return os.getenv("WEBSITE_GITHUB_TOKEN")


def publish_to_website(title: str, markdown: str, date_str: str = "") -> dict:
    """Publish a markdown post to the website repo via GitHub PR.

    Creates a new branch, commits the markdown file, and opens a PR.

    Args:
        title: The post title.
        markdown: The full markdown content with frontmatter.
        date_str: Date string for the filename (YYYY-MM-DD). Defaults to today.

    Returns:
        Dict with keys: success (bool), pr_url (str or None), error (str or None).
    """
    token = _get_github_token()
    if not token:
        logger.warning("WEBSITE_GITHUB_TOKEN not set — skipping website publish")
        return {"success": False, "pr_url": None, "error": "No GitHub token configured"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # Build filename
    if not date_str:
        from datetime import date
        date_str = date.today().isoformat()
    slug = _slugify(title)
    filename = f"{date_str}_{slug}.md"
    file_path = f"{WEBSITE_CONTENT_PATH}/{filename}"
    branch_name = f"energy/{date_str}_{slug}"

    try:
        # 1. Get the SHA of main branch
        resp = requests.get(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/git/ref/heads/main",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        main_sha = resp.json()["object"]["sha"]

        # 2. Create a new branch
        resp = requests.post(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": main_sha},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Created branch: {branch_name}")

        # 3. Commit the file to the new branch
        content_b64 = base64.b64encode(markdown.encode("utf-8")).decode("ascii")
        resp = requests.put(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/contents/{file_path}",
            headers=headers,
            json={
                "message": f"Publish: {title}",
                "content": content_b64,
                "branch": branch_name,
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Committed {filename} to {branch_name}")

        # 4. Open a PR
        resp = requests.post(
            f"{GITHUB_API}/repos/{WEBSITE_REPO}/pulls",
            headers=headers,
            json={
                "title": f"Publish: {title}",
                "head": branch_name,
                "base": "main",
                "body": (
                    f"Auto-generated energy intelligence brief.\n\n"
                    f"**File:** `{file_path}`\n\n"
                    f"Merging will trigger a Vercel rebuild and the post "
                    f"will be live at teodorotopa.com/energy/{date_str}_{slug}"
                ),
            },
            timeout=15,
        )
        resp.raise_for_status()
        pr_url = resp.json().get("html_url", "")
        logger.info(f"Opened PR: {pr_url}")

        return {"success": True, "pr_url": pr_url, "error": None}

    except requests.RequestException as e:
        logger.error(f"Failed to publish to website: {e}")
        return {"success": False, "pr_url": None, "error": str(e)}


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
        result["pr_url"] = pub_result.get("pr_url")

        if pub_result["success"]:
            notion.update_status(page_id, "Published")
            result["status"] = "published"
            result["content_length"] = len(markdown)
        else:
            result["status"] = f"publish_failed: {pub_result.get('error', 'unknown')}"
            logger.error(f"Did not update Notion status — publish failed for '{title}'")

        results.append(result)

    return results

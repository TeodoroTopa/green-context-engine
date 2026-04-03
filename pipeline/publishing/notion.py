"""Notion API integration — pushes drafts to the editorial queue.

Uses the Notion API directly via requests (no MCP dependency),
so this works from standalone Python scripts.

Requires NOTION_TOKEN env var (an internal integration token).
Set up at https://www.notion.so/my-integrations — create an integration,
then share the editorial queue database with it.
"""

import logging
import os
import re
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionPublisher:
    """Pushes drafts and metadata to the Notion editorial queue."""

    def __init__(self, database_id: str | None = None, token: str | None = None):
        self.token = token or os.getenv("NOTION_TOKEN")
        if not self.token:
            raise ValueError(
                "NOTION_TOKEN not set. Create an integration at "
                "https://www.notion.so/my-integrations and add the token to .env"
            )
        self.database_id = database_id or self._load_database_id()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _load_database_id(self) -> str:
        """Load database ID from config/publishing.yaml."""
        config_path = Path("config/publishing.yaml")
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            db_id = cfg.get("notion", {}).get("database_id")
            if db_id:
                return db_id
        raise ValueError("No database_id found in config/publishing.yaml or constructor")

    def create_story(self, title: str, source_url: str = "", source_name: str = "", topics: list[str] | None = None) -> str | None:
        """Create a Notion page for a newly discovered story (status: Queued).

        Returns:
            The Notion page ID if successful, None otherwise.
        """
        properties = {
            "Story Title": {"title": [{"text": {"content": title}}]},
            "Status": {"select": {"name": "Queued"}},
        }
        if source_name:
            properties["Source"] = {"select": {"name": source_name}}
        if source_url:
            properties["userDefined:URL"] = {"url": source_url}
        if topics:
            properties["Topics"] = {"multi_select": [{"name": t} for t in topics]}

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            resp = requests.post(
                f"{NOTION_API}/pages",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            page_id = resp.json()["id"]
            logger.info(f"Queued in Notion: {title} (page {page_id})")
            return page_id
        except requests.RequestException as e:
            logger.error(f"Failed to create Notion page: {e}")
            return None

    def update_status(self, page_id: str, status: str) -> bool:
        """Update the status of an existing Notion page.

        Args:
            page_id: The Notion page ID.
            status: New status value (Queued, Enriching, Drafted, Review, Approved, Published).

        Returns:
            True if successful.
        """
        payload = {
            "properties": {
                "Status": {"select": {"name": status}},
            }
        }
        try:
            resp = requests.patch(
                f"{NOTION_API}/pages/{page_id}",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            logger.debug(f"Updated Notion page {page_id} → {status}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to update Notion status: {e}")
            return False

    def push_draft(self, draft_path: Path, source_url: str = "", source_name: str = "", topics: list[str] | None = None) -> str | None:
        """Create a page in the editorial queue for a draft.

        Args:
            draft_path: Path to the saved draft markdown file.
            source_url: URL of the original article.
            source_name: Name of the source (e.g. "Mongabay").
            topics: List of topic tags.

        Returns:
            The Notion page ID if successful, None otherwise.
        """
        frontmatter = self._parse_frontmatter(draft_path)
        title = frontmatter.get("title", draft_path.stem)

        properties = {
            "Story Title": {"title": [{"text": {"content": title}}]},
            "Status": {"select": {"name": "Drafted"}},
        }

        if source_name:
            properties["Source"] = {"select": {"name": source_name}}
        if source_url:
            properties["userDefined:URL"] = {"url": source_url}
        if frontmatter.get("date"):
            properties["Date Found"] = {"date": {"start": self._normalize_date(frontmatter["date"])}}
        if topics:
            properties["Topics"] = {"multi_select": [{"name": t} for t in topics]}

        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }

        try:
            resp = requests.post(
                f"{NOTION_API}/pages",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            page_id = resp.json()["id"]
            logger.info(f"Pushed to Notion: {title} (page {page_id})")
            return page_id
        except requests.RequestException as e:
            logger.error(f"Failed to push to Notion: {e}")
            return None

    def append_content(self, page_id: str, draft_path: Path) -> bool:
        """Append the draft body as content blocks to an existing Notion page.

        Args:
            page_id: The Notion page ID.
            draft_path: Path to the saved draft markdown file.

        Returns:
            True if successful.
        """
        body = self._extract_body(draft_path)
        if not body:
            logger.warning(f"No body content found in {draft_path}")
            return False

        blocks = self._markdown_to_blocks(body)
        if not blocks:
            return False

        payload = {"children": blocks}
        try:
            resp = requests.patch(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            logger.info(f"Appended {len(blocks)} content blocks to page {page_id}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to append content to Notion page: {e}")
            return False

    def _extract_body(self, path: Path) -> str:
        """Extract the markdown body (everything after YAML frontmatter)."""
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n.+?\n---\s*\n?", text, re.DOTALL)
        if match:
            return text[match.end():].strip()
        return text.strip()

    def _markdown_to_blocks(self, markdown: str) -> list[dict]:
        """Convert markdown text to Notion block objects.

        Handles: headings (##), bold (**), italic (*), dividers (---),
        and plain paragraphs. Chunks rich text at 2000 chars per item.
        """
        blocks = []
        for line in markdown.split("\n"):
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Divider
            if re.match(r"^---+$", stripped):
                blocks.append({"object": "block", "type": "divider", "divider": {}})
                continue

            # Heading 2 (## ...)
            heading_match = re.match(r"^##\s+(.+)", stripped)
            if heading_match:
                text = heading_match.group(1).strip()
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": self._parse_rich_text(text)},
                })
                continue

            # Heading 3 (### ...)
            heading3_match = re.match(r"^###\s+(.+)", stripped)
            if heading3_match:
                text = heading3_match.group(1).strip()
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": self._parse_rich_text(text)},
                })
                continue

            # Regular paragraph
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": self._parse_rich_text(stripped)},
            })

        return blocks

    def _parse_rich_text(self, text: str) -> list[dict]:
        """Parse markdown inline formatting into Notion rich text items.

        Handles **bold** and *italic*. Chunks at 2000 chars per item.
        """
        items = []
        # Split on bold (**...**) and italic (*...*)
        # Pattern: match **bold**, *italic*, or plain text
        pattern = r"(\*\*[^*]+?\*\*|\*[^*]+?\*)"
        parts = re.split(pattern, text)

        for part in parts:
            if not part:
                continue

            annotations = {"bold": False, "italic": False}
            content = part

            if part.startswith("**") and part.endswith("**"):
                content = part[2:-2]
                annotations["bold"] = True
            elif part.startswith("*") and part.endswith("*"):
                content = part[1:-1]
                annotations["italic"] = True

            # Chunk at 2000 chars per Notion API limit
            for i in range(0, len(content), 2000):
                chunk = content[i:i + 2000]
                items.append({
                    "type": "text",
                    "text": {"content": chunk},
                    "annotations": annotations,
                })

        return items if items else [{"type": "text", "text": {"content": ""}}]

    def _parse_frontmatter(self, path: Path) -> dict:
        """Extract YAML frontmatter from a markdown file."""
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.+?)\n---", text, re.DOTALL)
        if match:
            try:
                return yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                pass
        return {}

    def _normalize_date(self, date_val) -> str:
        """Convert various date formats to ISO 8601 (YYYY-MM-DD)."""
        if isinstance(date_val, str):
            # Try parsing common formats
            import datetime
            for fmt in ("%Y-%m-%d", "%d %b %Y %H:%M:%S %z", "%d %b %Y"):
                try:
                    return datetime.datetime.strptime(date_val.strip(), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            # Return as-is if we can't parse it
            return date_val[:10]
        return str(date_val)

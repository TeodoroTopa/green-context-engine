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
    """Pushes draft metadata to the Notion editorial queue."""

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
            properties["URL"] = {"url": source_url}
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

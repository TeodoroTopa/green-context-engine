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

    def find_page_by_url(self, url: str) -> str | None:
        """Check if a page with this source URL already exists in the database.

        Args:
            url: The source article URL.

        Returns:
            The page ID if found, None otherwise.
        """
        if not url:
            return None
        payload = {
            "filter": {
                "property": "URL",
                "url": {"equals": url},
            }
        }
        try:
            resp = requests.post(
                f"{NOTION_API}/databases/{self.database_id}/query",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                return results[0]["id"]
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to check for existing page: {e}")
            return None

    def create_story(self, title: str, source_url: str = "", source_name: str = "", topics: list[str] | None = None, published_date: str = "") -> str | None:
        """Create a Notion page for a newly discovered story (status: Queued).

        Checks for duplicates by source URL first. If a page with the same
        URL already exists, returns its ID instead of creating a new one.

        Returns:
            The Notion page ID if successful, None otherwise.
        """
        # Duplicate check
        existing = self.find_page_by_url(source_url)
        if existing:
            logger.info(f"Page already exists for URL: {title} (page {existing})")
            return existing

        properties = {
            "Story Title": {"title": [{"text": {"content": title}}]},
            "Status": {"select": {"name": "Review"}},
        }
        if source_name:
            properties["Source"] = {"select": {"name": source_name}}
        if source_url:
            properties["URL"] = {"url": source_url}
        if published_date:
            properties["Date Found"] = {"date": {"start": self._normalize_date(published_date)}}
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

    def get_pages_by_status(self, status: str) -> list[dict]:
        """Query the database for pages with a given status.

        Args:
            status: Status value to filter by (e.g. "Approved", "Drafted").

        Returns:
            List of page dicts with keys: id, title, url, source.
        """
        payload = {
            "filter": {
                "property": "Status",
                "select": {"equals": status},
            }
        }
        try:
            resp = requests.post(
                f"{NOTION_API}/databases/{self.database_id}/query",
                headers=self.headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

            pages = []
            for page in results:
                props = page.get("properties", {})
                title_arr = props.get("Story Title", {}).get("title", [])
                title = title_arr[0]["text"]["content"] if title_arr else ""
                url = props.get("URL", {}).get("url", "")
                source = props.get("Source", {}).get("select", {})
                pages.append({
                    "id": page["id"],
                    "title": title,
                    "url": url,
                    "source": source.get("name", "") if source else "",
                })
            logger.info(f"Found {len(pages)} pages with status '{status}'")
            return pages
        except requests.RequestException as e:
            logger.error(f"Failed to query Notion database: {e}")
            return []

    def get_rejected_feedback(self) -> list[dict]:
        """Get all rejected pages with their feedback notes.

        Returns:
            List of dicts with keys: title, url, feedback.
        """
        pages = self.get_pages_by_status("Rejected")
        results = []
        for page in pages:
            # Fetch full page to get Feedback property
            try:
                resp = requests.get(
                    f"{NOTION_API}/pages/{page['id']}",
                    headers=self.headers, timeout=15,
                )
                resp.raise_for_status()
                props = resp.json().get("properties", {})
                feedback_rt = props.get("Feedback", {}).get("rich_text", [])
                feedback = "".join(item.get("text", {}).get("content", "") for item in feedback_rt)
                if feedback:
                    results.append({
                        "title": page["title"],
                        "url": page.get("url", ""),
                        "feedback": feedback,
                    })
            except requests.RequestException as e:
                logger.warning(f"Failed to read feedback for {page['title']}: {e}")
        return results

    def get_page_content(self, page_id: str) -> str:
        """Fetch a page's content blocks and convert back to markdown.

        Args:
            page_id: The Notion page ID.

        Returns:
            Markdown string of the page body (no frontmatter).
        """
        try:
            resp = requests.get(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=self.headers,
                params={"page_size": 100},
                timeout=15,
            )
            resp.raise_for_status()
            blocks = resp.json().get("results", [])
            return self._blocks_to_markdown(blocks)
        except requests.RequestException as e:
            logger.error(f"Failed to fetch page content: {e}")
            return ""

    def get_page_as_markdown(self, page_id: str) -> str:
        """Fetch a full page as markdown with YAML frontmatter.

        Reads page properties for metadata and block children for body.

        Args:
            page_id: The Notion page ID.

        Returns:
            Complete markdown string with frontmatter + body.
        """
        try:
            # Fetch page properties
            resp = requests.get(
                f"{NOTION_API}/pages/{page_id}",
                headers=self.headers,
                timeout=15,
            )
            resp.raise_for_status()
            page = resp.json()
            props = page.get("properties", {})

            # Extract metadata
            title_arr = props.get("Story Title", {}).get("title", [])
            title = title_arr[0]["text"]["content"] if title_arr else "Untitled"
            url = props.get("URL", {}).get("url", "")
            source_sel = props.get("Source", {}).get("select", {})
            source_name = source_sel.get("name", "") if source_sel else ""
            date_prop = props.get("Date Found", {}).get("date", {})
            date_str = date_prop.get("start", "") if date_prop else ""

            # Fallback date: use today if Date Found not set
            if not date_str:
                import datetime
                date_str = datetime.date.today().isoformat()

            # Build frontmatter
            # Title links to source and shows attribution
            display_title = title
            if source_name:
                display_title = f"{title} ({source_name})"

            lines = [
                "---",
                f'title: "{display_title}"',
                f"date: {date_str}",
                f"source_url: {url}" if url else None,
                "sources:",
            ]
            lines = [l for l in lines if l is not None]
            if source_name and url:
                lines.append(f"  - name: {source_name}")
                lines.append(f"    url: {url}")
            lines.append("  - name: Ember")
            lines.append("    url: https://ember-energy.org")
            lines.append("status: approved")
            lines.append("---")

            # Fetch body
            body = self.get_page_content(page_id)
            return "\n".join(lines) + "\n\n" + body

        except requests.RequestException as e:
            logger.error(f"Failed to fetch page as markdown: {e}")
            return ""

    def _blocks_to_markdown(self, blocks: list[dict]) -> str:
        """Convert Notion block objects back to markdown text."""
        lines = []
        for block in blocks:
            block_type = block.get("type", "")

            if block_type == "divider":
                lines.append("\n---\n")
            elif block_type == "heading_2":
                text = self._rich_text_to_markdown(block["heading_2"].get("rich_text", []))
                lines.append(f"\n## {text}\n")
            elif block_type == "heading_3":
                text = self._rich_text_to_markdown(block["heading_3"].get("rich_text", []))
                lines.append(f"\n### {text}\n")
            elif block_type == "paragraph":
                text = self._rich_text_to_markdown(block["paragraph"].get("rich_text", []))
                if text:
                    lines.append(f"\n{text}\n")
            # Skip unknown block types silently

        return "\n".join(lines).strip()

    def _rich_text_to_markdown(self, rich_text: list[dict]) -> str:
        """Convert Notion rich text items back to markdown inline formatting."""
        parts = []
        for item in rich_text:
            text = item.get("text", {}).get("content", "")
            annotations = item.get("annotations", {})
            if annotations.get("bold"):
                text = f"**{text}**"
            elif annotations.get("italic"):
                text = f"*{text}*"
            parts.append(text)
        return "".join(parts)

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

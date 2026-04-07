"""Tests for the Notion publisher."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from pipeline.publishing.notion import NotionPublisher


@patch("pipeline.publishing.notion.requests")
def test_create_story_sends_correct_payload(mock_requests):
    """create_story sends a POST to Notion with status Review."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "page-123"}
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    page_id = pub.create_story("Test Story", source_url="https://example.com", source_name="Mongabay")

    assert page_id == "page-123"
    call_args = mock_requests.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["properties"]["Status"]["select"]["name"] == "Review"
    assert payload["properties"]["Story Title"]["title"][0]["text"]["content"] == "Test Story"


@patch("pipeline.publishing.notion.requests")
def test_update_status_sends_patch(mock_requests):
    """update_status sends a PATCH to update the page status."""
    mock_resp = MagicMock()
    mock_requests.patch.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.update_status("page-123", "Enriching")

    assert result is True
    call_args = mock_requests.patch.call_args
    assert "page-123" in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert payload["properties"]["Status"]["select"]["name"] == "Enriching"


@patch("pipeline.publishing.notion.requests")
def test_push_draft_parses_frontmatter(mock_requests, tmp_path):
    """push_draft extracts title from YAML frontmatter."""
    draft = tmp_path / "test-draft.md"
    draft.write_text('---\ntitle: "My Draft Title"\ndate: 2026-04-03\nstatus: draft\n---\n\nContent here.')

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "page-456"}
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    page_id = pub.push_draft(draft, source_url="https://example.com", source_name="Test")

    assert page_id == "page-456"
    call_args = mock_requests.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["properties"]["Story Title"]["title"][0]["text"]["content"] == "My Draft Title"


@patch("pipeline.publishing.notion.requests")
def test_push_draft_handles_api_error(mock_requests, tmp_path):
    """push_draft returns None on API error."""
    import requests as real_requests

    draft = tmp_path / "test-draft.md"
    draft.write_text("---\ntitle: Test\n---\n\nContent.")

    # Keep the real exception class so except clause works
    mock_requests.RequestException = real_requests.RequestException
    mock_requests.post.side_effect = real_requests.RequestException("API down")

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.push_draft(draft)
    assert result is None


def test_markdown_to_blocks_headings_and_paragraphs():
    """_markdown_to_blocks converts headings, paragraphs, and dividers."""
    pub = NotionPublisher(database_id="db-id", token="fake-token")
    md = "## The Hook\n\nSome paragraph text.\n\n---\n\n### Sub-heading\n\n**Bold text** and *italic text*."
    blocks = pub._markdown_to_blocks(md)

    assert blocks[0]["type"] == "heading_2"
    assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "The Hook"

    assert blocks[1]["type"] == "paragraph"
    assert blocks[1]["paragraph"]["rich_text"][0]["text"]["content"] == "Some paragraph text."

    assert blocks[2]["type"] == "divider"

    assert blocks[3]["type"] == "heading_3"
    assert blocks[3]["heading_3"]["rich_text"][0]["text"]["content"] == "Sub-heading"

    # Bold + italic paragraph
    para_rich = blocks[4]["paragraph"]["rich_text"]
    bold_item = [r for r in para_rich if r["annotations"]["bold"]]
    italic_item = [r for r in para_rich if r["annotations"]["italic"]]
    assert len(bold_item) == 1
    assert bold_item[0]["text"]["content"] == "Bold text"
    assert len(italic_item) == 1
    assert italic_item[0]["text"]["content"] == "italic text"


def test_parse_rich_text_chunks_long_content():
    """Rich text items over 2000 chars get chunked."""
    pub = NotionPublisher(database_id="db-id", token="fake-token")
    long_text = "A" * 4500
    items = pub._parse_rich_text(long_text)
    assert len(items) == 3
    assert len(items[0]["text"]["content"]) == 2000
    assert len(items[1]["text"]["content"]) == 2000
    assert len(items[2]["text"]["content"]) == 500


def test_extract_body_strips_frontmatter(tmp_path):
    """_extract_body returns content after YAML frontmatter."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\ndate: 2026-04-03\n---\n\n## The Hook\n\nContent here.')

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    body = pub._extract_body(draft)
    assert body.startswith("## The Hook")
    assert "title:" not in body


@patch("pipeline.publishing.notion.requests")
def test_append_content_sends_blocks(mock_requests, tmp_path):
    """append_content sends PATCH with children blocks."""
    draft = tmp_path / "test.md"
    draft.write_text('---\ntitle: "Test"\n---\n\n## Heading\n\nParagraph text.')

    mock_resp = MagicMock()
    mock_requests.patch.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.append_content("page-123", draft)

    assert result is True
    call_args = mock_requests.patch.call_args
    assert "blocks/page-123/children" in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert "children" in payload
    assert len(payload["children"]) == 2  # heading + paragraph

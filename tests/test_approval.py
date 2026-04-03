"""Tests for the approval processing module."""

from unittest.mock import MagicMock, patch

from pipeline.publishing.approval import process_approved


@patch("pipeline.publishing.approval.publish_to_website", return_value=True)
def test_process_approved_reads_from_notion(mock_publish):
    """process_approved reads content from Notion and publishes."""
    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Test Story", "url": "", "source": "Mongabay"}
    ]
    notion.get_page_as_markdown.return_value = "---\ntitle: Test\n---\n\n## Hook\n\nContent."
    notion.update_status.return_value = True

    results = process_approved(notion)

    assert len(results) == 1
    assert results[0]["status"] == "published"
    assert results[0]["content_length"] > 0
    notion.get_page_as_markdown.assert_called_once_with("page-1")
    notion.update_status.assert_called_once_with("page-1", "Published")
    mock_publish.assert_called_once_with("Test Story", notion.get_page_as_markdown.return_value)


def test_process_approved_handles_empty_content():
    """process_approved skips pages with no readable content."""
    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Empty Page", "url": "", "source": ""}
    ]
    notion.get_page_as_markdown.return_value = ""

    results = process_approved(notion)

    assert len(results) == 1
    assert results[0]["status"] == "no_content"
    notion.update_status.assert_not_called()


def test_process_approved_no_approved_pages():
    """process_approved returns empty list when nothing is approved."""
    notion = MagicMock()
    notion.get_pages_by_status.return_value = []

    results = process_approved(notion)
    assert results == []


@patch("pipeline.publishing.notion.requests")
def test_get_pages_by_status(mock_requests):
    """get_pages_by_status queries Notion with a status filter."""
    from pipeline.publishing.notion import NotionPublisher

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{
            "id": "page-abc",
            "properties": {
                "Story Title": {"title": [{"text": {"content": "My Story"}}]},
                "userDefined:URL": {"url": "https://example.com"},
                "Source": {"select": {"name": "Mongabay"}},
            },
        }]
    }
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    pages = pub.get_pages_by_status("Approved")

    assert len(pages) == 1
    assert pages[0]["id"] == "page-abc"
    assert pages[0]["title"] == "My Story"
    call_payload = mock_requests.post.call_args.kwargs["json"]
    assert call_payload["filter"]["select"]["equals"] == "Approved"


def test_blocks_to_markdown():
    """_blocks_to_markdown converts Notion blocks back to markdown."""
    from pipeline.publishing.notion import NotionPublisher

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "The Hook"}, "annotations": {}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Some text."}, "annotations": {}}]}},
        {"type": "divider", "divider": {}},
        {"type": "paragraph", "paragraph": {"rich_text": [
            {"text": {"content": "Bold part"}, "annotations": {"bold": True}},
            {"text": {"content": " and "}, "annotations": {}},
            {"text": {"content": "italic"}, "annotations": {"italic": True}},
        ]}},
    ]
    md = pub._blocks_to_markdown(blocks)

    assert "## The Hook" in md
    assert "Some text." in md
    assert "---" in md
    assert "**Bold part**" in md
    assert "*italic*" in md


def test_rich_text_to_markdown():
    """_rich_text_to_markdown handles bold and italic annotations."""
    from pipeline.publishing.notion import NotionPublisher

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    rich_text = [
        {"text": {"content": "Normal "}, "annotations": {}},
        {"text": {"content": "bold"}, "annotations": {"bold": True}},
        {"text": {"content": " and "}, "annotations": {}},
        {"text": {"content": "italic"}, "annotations": {"italic": True}},
    ]
    result = pub._rich_text_to_markdown(rich_text)
    assert result == "Normal **bold** and *italic*"

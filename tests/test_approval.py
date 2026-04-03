"""Tests for the approval processing module."""

from unittest.mock import MagicMock, patch

from pipeline.publishing.approval import process_approved, _slugify


def test_slugify():
    """_slugify matches the drafter's filename convention."""
    assert _slugify("Solar Surge in Germany!") == "solar-surge-in-germany"
    assert _slugify("Indonesia's Deforestation") == "indonesia-s-deforestation"
    long_title = "A" * 100
    assert len(_slugify(long_title)) <= 50


@patch("pipeline.publishing.approval.publish_to_website")
def test_process_approved_reads_from_notion(mock_publish):
    """process_approved reads content from Notion and publishes."""
    mock_publish.return_value = {"success": True, "url": "https://teodorotopa.com/energy/test", "error": None}

    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Test Story", "url": "", "source": "Mongabay"}
    ]
    notion.get_page_as_markdown.return_value = "---\ntitle: Test\n---\n\n## Hook\n\nContent."
    notion.update_status.return_value = True

    results = process_approved(notion)

    assert len(results) == 1
    assert results[0]["status"] == "published"
    assert results[0]["url"] == "https://teodorotopa.com/energy/test"
    notion.get_page_as_markdown.assert_called_once_with("page-1")
    notion.update_status.assert_called_once_with("page-1", "Published")


@patch("pipeline.publishing.approval.publish_to_website")
def test_process_approved_skips_publish_on_failure(mock_publish):
    """process_approved does not update Notion if publish fails."""
    mock_publish.return_value = {"success": False, "url": None, "error": "API error"}

    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Test Story", "url": "", "source": ""}
    ]
    notion.get_page_as_markdown.return_value = "---\ntitle: Test\n---\n\nContent."

    results = process_approved(notion)

    assert len(results) == 1
    assert "publish_failed" in results[0]["status"]
    notion.update_status.assert_not_called()


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
def test_find_page_by_url_returns_existing(mock_requests):
    """find_page_by_url returns page ID when URL already exists."""
    from pipeline.publishing.notion import NotionPublisher

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{"id": "page-existing"}]
    }
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.find_page_by_url("https://example.com/article")

    assert result == "page-existing"
    call_payload = mock_requests.post.call_args.kwargs["json"]
    assert call_payload["filter"]["property"] == "userDefined:URL"
    assert call_payload["filter"]["url"]["equals"] == "https://example.com/article"


@patch("pipeline.publishing.notion.requests")
def test_find_page_by_url_returns_none_when_not_found(mock_requests):
    """find_page_by_url returns None when no match."""
    from pipeline.publishing.notion import NotionPublisher

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.find_page_by_url("https://example.com/new-article")

    assert result is None


@patch("pipeline.publishing.notion.requests")
def test_create_story_skips_duplicate(mock_requests):
    """create_story returns existing page ID if URL already in database."""
    from pipeline.publishing.notion import NotionPublisher

    # First call: query returns existing page. Second call: shouldn't happen.
    query_resp = MagicMock()
    query_resp.json.return_value = {"results": [{"id": "page-dup"}]}
    mock_requests.post.return_value = query_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    result = pub.create_story("Test", source_url="https://example.com/existing")

    assert result == "page-dup"
    # Only one POST call (the query), not two (query + create)
    assert mock_requests.post.call_count == 1


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

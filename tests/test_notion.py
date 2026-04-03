"""Tests for the Notion publisher."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from pipeline.publishing.notion import NotionPublisher


@patch("pipeline.publishing.notion.requests")
def test_create_story_sends_correct_payload(mock_requests):
    """create_story sends a POST to Notion with status Queued."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "page-123"}
    mock_requests.post.return_value = mock_resp

    pub = NotionPublisher(database_id="db-id", token="fake-token")
    page_id = pub.create_story("Test Story", source_url="https://example.com", source_name="Mongabay")

    assert page_id == "page-123"
    call_args = mock_requests.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["properties"]["Status"]["select"]["name"] == "Queued"
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

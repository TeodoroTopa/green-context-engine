"""Tests for the approval processing module."""

from unittest.mock import MagicMock, patch

from pipeline.publishing.approval import (
    find_matching_draft,
    process_approved,
    _titles_match,
)


def test_find_matching_draft_by_slug(tmp_path):
    """Finds a draft by slugified title in the filename."""
    draft = tmp_path / "2026-04-03_solar-surge-in-germany.md"
    draft.write_text("---\ntitle: Solar Surge in Germany\n---\n\nContent.")

    result = find_matching_draft("Solar surge in Germany", tmp_path)
    assert result == draft


def test_find_matching_draft_by_frontmatter(tmp_path):
    """Falls back to frontmatter title matching."""
    # Filename doesn't match, but frontmatter does
    draft = tmp_path / "2026-04-03_renamed-file.md"
    draft.write_text('---\ntitle: "Indonesia Deforestation Crisis"\n---\n\nContent.')

    result = find_matching_draft("Indonesia Deforestation Crisis", tmp_path)
    assert result == draft


def test_find_matching_draft_returns_none(tmp_path):
    """Returns None when no draft matches."""
    draft = tmp_path / "2026-04-03_unrelated-story.md"
    draft.write_text("---\ntitle: Unrelated Story\n---\n\nContent.")

    result = find_matching_draft("Solar Surge in Germany", tmp_path)
    assert result is None


def test_titles_match_handles_variations():
    """_titles_match normalizes punctuation and case."""
    assert _titles_match("Solar Surge!", "solar surge")
    assert _titles_match("Indonesia's Crisis", "indonesias crisis")
    assert not _titles_match("Solar in Germany", "Coal in China")


@patch("pipeline.publishing.approval.publish_to_website", return_value=True)
def test_process_approved_full_flow(mock_publish, tmp_path):
    """process_approved moves drafts and updates Notion status."""
    drafts = tmp_path / "drafts"
    approved = tmp_path / "approved"
    drafts.mkdir()

    draft_file = drafts / "2026-04-03_test-story-about-energy.md"
    draft_file.write_text("---\ntitle: Test Story About Energy\n---\n\nContent.")

    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Test Story About Energy", "url": "", "source": "Mongabay"}
    ]
    notion.update_status.return_value = True

    results = process_approved(notion, drafts_dir=drafts, approved_dir=approved)

    assert len(results) == 1
    assert results[0]["status"] == "published"
    assert (approved / "2026-04-03_test-story-about-energy.md").exists()
    assert not draft_file.exists()  # moved, not copied
    notion.update_status.assert_called_once_with("page-1", "Published")
    mock_publish.assert_called_once()


def test_process_approved_no_matching_draft(tmp_path):
    """process_approved handles missing draft files gracefully."""
    drafts = tmp_path / "drafts"
    approved = tmp_path / "approved"
    drafts.mkdir()

    notion = MagicMock()
    notion.get_pages_by_status.return_value = [
        {"id": "page-1", "title": "Nonexistent Draft", "url": "", "source": ""}
    ]

    results = process_approved(notion, drafts_dir=drafts, approved_dir=approved)

    assert len(results) == 1
    assert results[0]["status"] == "no_draft_found"
    notion.update_status.assert_not_called()


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
    assert pages[0]["source"] == "Mongabay"

    # Verify the filter was sent
    call_payload = mock_requests.post.call_args.kwargs["json"]
    assert call_payload["filter"]["property"] == "Status"
    assert call_payload["filter"]["select"]["equals"] == "Approved"

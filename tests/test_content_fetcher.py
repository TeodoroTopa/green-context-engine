"""Tests for the article content fetcher."""

from unittest.mock import patch, MagicMock

from pipeline.content.fetcher import fetch_article_text, _should_skip, _truncate
from pipeline.monitors.rss_monitor import Story


def _make_story(source="electrek", summary="Short teaser.", url="https://example.com/story"):
    return Story(
        title="Test Story", url=url, summary=summary,
        published="2026-04-06", source=source, feed_name=f"{source}_main",
    )


def test_does_not_skip_fetchable_sources():
    """Fetchable sources are not skipped."""
    assert _should_skip(_make_story(source="electrek"), None) is False
    assert _should_skip(_make_story(source="mongabay"), None) is False


def test_skips_when_config_says_false():
    """Sources with fetch_content: false in config are skipped."""
    config = [{"source": "carbonbrief", "fetch_content": False}]
    assert _should_skip(_make_story(source="carbonbrief"), config) is True


def test_skips_when_summary_already_long():
    """Stories with substantial RSS summaries don't need fetching."""
    long_summary = " ".join(["word"] * 250)
    assert _should_skip(_make_story(summary=long_summary), None) is True


def test_does_not_skip_short_summary():
    """Short RSS teasers should be fetched."""
    assert _should_skip(_make_story(summary="Short teaser."), None) is False


@patch("pipeline.content.fetcher.trafilatura")
@patch("pipeline.content.fetcher.requests")
def test_fetches_and_extracts_text(mock_requests, mock_trafilatura):
    """Full fetch path: download HTML, extract with trafilatura, return text."""
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><p>Full article text here with details.</p></body></html>"
    mock_requests.get.return_value = mock_resp
    mock_requests.RequestException = Exception

    mock_trafilatura.extract.return_value = "Full article text here with details."

    result = fetch_article_text(_make_story())
    assert "Full article text" in result
    mock_requests.get.assert_called_once()
    mock_trafilatura.extract.assert_called_once()


@patch("pipeline.content.fetcher.requests")
def test_returns_empty_on_http_error(mock_requests):
    """HTTP errors return empty string, don't crash."""
    mock_requests.get.side_effect = Exception("403 Forbidden")
    mock_requests.RequestException = Exception

    result = fetch_article_text(_make_story())
    assert result == ""


@patch("pipeline.content.fetcher.trafilatura")
@patch("pipeline.content.fetcher.requests")
def test_returns_empty_when_trafilatura_fails(mock_requests, mock_trafilatura):
    """If trafilatura can't extract text, return empty string."""
    mock_resp = MagicMock()
    mock_resp.text = "<html><body></body></html>"
    mock_requests.get.return_value = mock_resp
    mock_requests.RequestException = Exception
    mock_trafilatura.extract.return_value = None

    result = fetch_article_text(_make_story())
    assert result == ""


def test_truncation_at_word_boundary():
    """Truncation cuts at word boundary, not mid-word."""
    text = " ".join(f"word{i}" for i in range(1000))
    result = _truncate(text, max_words=800)
    assert len(result.split()) == 800
    assert result.endswith("word799")


def test_truncation_preserves_short_text():
    """Short text is returned unchanged."""
    text = "This is short."
    assert _truncate(text, max_words=800) == text

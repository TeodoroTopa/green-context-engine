"""Article content fetcher — downloads and extracts full article text from URLs.

Uses trafilatura for article extraction (handles boilerplate removal, nav stripping,
etc.). Falls back gracefully to empty string on any failure — the pipeline continues
with the RSS summary.
"""

import logging

import requests
import trafilatura

from pipeline.monitors.rss_monitor import Story

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Sources where fetching is known to fail (paywall, anti-bot, JS-only)
SKIP_SOURCES: set[str] = set()  # No sources currently need skipping

# If RSS summary already has this many words, skip fetching
SUMMARY_WORD_THRESHOLD = 200

# Max words to keep from extracted article
MAX_WORDS = 800


def fetch_article_text(story: Story, feeds_config: list[dict] | None = None) -> str:
    """Fetch and extract full article text for a story.

    Args:
        story: The story to fetch content for.
        feeds_config: Optional list of feed config dicts from feeds.yaml.
            Each can have a 'fetch_content' key (true/false).

    Returns:
        Extracted article text (truncated to MAX_WORDS), or empty string on failure.
    """
    # Check if source is configured to skip
    if _should_skip(story, feeds_config):
        return ""

    try:
        html = _download(story.url)
        if not html:
            return ""

        text = trafilatura.extract(html)
        if not text:
            logger.warning(f"trafilatura returned no text for {story.url}")
            return ""

        truncated = _truncate(text, MAX_WORDS)
        logger.info(f"Fetched {len(truncated.split())} words from {story.source}: {story.title[:50]}")
        return truncated

    except Exception as e:
        logger.warning(f"Failed to fetch article text for {story.url}: {e}")
        return ""


def _should_skip(story: Story, feeds_config: list[dict] | None) -> bool:
    """Check if we should skip fetching for this story."""
    # Check hardcoded skip list
    if story.source in SKIP_SOURCES:
        logger.debug(f"Skipping fetch for {story.source} (known unfetchable)")
        return True

    # Check per-feed config
    if feeds_config:
        for feed in feeds_config:
            if feed.get("source") == story.source:
                fetch_flag = feed.get("fetch_content")
                if fetch_flag is False:
                    logger.debug(f"Skipping fetch for {story.source} (config: fetch_content=false)")
                    return True
                break

    # If RSS summary is already substantial, skip
    word_count = len(story.summary.split())
    if word_count >= SUMMARY_WORD_THRESHOLD:
        logger.debug(f"Skipping fetch for {story.source} (summary already {word_count} words)")
        return True

    return False


def _download(url: str) -> str | None:
    """Download HTML from a URL with a realistic User-Agent."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=10,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"HTTP error fetching {url}: {e}")
        return None


def _truncate(text: str, max_words: int) -> str:
    """Truncate text to max_words on a word boundary."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])

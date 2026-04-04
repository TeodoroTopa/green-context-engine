"""Public API models — clean imports for external consumers.

Usage:
    from pipeline.models import Story, EnrichedStory
"""

from pipeline.monitors.rss_monitor import Story
from pipeline.analysis.enricher import EnrichedStory

__all__ = ["Story", "EnrichedStory"]

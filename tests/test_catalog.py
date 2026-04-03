"""Tests for the data catalog loader."""

from pipeline.analysis.catalog import load_catalog, get_available_sources


def test_load_catalog_returns_nonempty_string():
    """load_catalog reads YAML files and returns formatted text."""
    text = load_catalog()
    assert len(text) > 0
    assert "EMBER" in text
    assert "EIA" in text


def test_get_available_sources_returns_both():
    """get_available_sources finds ember and eia catalogs."""
    sources = get_available_sources()
    assert "ember" in sources
    assert "eia" in sources
    assert sources["ember"]["connector"] == "pipeline.sources.ember.EmberSource"
    assert "entities" in sources["ember"]


def test_catalog_contains_entity_groups():
    """The catalog text includes entity groups for the strategist."""
    text = load_catalog()
    assert "World" in text
    assert "OECD" in text
    assert "United States" in text
    # Countries in the first 10 of their region appear; others are truncated
    assert "China" in text

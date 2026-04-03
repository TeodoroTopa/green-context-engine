"""Tests for the file-based response cache."""

import json
import time

from pipeline.sources.cache import cache_key, get_cached, set_cached


def test_cache_key_is_deterministic():
    """Same URL + params should always produce the same key."""
    key1 = cache_key("https://example.com/api", {"a": 1, "b": 2})
    key2 = cache_key("https://example.com/api", {"b": 2, "a": 1})
    assert key1 == key2  # param order shouldn't matter (sorted internally)


def test_cache_key_differs_for_different_params():
    key1 = cache_key("https://example.com/api", {"entity": "Germany"})
    key2 = cache_key("https://example.com/api", {"entity": "France"})
    assert key1 != key2


def test_cache_miss_returns_none(tmp_path, monkeypatch):
    """get_cached returns None when nothing is cached."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    result = get_cached("nonexistent_key")
    assert result is None


def test_cache_roundtrip(tmp_path, monkeypatch):
    """set_cached then get_cached returns the original response."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    response = {"data": [{"entity": "Germany", "value": 42}]}
    set_cached("test_key", response)
    result = get_cached("test_key")
    assert result == response


def test_cache_expiry(tmp_path, monkeypatch):
    """Expired cache entries return None."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)

    # Write a cache entry with a timestamp in the past
    path = tmp_path / "old_key.json"
    old_time = time.time() - 100000  # well past any reasonable TTL
    path.write_text(json.dumps({"cached_at": old_time, "response": {"old": True}}))

    result = get_cached("old_key", ttl=3600)
    assert result is None


def test_cache_not_expired(tmp_path, monkeypatch):
    """Fresh cache entries are returned."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)

    path = tmp_path / "fresh_key.json"
    path.write_text(json.dumps({"cached_at": time.time(), "response": {"fresh": True}}))

    result = get_cached("fresh_key", ttl=3600)
    assert result == {"fresh": True}

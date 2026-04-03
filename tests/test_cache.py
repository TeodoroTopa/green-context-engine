"""Tests for the file-based response cache."""

import json
import time

from pipeline.sources.cache import cache_key, get_cached, set_cached


def test_cache_key_deterministic_regardless_of_param_order():
    key1 = cache_key("https://example.com/api", {"a": 1, "b": 2})
    key2 = cache_key("https://example.com/api", {"b": 2, "a": 1})
    assert key1 == key2


def test_cache_roundtrip(tmp_path, monkeypatch):
    """set then get returns the data; missing key returns None."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)

    assert get_cached("nonexistent") is None

    response = {"data": [{"entity": "Germany", "value": 42}]}
    set_cached("test_key", response)
    assert get_cached("test_key") == response


def test_cache_expiry(tmp_path, monkeypatch):
    """Expired entries return None."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)

    path = tmp_path / "old_key.json"
    old_time = time.time() - 100000
    path.write_text(json.dumps({"cached_at": old_time, "response": {"old": True}}))

    assert get_cached("old_key", ttl=3600) is None

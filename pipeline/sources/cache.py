"""File-based response cache for API calls.

Each cached response is stored as a JSON file in data/cache/.
Filename = SHA-256 hash of (url + sorted params).
File content = {"cached_at": <unix timestamp>, "response": <json response>}.

This avoids redundant API calls during development and respects rate limits.
"""

import hashlib
import json
import time
from pathlib import Path

CACHE_DIR = Path("data/cache")
DEFAULT_TTL = 86400  # 24 hours in seconds


def cache_key(url: str, params: dict) -> str:
    """Generate a deterministic cache key from a URL and its query params."""
    raw = url + json.dumps(params, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(key: str, ttl: int = DEFAULT_TTL) -> dict | None:
    """Return cached response if it exists and hasn't expired.

    Returns None on cache miss or expiry.
    """
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if time.time() - data["cached_at"] > ttl:
        return None
    return data["response"]


def set_cached(key: str, response: dict) -> None:
    """Write a response to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    payload = {"cached_at": time.time(), "response": response}
    path.write_text(json.dumps(payload), encoding="utf-8")

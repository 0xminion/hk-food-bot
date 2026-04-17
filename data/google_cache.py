"""
Shared Google Ratings Cache — single source of truth.

All modules that need Google ratings (loader, secret_gem, lazy_resolve)
import from here instead of loading the JSON independently.
Thread-safe for concurrent reads/writes from lazy_resolve background workers.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).parent / "google_ratings_cache.json"
_cache: Optional[dict] = None
_lock = threading.Lock()


def get_cache() -> dict:
    """Load and return the shared Google ratings cache (lazy, thread-safe)."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache

        if not _CACHE_FILE.exists():
            _cache = {}
            return _cache

        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"Loaded shared Google ratings cache: {len(_cache)} entries")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load Google cache: {e}")
            _cache = {}

        return _cache


def save_cache(cache: dict) -> None:
    """Save cache atomically (thread-safe)."""
    global _cache
    with _lock:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        tmp.rename(_CACHE_FILE)
        _cache = cache  # Update in-memory copy


def merge_and_save(updates: dict) -> None:
    """Merge new entries into the cache and persist (thread-safe).

    Unlike save_cache which replaces the entire cache, this merges
    only the provided entries — safe for concurrent writers.
    """
    global _cache
    with _lock:
        if _cache is None:
            _cache = {}
        for key, val in updates.items():
            if val.get("google_rating"):
                _cache[key] = val
        # Persist
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        tmp.rename(_CACHE_FILE)


def invalidate() -> None:
    """Force reload on next access (for data refresh)."""
    global _cache
    with _lock:
        _cache = None


def get_google_rating(name: str, address: str) -> Optional[dict]:
    """Get cached Google rating for a venue by name+address."""
    cache = get_cache()
    key = f"{name.strip()}|{address.strip()}"
    entry = cache.get(key)
    if entry and entry.get("google_rating"):
        return entry
    # Fallback: name-only match
    name_lower = name.strip().lower()
    for ck, cv in cache.items():
        if ck.split("|")[0].strip().lower() == name_lower:
            if cv.get("google_rating"):
                return cv
    return None

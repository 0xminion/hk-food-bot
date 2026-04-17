"""Tests for Google Maps rating resolver and cache management."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Cache Tests ───────────────────────────────────────────────────────────────

class TestCacheManagement:
    """Test cache loading, saving, and key generation."""

    def test_cache_key_generation(self):
        from scrapers.google_resolver import cache_key
        key = cache_key("Yardbird", "Sheung Wan, Hong Kong")
        assert key == "Yardbird|Sheung Wan, Hong Kong"

    def test_cache_key_strips_whitespace(self):
        from scrapers.google_resolver import cache_key
        key = cache_key("  Yardbird  ", "  Sheung Wan  ")
        assert key == "Yardbird|Sheung Wan"

    def test_load_cache_missing_file(self, tmp_path):
        from scrapers.google_resolver import load_cache
        with patch("scrapers.google_resolver.CACHE_FILE", tmp_path / "nonexistent.json"):
            cache = load_cache()
            assert cache == {}

    def test_load_cache_corrupt_file(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not valid json{{{")
        from scrapers.google_resolver import load_cache
        with patch("scrapers.google_resolver.CACHE_FILE", cache_file):
            cache = load_cache()
            assert cache == {}

    def test_save_and_load_cache(self, tmp_path):
        from scrapers.google_resolver import save_cache, load_cache
        cache_file = tmp_path / "cache.json"
        test_cache = {
            "Yardbird|Sheung Wan": {
                "google_rating": 4.5,
                "google_reviews": 1763,
                "resolved": True,
                "last_updated": "2026-04-13",
            }
        }
        with patch("scrapers.google_resolver.CACHE_FILE", cache_file):
            save_cache(test_cache)
            loaded = load_cache()
            assert loaded["Yardbird|Sheung Wan"]["google_rating"] == 4.5
            assert loaded["Yardbird|Sheung Wan"]["google_reviews"] == 1763

    def test_get_cached_returns_entry(self):
        from scrapers.google_resolver import get_cached
        cache = {
            "Yardbird|Sheung Wan": {
                "google_rating": 4.5,
                "google_reviews": 1763,
                "last_updated": "2026-04-13",
            }
        }
        result = get_cached(cache, "Yardbird", "Sheung Wan")
        assert result is not None
        assert result["google_rating"] == 4.5

    def test_get_cached_missing_entry(self):
        from scrapers.google_resolver import get_cached
        cache = {}
        result = get_cached(cache, "Yardbird", "Sheung Wan")
        assert result is None

    def test_get_cached_stale_entry(self):
        """Entries older than 90 days should return None."""
        from scrapers.google_resolver import get_cached
        cache = {
            "Old|Place": {
                "google_rating": 4.0,
                "google_reviews": 100,
                "last_updated": "2025-01-01",  # >90 days old
            }
        }
        result = get_cached(cache, "Old", "Place")
        assert result is None


# ── Secret Gem Source-Aware Tests ─────────────────────────────────────────────

class TestSecretGemSourceAware:
    """Test source-aware secret gem thresholds."""

    def _make_place(self, name="Test", address="", or_rating=0, google_rating=0,
                    review_count=0, style_tags=None):
        from data.loader import Place
        return Place(
            name=name,
            type="restaurant",
            cuisine_tags=["thai"],
            style_tags=style_tags or [],
            address=address,
            lat=22.3, lng=114.2,
            google_rating=google_rating,
            or_rating=or_rating,
            review_count=review_count,
            google_place_id="",
            booking_url="",
            booking_platform="",
            opening_hours="",
            source_url="",
            is_secret_gem=False,
            last_updated="",
            source="openrice",
            distance_walk_m=1000,
            distance_drive_m=1500,
        )

    def test_openrice_rule_a_high_rating_low_reviews(self):
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(or_rating=4.5, review_count=50)
        assert apply_secret_gem_rules(place) is True

    def test_openrice_rule_a_too_many_reviews(self):
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(or_rating=4.5, review_count=500)
        assert apply_secret_gem_rules(place) is False

    def test_google_data_overrides_openrice(self):
        """When Google cache exists, use Google thresholds."""
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(or_rating=3.5, review_count=500)

        google_entry = {
            "google_rating": 4.5,
            "google_reviews": 800,
        }

        with patch("data.google_cache.get_google_rating", return_value=google_entry):
            # 800 Google reviews < 1000 threshold → should be gem
            assert apply_secret_gem_rules(place) is True

    def test_google_data_mainstream_disqualifies(self):
        """Google >5000 reviews = mainstream, not a gem."""
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(or_rating=4.5, review_count=50)

        google_entry = {
            "google_rating": 4.5,
            "google_reviews": 6000,
        }

        with patch("data.google_cache.get_google_rating", return_value=google_entry):
            assert apply_secret_gem_rules(place) is False

    def test_mall_disqualifies(self):
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(
            name="Fancy Place",
            address="Shop 1, IFC Mall, Central",
            or_rating=4.5,
            review_count=50,
        )
        assert apply_secret_gem_rules(place) is False

    def test_no_rating_returns_false(self):
        from engine.secret_gem import apply_secret_gem_rules
        place = self._make_place(or_rating=0, google_rating=0, review_count=0)
        assert apply_secret_gem_rules(place) is False


# ── Lazy Resolve Tests ────────────────────────────────────────────────────────

class TestLazyResolve:
    """Test lazy resolution trigger and caching."""

    def test_needs_resolution_no_cache(self):
        from engine.lazy_resolve import needs_google_resolution
        with patch("data.google_cache.get_cache", return_value={}):
            assert needs_google_resolution("Test", "Address") is True

    def test_needs_resolution_cached(self):
        from engine.lazy_resolve import needs_google_resolution
        cache = {"Test|Address": {"google_rating": 4.5, "google_reviews": 100}}
        with patch("data.google_cache.get_cache", return_value=cache):
            assert needs_google_resolution("Test", "Address") is False

    def test_lazy_resolve_skips_cached(self):
        """lazy_resolve_places should not re-resolve already cached venues."""
        from engine.lazy_resolve import lazy_resolve_places
        cache = {"Test|Address": {"google_rating": 4.5, "google_reviews": 100}}

        place = MagicMock()
        place.name = "Test"
        place.address = "Address"

        with patch("data.google_cache.get_cache", return_value=cache):
            # Should not spawn a thread since venue is already cached
            lazy_resolve_places([place])
            # If it tried to resolve, it would fail since camoufox isn't mocked
            # The test passes if no exception is raised

    def test_empty_list_noop(self):
        from engine.lazy_resolve import lazy_resolve_places
        lazy_resolve_places([])  # Should not raise

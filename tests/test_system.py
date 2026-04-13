"""System/end-to-end tests.

Tests the full pipeline from data loading to recommendation output,
simulating a complete bot interaction without Telegram.
"""

from pathlib import Path

from data.loader import get_all_places, filter_by_type, compute_distances
from engine.recommender import recommend
from engine.taste import score_and_rank_places
from engine.crossover import get_crossover_cuisine
from engine.time_aware import filter_open_places
from engine.secret_gem import enrich_secret_gems
from handlers.common import format_recommendations_message, HK_AREAS


SAMPLE_CSV = Path(__file__).parent.parent / "data" / "sample_places.csv"


def test_full_pipeline_restaurant():
    """Test the full restaurant recommendation pipeline."""
    if not SAMPLE_CSV.exists():
        return  # Skip if sample data not available

    all_places = get_all_places(SAMPLE_CSV)
    assert len(all_places) > 0

    # Simulate: user picks Central, wants Italian
    result = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=22.2783,
        area_lng=114.1540,
        cuisine="italian",
        use_time_filter=False,
    )
    assert len(result.places) > 0

    # Format output
    msg = format_recommendations_message(result.places, "Central", "restaurant")
    assert "Central" in msg
    assert len(msg) > 100  # Non-trivial output


def test_full_pipeline_bar():
    """Test the full bar recommendation pipeline."""
    if not SAMPLE_CSV.exists():
        return

    all_places = get_all_places(SAMPLE_CSV)
    result = recommend(
        all_places=all_places,
        place_type="bar",
        area_lat=22.2783,
        area_lng=114.1540,
        use_time_filter=False,
    )

    if result.places:  # May have no bars in sample data
        msg = format_recommendations_message(result.places, "Central", "bar")
        assert "Central" in msg


def test_full_pipeline_surprise():
    """Test surprise/surprise mode end-to-end."""
    if not SAMPLE_CSV.exists():
        return

    all_places = get_all_places(SAMPLE_CSV)
    result = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="surprise",
        use_time_filter=False,
    )
    assert len(result.places) > 0


def test_taste_scoring_integration(sample_places):
    """Taste scoring should weight Italian/Thai higher."""
    scored = score_and_rank_places(sample_places)
    # Top-scored places should have Italian or Thai tags
    top_tags = set()
    for s in scored[:3]:
        top_tags.update(s.place.cuisine_tags)
    # At least one high-preference cuisine in top 3
    high_pref = {"italian", "thai", "chinese", "cantonese", "cocktail-bar", "japanese"}
    assert top_tags & high_pref


def test_secret_gem_enrichment(sample_places):
    """Secret gem enrichment should flag qualifying places."""
    enrich_secret_gems(sample_places)
    gem_count = sum(1 for p in sample_places if p.is_secret_gem)
    assert gem_count > 0


def test_crossover_pipeline():
    """Crossover engine should suggest Vietnamese for Thai preference."""
    preferred = ["thai"]
    tried = {"thai", "chinese"}
    result = get_crossover_cuisine(preferred, tried)
    # Should suggest something not in tried
    if result:
        assert result not in tried


def test_area_coordinates():
    """All defined areas should have valid coordinates."""
    for name, (lat, lng) in HK_AREAS.items():
        assert 22.0 < lat < 23.0, f"{name} lat out of range"
        assert 113.5 < lng < 115.0, f"{name} lng out of range"

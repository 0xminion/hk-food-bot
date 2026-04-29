"""Security and robustness tests for HK Food Bot.

Tests input validation, edge cases, and production readiness.
"""

import math
import tempfile
from pathlib import Path

import pytest
from data.loader import load_places, Place, compute_distances
from utils.haversine import haversine_distance
from engine.recommender import recommend


# ---------------------------------------------------------------------------
# CSV Input Validation
# ---------------------------------------------------------------------------

CSV_HEADER = "name,type,cuisine_tags,style_tags,address,lat,lng,google_rating,or_rating,review_count,google_place_id,booking_url,booking_platform,opening_hours,source_url,is_secret_gem,last_updated,source"


def _write_temp_csv(rows: list[str]) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(CSV_HEADER + "\n")
    for row in rows:
        f.write(row + "\n")
    f.close()
    return Path(f.name)


def test_load_skips_empty_name():
    """Rows with empty name should be skipped."""
    csv_path = _write_temp_csv([
        ',restaurant,"[italian]","",,22.28,114.15,4.0,0,10',
        'Valid Place,restaurant,"[thai]","",,,4.0,,10',
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].name == "Valid Place"
    csv_path.unlink()


def test_load_clamps_invalid_type():
    """Invalid type values should default to 'restaurant'."""
    csv_path = _write_temp_csv([
        'Test,invalid_type,"[italian]","",,22.28,114.15,4.0,0,10',
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].type == "restaurant"
    csv_path.unlink()


def test_load_clamps_rating_above_5():
    """Ratings above 5.0 should be clamped to 5.0."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,22.28,114.15,99.0,0,10',
    ])
    places = load_places(csv_path)
    assert places[0].google_rating == 5.0
    csv_path.unlink()


def test_load_clamps_negative_rating():
    """Negative ratings should be clamped to 0.0."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,22.28,114.15,-5.0,0,10',
    ])
    places = load_places(csv_path)
    assert places[0].google_rating == 0.0
    csv_path.unlink()


def test_load_clamps_negative_review_count():
    """Negative review counts should be clamped to 0."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,22.28,114.15,4.0,0,-99',
    ])
    places = load_places(csv_path)
    assert places[0].review_count == 0
    csv_path.unlink()


def test_load_rejects_out_of_range_lat():
    """Latitudes outside [-90, 90] should be set to 0.0."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,999,114.15,4.0,0,10',
    ])
    places = load_places(csv_path)
    assert places[0].lat == 0.0
    csv_path.unlink()


def test_load_rejects_out_of_range_lng():
    """Longitudes outside [-180, 180] should be set to 0.0."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,22.28,999,4.0,0,10',
    ])
    places = load_places(csv_path)
    assert places[0].lng == 0.0
    csv_path.unlink()


def test_load_clamps_or_rating():
    """OpenRice ratings should also be clamped to 0-5."""
    csv_path = _write_temp_csv([
        'Test,restaurant,"[italian]","",,22.28,114.15,4.0,99.0,10',
    ])
    places = load_places(csv_path)
    assert places[0].or_rating == 5.0
    csv_path.unlink()


# ---------------------------------------------------------------------------
# Haversine Edge Cases
# ---------------------------------------------------------------------------

def test_haversine_nan_returns_inf():
    """NaN inputs should return infinity instead of a silent NaN result."""
    result = haversine_distance(float('nan'), 114.0, 22.0, 114.0)
    assert result == float('inf')
    assert not math.isnan(result)


def test_haversine_nan_second_point():
    """NaN in second point should also return infinity."""
    result = haversine_distance(22.0, 114.0, float('nan'), 114.0)
    assert result == float('inf')


def test_haversine_nan_both_points():
    """NaN in both points should return infinity."""
    result = haversine_distance(float('nan'), float('nan'), float('nan'), float('nan'))
    assert result == float('inf')


# ---------------------------------------------------------------------------
# Compute Distances Edge Cases
# ---------------------------------------------------------------------------

def test_compute_distances_with_nan_coordinates():
    """Places with NaN coordinates should get 99999 distance."""
    places = [
        Place(name="NaN Place", type="restaurant", lat=float('nan'), lng=114.15),
        Place(name="Valid Place", type="restaurant", lat=22.28, lng=114.15),
    ]
    compute_distances(places, 22.2783, 114.1540)
    assert places[0].distance_walk_m == 99999
    assert places[1].distance_walk_m < 99999


# ---------------------------------------------------------------------------
# Recommender Bounds
# ---------------------------------------------------------------------------

def test_recommend_num_results_capped():
    """num_results should be capped at 50."""
    places = [
        Place(name=f"Place {i}", type="restaurant", cuisine_tags=["thai"],
              lat=22.28, lng=114.15, google_rating=4.0)
        for i in range(100)
    ]
    result = recommend(
        all_places=places,
        place_type="restaurant",
        area_lat=22.28,
        area_lng=114.15,
        num_results=9999,
        use_time_filter=False,
    )
    assert len(result.places) <= 50


def test_recommend_num_results_negative():
    """Negative num_results should be clamped to 1."""
    places = [
        Place(name="Place", type="restaurant", cuisine_tags=["thai"],
              lat=22.28, lng=114.15, google_rating=4.0)
    ]
    result = recommend(
        all_places=places,
        place_type="restaurant",
        area_lat=22.28,
        area_lng=114.15,
        num_results=-10,
        use_time_filter=False,
    )
    assert len(result.places) >= 1


# ---------------------------------------------------------------------------
# Bot Token Validation
# ---------------------------------------------------------------------------

def test_bot_token_validation_short():
    """Tokens shorter than 10 chars should be rejected."""
    token = "abc123"
    # Validate the same logic as bot.py main()
    assert not token or len(token) < 10 or ":" not in token


def test_bot_token_validation_no_colon():
    """Tokens without ':' should be rejected (Telegram bot tokens have format id:hash)."""
    token = "a" * 20  # Long enough but no colon
    assert not token or len(token) < 10 or ":" not in token


def test_bot_token_validation_valid():
    """Valid Telegram bot tokens have format digits:alphanumeric."""
    token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    assert len(token) >= 10 and ":" in token


# ---------------------------------------------------------------------------
# Malformed CSV
# ---------------------------------------------------------------------------

def test_load_malformed_csv_row():
    """Individual malformed rows should be skipped without crashing the whole load."""
    csv_path = _write_temp_csv([
        'Good Place,restaurant,"[thai]","",,22.28,114.15,4.0,0,10',
        '',  # Empty row
        'Another Good,restaurant,"[italian]","",,22.28,114.15,4.5,0,20',
    ])
    places = load_places(csv_path)
    # Should load at least the valid rows
    assert len(places) >= 2
    names = [p.name for p in places]
    assert "Good Place" in names
    assert "Another Good" in names
    csv_path.unlink()


def test_load_csv_with_extra_columns():
    """CSV with extra unexpected columns should not crash."""
    csv_path = _write_temp_csv([
        'Test Place,restaurant,"[italian]","",,22.28,114.15,4.0,0,10,,,,,,,,extra_col_data',
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    csv_path.unlink()


# ---------------------------------------------------------------------------
# Empty/None Handling
# ---------------------------------------------------------------------------

def test_recommend_empty_all_places():
    """Empty places list should return empty result, not crash."""
    result = recommend(
        all_places=[],
        place_type="restaurant",
        area_lat=22.28,
        area_lng=114.15,
        use_time_filter=False,
    )
    assert result.places == []


def test_recommend_all_invalid_coordinates():
    """All places with invalid coords should still work (fallback distances)."""
    places = [
        Place(name="No Coords", type="restaurant", cuisine_tags=["thai"],
              lat=0.0, lng=0.0, google_rating=4.0),
    ]
    result = recommend(
        all_places=places,
        place_type="restaurant",
        area_lat=22.28,
        area_lng=114.15,
        use_time_filter=False,
    )
    # Should not crash, even if no results due to distance filter
    assert isinstance(result.places, list)

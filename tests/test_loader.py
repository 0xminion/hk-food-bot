"""Tests for CSV data loader."""

import csv
import tempfile
from pathlib import Path

from data.loader import load_places, filter_by_type, filter_by_cuisine, get_unique_cuisines, Place


CSV_HEADER = "name,type,cuisine_tags,style_tags,address,lat,lng,google_rating,or_rating,review_count,google_place_id,booking_url,booking_platform,opening_hours,source_url,is_secret_gem,last_updated,source"


def _write_temp_csv(rows: list[str]) -> Path:
    """Write rows to a temp CSV file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(CSV_HEADER + "\n")
    for row in rows:
        f.write(row + "\n")
    f.close()
    return Path(f.name)


def test_load_single_place():
    """Test loading a single place from CSV."""
    csv_path = _write_temp_csv([
        'Test Place,restaurant,"[italian]",[],"123 Main St",22.28,114.15,4.5,,100,,https://chope.com/test,chope,Mo-Su 11:00-22:00,,false,2026-04-13,google_maps'
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].name == "Test Place"
    assert places[0].type == "restaurant"
    assert "italian" in places[0].cuisine_tags
    assert places[0].google_rating == 4.5
    assert places[0].review_count == 100
    csv_path.unlink()


def test_load_multiple_places():
    """Test loading multiple places."""
    csv_path = _write_temp_csv([
        'Place A,restaurant,"[thai]",[],"Addr A",22.28,114.15,4.0,,50,,,,,,false,2026-04-13,google_maps',
        'Place B,bar,"[cocktail-bar]",[],"Addr B",22.29,114.16,4.5,,200,,,,,,true,2026-04-13,google_maps',
    ])
    places = load_places(csv_path)
    assert len(places) == 2
    csv_path.unlink()


def test_filter_by_type(sample_places):
    """Test filtering by type."""
    restaurants = filter_by_type(sample_places, "restaurant")
    bars = filter_by_type(sample_places, "bar")
    assert len(restaurants) == 7
    assert len(bars) == 3
    assert all(p.type == "restaurant" for p in restaurants)
    assert all(p.type == "bar" for p in bars)


def test_filter_by_cuisine(sample_places):
    """Test filtering by cuisine."""
    thai = filter_by_cuisine(sample_places, ["thai"])
    assert len(thai) == 1
    assert thai[0].name == "Thai Basil"

    japanese = filter_by_cuisine(sample_places, ["japanese"])
    assert len(japanese) == 2  # Sushi Master + Ramen House


def test_filter_by_cuisine_case_insensitive(sample_places):
    """Cuisine filter should be case-insensitive."""
    result = filter_by_cuisine(sample_places, ["THAI"])
    assert len(result) == 1


def test_get_unique_cuisines(sample_places):
    """Test extracting unique cuisine tags."""
    cuisines = get_unique_cuisines(sample_places)
    assert "thai" in cuisines
    assert "italian" in cuisines
    assert "japanese" in cuisines
    assert "cocktail-bar" in cuisines


def test_load_nonexistent_file():
    """Loading a nonexistent file returns empty list."""
    places = load_places("/tmp/nonexistent.csv")
    assert places == []


def test_parse_tags_with_quotes():
    """Test tag parsing with various quote formats."""
    from data.loader import _parse_tags
    assert _parse_tags('["thai", "noodles"]') == ["thai", "noodles"]
    assert _parse_tags("thai,noodles") == ["thai", "noodles"]
    assert _parse_tags("") == []


def test_load_with_missing_fields():
    """CSV rows with missing fields should use defaults."""
    csv_path = _write_temp_csv([
        'Minimal Place,restaurant,"[italian]",[]'  # Only required fields
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].name == "Minimal Place"
    assert places[0].google_rating == 0.0
    assert places[0].review_count == 0
    assert places[0].address == ""
    csv_path.unlink()


def test_load_with_invalid_numeric_fields():
    """Non-numeric rating/review fields should default gracefully."""
    csv_path = _write_temp_csv([
        'Bad Data,restaurant,"[thai]",[],"",0,0,not_a_number,,also_not,,,,,,false,2026-04-13,'
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].google_rating == 0.0
    assert places[0].review_count == 0
    csv_path.unlink()


def test_load_empty_file():
    """Empty CSV (header only) returns empty list."""
    csv_path = _write_temp_csv([])
    places = load_places(csv_path)
    assert places == []
    csv_path.unlink()


def test_load_with_source_column():
    """CSV with source column should be parsed."""
    csv_path = _write_temp_csv([
        'Place With Source,restaurant,"[thai]",[],"",0,0,4.0,,10,,,,,,false,2026-04-13,openrice'
    ])
    places = load_places(csv_path)
    assert len(places) == 1
    assert places[0].source == "openrice"
    csv_path.unlink()

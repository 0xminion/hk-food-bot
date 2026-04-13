"""Integration tests for the recommendation pipeline."""

from engine.recommender import recommend, get_available_cuisines


def test_recommend_restaurants(sample_places):
    """Should return up to 5 restaurant recommendations."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="thai",
        use_time_filter=False,
    )
    assert len(result.places) > 0
    assert all(p.type == "restaurant" for p in result.places)


def test_recommend_bars(sample_places):
    """Should return bar recommendations."""
    result = recommend(
        all_places=sample_places,
        place_type="bar",
        area_lat=22.2783,
        area_lng=114.1540,
        use_time_filter=False,
    )
    assert len(result.places) > 0
    assert all(p.type == "bar" for p in result.places)


def test_recommend_surprise(sample_places):
    """Surprise mode should return results."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="surprise",
        use_time_filter=False,
    )
    assert len(result.places) > 0


def test_recommend_crossover_fallback(sample_places):
    """When few matches, should use crossover."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="french",  # No French in sample data
        use_time_filter=False,
    )
    assert len(result.places) > 0


def test_recommend_sorted_by_rating(sample_places):
    """Results should be sorted by rating descending."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        use_time_filter=False,
        use_taste_scoring=False,
    )
    for i in range(len(result.places) - 1):
        assert result.places[i].google_rating >= result.places[i + 1].google_rating


def test_get_available_cuisines(sample_places):
    """Should return cuisines available in the area."""
    cuisines = get_available_cuisines(sample_places, "restaurant", 22.2790, 114.1750)
    assert len(cuisines) > 0
    assert isinstance(cuisines, list)


def test_recommend_no_duplicates_in_fallback(sample_places):
    """Crossover fallback should not produce duplicate places."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="french",  # No French in sample → triggers crossover + nearby fallback
        use_time_filter=False,
    )
    names = [p.name for p in result.places]
    assert len(names) == len(set(names)), f"Duplicate places found: {names}"


def test_recommend_empty_places():
    """Should handle empty places list gracefully."""
    result = recommend(
        all_places=[],
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        use_time_filter=False,
    )
    assert result.places == []


def test_recommend_no_matches():
    """Should handle when type filter yields no results."""
    from data.loader import Place
    only_bars = [Place(name="Bar", type="bar", cuisine_tags=["cocktail-bar"])]
    result = recommend(
        all_places=only_bars,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        use_time_filter=False,
    )
    assert result.places == []


def test_recommend_num_results_zero(sample_places):
    """num_results=0 should not crash (clamped to 1)."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        num_results=0,
        use_time_filter=False,
    )
    assert len(result.places) >= 1

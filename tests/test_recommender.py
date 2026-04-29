"""Integration tests for the recommendation pipeline."""

import pytest

from engine.recommender import AREA_SCOPE_NEIGHBORS, _area_search_origins, recommend, get_available_cuisines


def test_area_scope_neighbor_map_is_direct_and_consistent():
    """The scope map should reflect the direct station-neighbor layout."""
    assert AREA_SCOPE_NEIGHBORS["Central"] == ["Central", "Sheung Wan", "Admiralty"]
    assert AREA_SCOPE_NEIGHBORS["Wan Chai"] == ["Wan Chai", "Causeway Bay", "Admiralty"]
    assert AREA_SCOPE_NEIGHBORS["Causeway Bay"] == ["Causeway Bay", "Wan Chai", "Tin Hau"]
    assert AREA_SCOPE_NEIGHBORS["Sheung Wan"] == ["Sheung Wan", "Central", "Sai Ying Pun"]
    assert AREA_SCOPE_NEIGHBORS["Sai Ying Pun"] == ["Sai Ying Pun", "Sheung Wan", "Kennedy Town"]
    assert AREA_SCOPE_NEIGHBORS["Admiralty"] == ["Admiralty", "Central", "Wan Chai"]
    assert AREA_SCOPE_NEIGHBORS["Tin Hau"] == ["Tin Hau", "Causeway Bay", "North Point"]
    assert AREA_SCOPE_NEIGHBORS["Kennedy Town"] == ["Kennedy Town", "Sai Ying Pun"]
    assert AREA_SCOPE_NEIGHBORS["TST"] == ["TST", "Jordan", "Yau Ma Tei"]
    assert AREA_SCOPE_NEIGHBORS["Mong Kok"] == ["Mong Kok", "Yau Ma Tei", "Prince Edward"]
    # Extended neighborhoods for UI consistency
    assert AREA_SCOPE_NEIGHBORS["North Point"] == ["North Point", "Tin Hau"]
    assert AREA_SCOPE_NEIGHBORS["Jordan"] == ["Jordan", "TST", "Yau Ma Tei"]
    assert AREA_SCOPE_NEIGHBORS["Yau Ma Tei"] == ["Yau Ma Tei", "Jordan", "TST", "Mong Kok", "Prince Edward"]
    assert AREA_SCOPE_NEIGHBORS["Prince Edward"] == ["Prince Edward", "Mong Kok", "Yau Ma Tei"]


@pytest.mark.parametrize(
    "area_name,expected_names",
    [
        ("Tin Hau", {"Tin Hau", "Causeway Bay", "North Point"}),
        ("TST", {"TST", "Jordan", "Yau Ma Tei"}),
        ("Mong Kok", {"Mong Kok", "Yau Ma Tei", "Prince Edward"}),
    ],
)
def test_area_scope_hidden_station_coords_resolve(area_name, expected_names):
    """Hidden neighbor stations should resolve to usable origins."""
    origins = _area_search_origins(area_name)
    assert {name for name, _, _ in origins} == expected_names


def test_recommend_surprise_with_rough_location_limits_radius(sample_places):
    """Surprise mode should honor the caller's rough location and stay within 2km."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="surprise",
        max_distance_m=2000,
        use_time_filter=False,
    )
    assert len(result.places) > 0
    assert all(p.distance_walk_m <= 2000 for p in result.places if p.distance_walk_m)


def test_recommend_ramen_stays_ramen(sample_places):
    """Explicit ramen selection should not drift into Italian/pizza garbage."""
    result = recommend(
        all_places=sample_places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="ramen",
        use_time_filter=False,
    )
    names = [p.name for p in result.places]
    assert names == ["Ramen House"]
    assert all("ramen" in p.cuisine_tags for p in result.places)


def test_recommend_french_does_not_backslide_into_bakery_or_dessert():
    from data.loader import Place

    places = [
        Place(name="French Table", type="restaurant", cuisine_tags=["french"]),
        Place(name="Bakery Corner", type="restaurant", cuisine_tags=["bakery"]),
        Place(name="Dessert Stop", type="restaurant", cuisine_tags=["dessert"]),
        Place(name="Italian Bistro", type="restaurant", cuisine_tags=["italian"]),
    ]
    result = recommend(
        all_places=places,
        place_type="restaurant",
        area_lat=22.2790,
        area_lng=114.1750,
        cuisine="french",
        use_time_filter=False,
        use_taste_scoring=False,
    )
    assert result.places[0].name == "French Table"
    assert all("bakery" not in p.cuisine_tags and "dessert" not in p.cuisine_tags for p in result.places)




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

"""Tests for taste profile scorer."""

from engine.taste import (
    get_cuisine_weight,
    score_place,
    score_and_rank_places,
    get_top_cuisines,
)
from data.loader import Place


def test_high_preference_cuisine():
    """Italian (weight 1.0) should score high."""
    place = Place(name="Test", type="restaurant", cuisine_tags=["italian"])
    score = score_place(place)
    assert score == 1.0


def test_low_preference_cuisine():
    """Unknown cuisine scores the default weight."""
    place = Place(name="Test", type="restaurant", cuisine_tags=["obscure-cuisine"])
    score = score_place(place)
    assert score == 0.2  # DEFAULT_CUISINE_WEIGHT


def test_no_cuisine_tags():
    """Place with no cuisine tags gets the default weight."""
    place = Place(name="Test", type="restaurant", cuisine_tags=[])
    score = score_place(place)
    assert score == 0.2  # DEFAULT_CUISINE_WEIGHT


def test_multiple_cuisine_bonus():
    """Multiple matching tags get a small bonus."""
    single = Place(name="A", type="restaurant", cuisine_tags=["thai"])
    multi = Place(name="B", type="restaurant", cuisine_tags=["thai", "vietnamese"])
    score_single = score_place(single)
    score_multi = score_place(multi)
    # Both are >= 0.5 weight, multi has 2 matching tags → bonus
    assert score_single == 0.75  # thai=0.75
    assert score_multi > score_single  # bonus for multiple matches


def test_score_and_rank(sample_places):
    """Scored places should be sorted by score descending."""
    scored = score_and_rank_places(sample_places)
    assert len(scored) == len(sample_places)
    for i in range(len(scored) - 1):
        assert scored[i].total_score >= scored[i + 1].total_score


def test_secret_gem_bonus(sample_places):
    """Secret gems should get a bonus."""
    gem_place = Place(name="Gem", type="restaurant", cuisine_tags=["thai"], is_secret_gem=True)
    normal_place = Place(name="Normal", type="restaurant", cuisine_tags=["thai"], is_secret_gem=False)

    scored_gem = score_and_rank_places([gem_place, normal_place])
    # Gem should score higher due to bonus
    gem_scored = next(s for s in scored_gem if s.place.name == "Gem")
    assert gem_scored.bonus_gem > 0


def test_get_top_cuisines():
    """Top cuisines should be sorted by weight."""
    top = get_top_cuisines(5)
    assert len(top) == 5
    for i in range(len(top) - 1):
        assert top[i][1] >= top[i + 1][1]


def test_cuisine_weight_known():
    """Known cuisine should return proper weight."""
    weight = get_cuisine_weight("italian")
    assert weight == 1.0


def test_cuisine_weight_unknown():
    """Unknown cuisine should return default."""
    weight = get_cuisine_weight("nonexistent")
    assert weight == 0.2


def test_cuisine_weight_case_insensitive():
    """Weight lookup should be case-insensitive."""
    assert get_cuisine_weight("ITALIAN") == get_cuisine_weight("italian")

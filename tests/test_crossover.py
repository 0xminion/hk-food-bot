"""Tests for crossover recommendation engine."""

from engine.crossover import (
    get_similar_cuisines,
    get_crossover_cuisine,
    get_serendipitous_cuisine,
)


def test_thai_to_vietnamese():
    """Thai fans should get Vietnamese as crossover."""
    similar = get_similar_cuisines("thai")
    cuisines = [c for c, _ in similar]
    assert "vietnamese" in cuisines


def test_italian_to_spanish():
    """Italian fans should get Spanish as crossover."""
    similar = get_similar_cuisines("italian")
    cuisines = [c for c, _ in similar]
    assert "spanish" in cuisines


def test_cocktail_to_speakeasy():
    """Cocktail bar fans should get speakeasy as crossover."""
    similar = get_similar_cuisines("cocktail-bar")
    cuisines = [c for c, _ in similar]
    assert "speakeasy" in cuisines


def test_unknown_cuisine_returns_empty():
    """Unknown cuisine should return empty list."""
    similar = get_similar_cuisines("obscure-cuisine")
    assert similar == []


def test_crossover_skips_tried():
    """Crossover should suggest untried cuisines."""
    preferred = ["thai"]
    tried = {"vietnamese", "malay", "lao"}
    result = get_crossover_cuisine(preferred, tried)
    if result:
        assert result not in tried


def test_crossover_returns_none_when_exhausted():
    """If all similar cuisines are tried, returns None."""
    preferred = ["thai"]
    tried = {"vietnamese", "malay", "lao", "indonesian"}
    result = get_crossover_cuisine(preferred, tried)
    assert result is None


def test_serendipitous_picks_untried():
    """Serendipitous pick should be from untried cuisines."""
    preferred = ["italian", "thai"]
    available = ["italian", "thai", "french", "korean", "vietnamese", "mexican"]
    result = get_serendipitous_cuisine(preferred, available)
    assert result not in preferred


def test_serendipitous_returns_none_with_empty_available():
    """Returns None if no available cuisines."""
    result = get_serendipitous_cuisine(["italian"], [])
    assert result is None

"""Tests for secret gem detection."""

from engine.secret_gem import apply_secret_gem_rules, is_mall_location
from data.loader import Place


def test_rule_a_high_rating_low_reviews():
    """Rule A: rating ≥4.3 AND reviews <200."""
    place = Place(
        name="Hidden Gem",
        type="restaurant",
        cuisine_tags=["thai"],
        address="123 Back Alley, Wan Chai",
        google_rating=4.5,
        review_count=80,
    )
    assert apply_secret_gem_rules(place) is True


def test_rule_a_too_many_reviews():
    """Rule A fails with too many reviews."""
    place = Place(
        name="Popular Place",
        type="restaurant",
        cuisine_tags=["thai"],
        google_rating=4.5,
        review_count=300,
    )
    assert apply_secret_gem_rules(place) is False


def test_rule_c_hidden_alley():
    """Rule C: rating ≥4.0, <100 reviews, hidden-alley style."""
    place = Place(
        name="Alley Spot",
        type="restaurant",
        cuisine_tags=["chinese"],
        style_tags=["hidden-alley"],
        google_rating=4.1,
        review_count=50,
    )
    assert apply_secret_gem_rules(place) is True


def test_rule_e_few_reviews_high_rating():
    """Rule E: few reviews + high rating."""
    place = Place(
        name="New Gem",
        type="restaurant",
        cuisine_tags=["italian"],
        google_rating=4.3,
        review_count=30,
    )
    assert apply_secret_gem_rules(place) is True


def test_negative_mall_location():
    """Places in major malls should not be gems."""
    place = Place(
        name="Mall Restaurant",
        type="restaurant",
        cuisine_tags=["italian"],
        address="Shop 123, IFC Mall, Central",
        google_rating=4.5,
        review_count=50,
    )
    assert apply_secret_gem_rules(place) is False


def test_negative_mainstream():
    """Places with >1000 reviews should not be gems."""
    place = Place(
        name="Famous Place",
        type="restaurant",
        cuisine_tags=["chinese"],
        address="123 Normal St",
        google_rating=4.5,
        review_count=2000,
    )
    assert apply_secret_gem_rules(place) is False


def test_is_mall_location():
    """Mall detection from address."""
    assert is_mall_location("Shop 1, IFC, Central") is True
    assert is_mall_location("Harbour City, TST") is True
    assert is_mall_location("123 Back Alley, Wan Chai") is False
    assert is_mall_location("") is False

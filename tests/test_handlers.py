"""Integration tests for bot handlers.

These tests validate the handler logic without actually connecting to Telegram.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from handlers.common import (
    HK_AREAS,
    build_area_keyboard,
    build_cuisine_keyboard,
    format_recommendation,
    format_recommendations_message,
)
from data.loader import Place


def test_hk_areas_count():
    """Should have 10 HK areas."""
    assert len(HK_AREAS) == 10


def test_build_area_keyboard():
    """Area keyboard should have buttons for all areas."""
    kb = build_area_keyboard()
    assert kb is not None
    # Count buttons across all rows
    total_buttons = sum(len(row) for row in kb.inline_keyboard)
    assert total_buttons == 10


def test_build_cuisine_keyboard():
    """Cuisine keyboard should include surprise me button."""
    kb = build_cuisine_keyboard(["thai", "italian", "japanese"])
    total_buttons = sum(len(row) for row in kb.inline_keyboard)
    assert total_buttons == 4  # 3 cuisines + surprise


def test_format_recommendation(sample_places):
    """Formatting should produce a non-empty string."""
    text = format_recommendation(sample_places[0], 1)
    assert "Thai Basil" in text
    assert "thai" in text.lower()
    assert "⭐" in text


def test_format_recommendation_with_booking():
    """Booking URL should appear in output."""
    place = Place(
        name="Test",
        type="restaurant",
        cuisine_tags=["italian"],
        booking_url="https://chope.com/test",
        google_rating=4.5,
        review_count=100,
    )
    text = format_recommendation(place, 1)
    assert "Book here" in text


def test_format_recommendation_no_booking():
    """No booking URL should show walk-in message."""
    place = Place(
        name="Test",
        type="restaurant",
        cuisine_tags=["italian"],
        booking_url="",
        google_rating=4.5,
        review_count=100,
    )
    text = format_recommendation(place, 1)
    assert "Walk-in" in text


def test_format_recommendations_message():
    """Full message should include header and body."""
    places = [
        Place(name="A", type="restaurant", cuisine_tags=["thai"], google_rating=4.5),
        Place(name="B", type="restaurant", cuisine_tags=["italian"], google_rating=4.3),
    ]
    msg = format_recommendations_message(places, "Central", "restaurant")
    assert "Central" in msg
    assert "A" in msg
    assert "B" in msg


def test_format_recommendations_with_crossover():
    """Crossover message should mention expanded search."""
    places = [Place(name="A", type="restaurant", cuisine_tags=["vietnamese"])]
    msg = format_recommendations_message(
        places, "Central", "restaurant", crossover="vietnamese", expanded=True
    )
    assert "Vietnamese" in msg


def test_format_recommendations_low_count():
    """Low match count should show warning."""
    places = [Place(name="A", type="restaurant", cuisine_tags=["thai"])]
    msg = format_recommendations_message(places, "Central", "restaurant")
    assert "Only" in msg or "1 matches" in msg

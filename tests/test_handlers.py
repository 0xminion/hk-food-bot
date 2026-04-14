"""Integration tests for bot handlers.

These tests validate the handler logic without actually connecting to Telegram.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from handlers.common import (
    HK_AREAS,
    build_area_keyboard,
    build_cuisine_keyboard,
    build_google_maps_url,
    build_more_button_keyboard,
    format_recommendation,
    format_recommendations_message,
)
from bot import handle_more_recommendations
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


def test_build_cuisine_keyboard(monkeypatch):
    """Cuisine keyboard should include 10 choices plus surprise and others, in shuffled order."""
    def reverse_shuffle(items):
        items.reverse()
    monkeypatch.setattr("handlers.common.random.shuffle", reverse_shuffle)
    kb = build_cuisine_keyboard(["thai", "italian", "japanese", "spanish", "french", "korean", "indian", "bakery", "dessert", "ramen"])
    total_buttons = sum(len(row) for row in kb.inline_keyboard)
    assert total_buttons == 12  # 10 cuisines + surprise + others
    assert kb.inline_keyboard[0][0].text == "Ramen"  # reversed order proves shuffle was used


def test_build_more_button_keyboard():
    kb = build_more_button_keyboard("eat")
    assert kb.inline_keyboard[0][0].text == "➕ More"
    assert kb.inline_keyboard[0][0].callback_data == "more:eat"
def test_build_google_maps_url_uses_place_query_not_coords():
    """Google Maps link should be a place search URL, not raw coordinates."""
    place = Place(
        name="Bar Leone",
        type="bar",
        cuisine_tags=["cocktail-bar"],
        address="11-15 Bridges St, Central, Hong Kong",
        lat=22.2835238,
        lng=114.1509492,
        source_url="https://maps.google.com/?q=22.2835238,114.1509492",
    )
    url = build_google_maps_url(place)
    assert "google.com/maps/search/?api=1&query=" in url
    assert "22.2835238" not in url
    assert "114.1509492" not in url


def test_format_recommendation(sample_places):
    """Formatting should produce a non-empty string."""
    text = format_recommendation(sample_places[0], 1)
    first_line = text.splitlines()[0]
    assert "Thai Basil" in text
    assert "thai" in text.lower()
    assert "⭐" in first_line
    assert first_line.startswith("<b>1. Thai Basil</b>")


def test_format_recommendation_compact_distance_line():
    place = Place(
        name="Test",
        type="restaurant",
        cuisine_tags=["italian"],
        google_rating=4.5,
        review_count=100,
        distance_walk_m=1200,
        distance_drive_m=2400,
    )
    text = format_recommendation(place, 1)
    dist_line = [line for line in text.splitlines() if "🚶" in line][0]
    assert "🚶" in dist_line and "🚗" in dist_line
    assert "\n" not in dist_line


def test_handle_more_recommendations_expands_search(monkeypatch):
    query = AsyncMock()
    query.data = "more:eat"
    query.edit_message_text = AsyncMock()
    query.answer = AsyncMock()
    update = MagicMock(callback_query=query)
    context = MagicMock()
    context.user_data = {
        "last_recommendation": {
            "flow": "eat",
            "place_type": "restaurant",
            "area_name": "Central",
            "lat": 22.2783,
            "lng": 114.1540,
            "cuisine": "thai",
        },
        "all_places": [],
        "exclude_place_names": [],
    }
    with patch("bot.recommend") as mock_recommend:
        mock_recommend.return_value = MagicMock(
            places=[], crossover_suggestion="", expanded_search=True
        )
        asyncio.run(handle_more_recommendations(update, context))
    mock_recommend.assert_called_once()
    kwargs = mock_recommend.call_args.kwargs
    assert kwargs["allow_expansion"] is True
    query.edit_message_text.assert_awaited()


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

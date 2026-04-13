"""Shared formatting and keyboard utilities for bot handlers."""

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from data.loader import Place
from engine.time_aware import get_open_status_label

logger = logging.getLogger(__name__)

# HK area definitions (keyed by short label, value = (lat, lng))
HK_AREAS = {
    "Central":      (22.2783, 114.1540),
    "Wan Chai":     (22.2790, 114.1750),
    "Causeway Bay": (22.2800, 114.1850),
    "TST":          (22.2970, 114.1700),
    "Mong Kok":     (22.3190, 114.1690),
    "Sai Ying Pun": (22.2860, 114.1420),
    "Sheung Wan":   (22.2860, 114.1500),
    "Admiralty":    (22.2780, 114.1650),
    "Tin Hau":      (22.2840, 114.1920),
    "Kennedy Town": (22.2810, 114.1300),
}


def build_area_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard with HK area buttons."""
    buttons = [
        InlineKeyboardButton(name, callback_data=f"loc:{name}")
        for name in HK_AREAS
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def build_cuisine_keyboard(cuisines: list[str]) -> InlineKeyboardMarkup:
    """Build inline keyboard with cuisine options plus surprise me button."""
    buttons = [
        InlineKeyboardButton(c.title(), callback_data=f"cuisine:{c}")
        for c in cuisines
    ]
    buttons.append(InlineKeyboardButton("🎲 Surprise me!", callback_data="cuisine:surprise"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def format_recommendation(place: Place, idx: int) -> str:
    """Format a single place recommendation block for Telegram."""
    lines = [f"<b>{idx}. {place.name}</b>"]

    # Google Maps link
    if place.lat and place.lng:
        maps_url = f"https://www.google.com/maps/search/?api=1&query={place.lat},{place.lng}"
        lines.append(f'   📍 <a href="{maps_url}">Open in Google Maps</a>')

    # Secret gem badge
    if place.is_secret_gem:
        lines.append("   💎 Secret gem!")

    # Cuisine tags
    if place.cuisine_tags:
        lines.append(f"   🍜 Cuisine: {', '.join(place.cuisine_tags)}")

    # Style tags
    if place.style_tags:
        lines.append(f"   🏷 Style: {', '.join(place.style_tags)}")

    # Rating
    if place.google_rating > 0:
        review_text = f"({place.review_count} reviews)" if place.review_count else ""
        lines.append(f"   ⭐ {place.google_rating} {review_text}")

    # Opening hours + status
    if place.opening_hours:
        status = get_open_status_label(place.opening_hours)
        lines.append(f"   🕐 {place.opening_hours} | {status}")

    # Distance
    if place.distance_walk_m:
        walk_min = max(1, int(place.distance_walk_m / 1000 * 12))
        lines.append(f"   🚶 ~{walk_min} min walk ({place.distance_walk_m}m)")
    if place.distance_drive_m:
        drive_min = max(1, int(place.distance_drive_m / 1000 * 2.4))
        lines.append(f"   🚗 ~{drive_min} min drive ({place.distance_drive_m}m)")

    # Address
    if place.address:
        lines.append(f"   📫 {place.address}")

    # Booking
    if place.booking_url:
        lines.append(f'   🎟 <a href="{place.booking_url}">Book here</a>')
    else:
        lines.append("   🎟 Walk-in, no booking needed")

    return "\n".join(lines)


def format_recommendations_message(
    places: list[Place],
    area_name: str,
    place_type: str,
    crossover: str = "",
    expanded: bool = False,
) -> str:
    """Format the full recommendations message."""
    type_label = "🍽 Restaurants" if place_type == "restaurant" else "🍸 Bars"
    header = f"{type_label} in <b>{area_name}</b>:\n\n"

    body = "\n\n".join(format_recommendation(p, i + 1) for i, p in enumerate(places))

    footer_parts = []
    if expanded and crossover:
        footer_parts.append(f"🔄 Expanded search with {crossover.title()} options")
    if len(places) < 5:
        footer_parts.append(f"⚠️ Only {len(places)} matches found — try another area or cuisine")

    footer = "\n\n" + "\n".join(footer_parts) if footer_parts else ""
    return header + body + footer

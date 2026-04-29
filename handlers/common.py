"""Shared formatting and keyboard utilities for bot handlers."""

import logging
from urllib.parse import quote_plus

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from data.loader import Place
from engine.time_aware import get_open_status_label

logger = logging.getLogger(__name__)

# Conversation states shared across handlers and bot.py
LOCATION, PRICE, CUISINE, OTHER_INPUT, SURPRISE_LOCATION = range(5)

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


# Price range labels and matching logic
PRICE_OPTIONS = [
    ("any", "Any budget"),
    ("$", "💰 Cheap eats"),
    ("$$", "💰💰 Mid-range"),
    ("$$$", "💰💰💰 Upscale"),
    ("$$$$", "💰💰💰💰 Fine dining"),
]


def build_price_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard with budget filter options."""
    buttons = [
        InlineKeyboardButton(label, callback_data=f"price:{code}")
        for code, label in PRICE_OPTIONS
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def _parse_price_tier(price_range: str) -> int:
    """Map OpenRice numeric price range to tier 0-$4."""
    if not price_range:
        return 0
    pr = price_range.strip()
    # Match numeric patterns like $50以下, $51-100, $101-200, $201-400, $401-800, $801以上
    if pr.startswith("$50") or "50以下" in pr:
        return 1
    if "51-100" in pr or "101-200" in pr:
        return 1
    if "201-400" in pr:
        return 2
    if "401-800" in pr:
        return 3
    if "801" in pr:
        return 4
    # Fallback to dollar-sign count
    return pr.count("$")


def price_matches(price_range: str, selected: str) -> bool:
    """Check if a place's price_range matches the selected budget filter."""
    if selected == "any" or not price_range:
        return True
    selected_tier = _parse_price_tier(selected)
    range_tier = _parse_price_tier(price_range)
    if range_tier == 0:
        return True  # Unknown price — include it
    return range_tier == selected_tier


def build_cuisine_keyboard(cuisines: list[str]) -> InlineKeyboardMarkup:
    """Build inline keyboard with cuisine options, surprise me, and others.

    Cuisines are sorted by taste profile weight (highest first) so the user's
    favorites appear first. Top 10 are shown.
    """
    from engine.taste import get_cuisine_weight

    # Deduplicate preserving order, then sort by taste weight descending
    unique = list(dict.fromkeys(cuisines))
    unique.sort(key=lambda c: get_cuisine_weight(c), reverse=True)
    choices = unique[:10]

    buttons = [
        InlineKeyboardButton(c.title(), callback_data=f"cuisine:{c}")
        for c in choices
    ]
    buttons.append(InlineKeyboardButton("🎲 Surprise me!", callback_data="cuisine:surprise"))
    buttons.append(InlineKeyboardButton("✍️ Others", callback_data="cuisine:other"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def build_location_request_keyboard() -> ReplyKeyboardMarkup:
    """Ask the user to share their rough/live location."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Share my location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_more_button_keyboard(flow: str) -> InlineKeyboardMarkup:
    """Build a compact 'more' action for expanding the current search."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("➕ More", callback_data=f"more:{flow}")]])


def build_google_maps_url(place: Place) -> str:
    """Build a Google Maps link for a place, preferring actual place URLs if present."""
    source_url = (place.source_url or "").strip()
    if source_url.startswith("https://maps.app.goo.gl/"):
        return source_url
    if "google.com/maps" in source_url and "q=" not in source_url and "@" not in source_url:
        return source_url
    query = f"{place.name} {place.address}".strip()
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def format_recommendation(place: Place, idx: int) -> str:
    """Format a single place recommendation block for Telegram."""
    name_line = f"<b>{idx}. {place.name}</b>"

    ratings = []
    if place.google_rating > 0:
        review_text = f" ({place.review_count} reviews)" if place.review_count else ""
        ratings.append(f"⭐ {place.google_rating}{review_text}")
    if place.or_rating > 0:
        ratings.append(f"⭐ {round(place.or_rating, 2)} (OR)")
    if ratings:
        name_line += " " + " · ".join(ratings)

    lines = [name_line]

    # Google Maps link
    maps_url = build_google_maps_url(place)
    if maps_url:
        lines.append(f'   📍 <a href="{maps_url}">Open in Google Maps</a>')

    # Secret gem badge
    if place.is_secret_gem:
        lines.append("   💎 Secret gem!")

    # Award badges
    try:
        from engine.awards import get_award_boost
        from pathlib import Path
        data_dir = Path(__file__).parent.parent / "data"
        _, badges = get_award_boost(place.name, data_dir)
        if badges:
            lines.append("   " + " ".join(badges))
    except Exception:
        pass

    # Cuisine tags
    if place.cuisine_tags:
        lines.append(f"   🍜 Cuisine: {', '.join(place.cuisine_tags)}")

    # Style tags
    if place.style_tags:
        lines.append(f"   🏷 Style: {', '.join(place.style_tags)}")

    # Hours
    if place.opening_hours:
        status = get_open_status_label(place.opening_hours)
        lines.append(f"   🕐 {place.opening_hours} | {status}")

    # Distance
    dist_bits = []
    if place.distance_walk_m:
        walk_min = max(1, int(place.distance_walk_m / 1000 * 12))
        dist_bits.append(f"🚶 ~{walk_min} min walk ({place.distance_walk_m}m)")
    if place.distance_drive_m:
        drive_min = max(1, int(place.distance_drive_m / 1000 * 2.4))
        dist_bits.append(f"🚗 ~{drive_min} min drive ({place.distance_drive_m}m)")
    if dist_bits:
        lines.append("   " + " · ".join(dist_bits))

    # Address
    if place.address:
        lines.append(f"   📫 {place.address}")

    # Booking
    if place.booking_url:
        lines.append(f'   🎟 <a href="{place.booking_url}">Book here</a>')
    else:
        lines.append("   🎟 Walk-in, no booking needed")

    # Rationale (from conversational mode)
    if getattr(place, "rationale", None):
        lines.append(f"   💬 <i>{place.rationale}</i>")

    return "\n".join(lines)


def format_night_out_message(itineraries: list, area_name: str, budget: str | None = None) -> str:
    """Format night-out itineraries for Telegram."""
    header = f"🌃 <b>Night out in {area_name}</b>"
    if budget:
        header += f" · {budget}"
    header += "\n\n"

    if not itineraries:
        return header + "😅 No matching dinner + bar combos found. Try a different area or budget."

    blocks = []
    for idx, it in enumerate(itineraries, 1):
        d, b = it.dinner, it.bar
        block = f"<b>Option {idx}</b>\n"
        # Dinner
        block += f"🍽 <b>{d.name}</b>"
        if d.google_rating > 0:
            block += f"  ⭐ {d.google_rating}"
        if d.or_rating > 0:
            block += f"  ⭐ {round(d.or_rating, 2)} (OR)"
        block += f"\n   📍 <a href=\"{build_google_maps_url(d)}\">Google Maps</a>\n"
        if d.cuisine_tags:
            block += f"   🍜 {', '.join(d.cuisine_tags)}\n"
        if getattr(d, "is_secret_gem", False):
            block += "   💎 Secret gem\n"

        # Arrow
        walk_min = max(1, it.walk_m // 80)
        block += f"   ↓ 🚶 {walk_min} min walk ({it.walk_m}m)\n"

        # Bar
        block += f"🍸 <b>{b.name}</b>"
        if b.google_rating > 0:
            block += f"  ⭐ {b.google_rating}"
        if b.or_rating > 0:
            block += f"  ⭐ {round(b.or_rating, 2)} (OR)"
        block += f"\n   📍 <a href=\"{build_google_maps_url(b)}\">Google Maps</a>\n"
        if b.style_tags:
            block += f"   🏷 {', '.join(b.style_tags)}\n"
        if getattr(b, "is_secret_gem", False):
            block += "   💎 Secret gem\n"

        block += f"\n   <i>{it.rationale}</i>"
        blocks.append(block)

    return header + "\n\n".join(blocks)


def format_recommendations_message(
    places: list[Place],
    area_name: str,
    place_type: str,
    crossover: str = "",
    expanded: bool = False,
    start_idx: int = 1,
) -> str:
    """Format the full recommendations message."""
    type_label = "🍽 Restaurants" if place_type == "restaurant" else "🍸 Bars"
    header = f"{type_label} in <b>{area_name}</b>:\n\n"

    body = "\n\n".join(format_recommendation(p, start_idx + i) for i, p in enumerate(places))

    footer_parts = []
    if expanded and crossover:
        footer_parts.append(f"🔄 Expanded search with {crossover.title()} options")
    if len(places) < 5:
        footer_parts.append(f"⚠️ Only {len(places)} matches found — try another area or cuisine")

    footer = "\n\n" + "\n".join(footer_parts) if footer_parts else ""
    return header + body + footer

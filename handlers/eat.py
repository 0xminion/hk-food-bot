"""
/eat? command handler.

Flow: /eat? → area picker → cuisine picker → 5 restaurant recommendations
"""

import logging
import random
import re
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters

from data.loader import get_all_places
from data.loader import filter_by_type
from engine.recommender import recommend, get_available_cuisines
from handlers.common import (
    CUISINE,
    LOCATION,
    OTHER_INPUT,
    SURPRISE_LOCATION,
    HK_AREAS,
    build_area_keyboard,
    build_cuisine_keyboard,
    build_location_request_keyboard,
    build_more_button_keyboard,
    format_recommendations_message,
)

logger = logging.getLogger(__name__)

def _get_places_from_cache(context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data.get("config", {})
    csv_path = Path(context.bot_data.get("bot_dir", ".")) / config.get("data", {}).get("places_csv", "data/merged_places.csv")
    all_places = context.bot_data.get("_cached_places")
    if all_places is None:
        all_places = get_all_places(csv_path)
        context.bot_data["_cached_places"] = all_places
    context.user_data["all_places"] = all_places
    return all_places


def _build_cuisine_suggestions(all_places, area_name, lat, lng):
    cuisines = get_available_cuisines(all_places, "restaurant", lat, lng, area_name=area_name)
    if not cuisines:
        return []
    choices = list(dict.fromkeys(cuisines[:10]))
    random.shuffle(choices)
    return choices


async def eat_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /eat? — ask for location."""
    context.user_data["place_type"] = "restaurant"
    await update.message.reply_text(
        "🍽 Looking for a restaurant!\n\n📍 Which area are you in or near?",
        reply_markup=build_area_keyboard(),
    )
    return LOCATION


async def eat_location_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle area selection — show cuisine options."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)

    area_name = query.data.replace("loc:", "")
    if area_name not in HK_AREAS:
        logger.warning(f"Unknown area in callback data: {area_name!r}")
        try:
            await query.edit_message_text("Invalid area. Please try again.")
        except Exception:
            pass
        return ConversationHandler.END

    lat, lng = HK_AREAS[area_name]
    context.user_data["location"] = (area_name, lat, lng)

    all_places = _get_places_from_cache(context)
    suggestions = _build_cuisine_suggestions(all_places, area_name, lat, lng)

    if not suggestions:
        try:
            await query.edit_message_text(
                f"😅 No restaurants found in {area_name}. Try another area!",
                reply_markup=build_area_keyboard(),
            )
        except Exception:
            logger.error("Failed to edit message for no cuisines", exc_info=True)
        return LOCATION

    try:
        await query.edit_message_text(
            f"📍 <b>{area_name}</b> selected.\n\n🍽 What cuisine are you feeling?",
            parse_mode="HTML",
            reply_markup=build_cuisine_keyboard(suggestions),
        )
    except Exception:
        logger.error("Failed to edit message for cuisine selection", exc_info=True)
        return ConversationHandler.END
    return CUISINE


async def eat_cuisine_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cuisine selection — either recommend or ask for extra input/location."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)

    cuisine = query.data.replace("cuisine:", "")
    if cuisine == "surprise":
        await query.message.reply_text(
            "🎲 Surprise mode needs your rough location. Share it below and I’ll keep results within 2km.",
            reply_markup=build_location_request_keyboard(),
        )
        context.user_data["surprise_place_type"] = "restaurant"
        return SURPRISE_LOCATION

    if cuisine == "other":
        await query.message.reply_text(
            "✍️ Type the cuisine you want and I’ll search for it.",
        )
        context.user_data["awaiting_cuisine_text"] = True
        return OTHER_INPUT

    all_places = context.user_data.get("all_places", [])
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))
    result = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=lat,
        area_lng=lng,
        cuisine=cuisine,
        area_name=area_name,
        allow_expansion=False,
        exclude_place_names=set(context.user_data.get("exclude_place_names", [])),
    )

    shown_names = [p.name for p in result.places]
    exclude_names = set(context.user_data.get("exclude_place_names", []))
    exclude_names.update(shown_names)
    context.user_data["exclude_place_names"] = sorted(exclude_names)
    context.user_data["last_recommendation"] = {
        "flow": "eat",
        "place_type": "restaurant",
        "area_name": area_name,
        "lat": lat,
        "lng": lng,
        "cuisine": cuisine,
        "shown_place_names": shown_names,
    }

    message = format_recommendations_message(
        places=result.places,
        area_name=area_name,
        place_type="restaurant",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )
    markup = None if result.expanded_search else build_more_button_keyboard("eat")

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=markup,
        )
    except Exception:
        logger.error("Failed to edit message with recommendations", exc_info=True)
    return ConversationHandler.END


async def eat_other_cuisine_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle typed-in cuisine and return recommendations. Supports fuzzy regional matching."""
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Type a cuisine name, e.g. Thai, Lebanese, French, SEA, EU.")
        return OTHER_INPUT

    from engine.cuisine_groups import resolve_cuisine_input
    cuisine_tags = resolve_cuisine_input(text)

    all_places = context.user_data.get("all_places", [])
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))

    if len(cuisine_tags) == 1:
        # Single cuisine — use normal flow
        cuisine = cuisine_tags[0]
        result = recommend(
            all_places=all_places,
            place_type="restaurant",
            area_lat=lat,
            area_lng=lng,
            cuisine=cuisine,
            area_name=area_name,
        )
    else:
        # Regional group — search for all matching cuisines
        from data.loader import filter_by_cuisine
        scope_radius = 2000 if area_name else 25000
        from engine.recommender import _filter_nearby_places
        nearby = _filter_nearby_places(
            filter_by_type(all_places, "restaurant"),
            area_name, lat, lng, scope_radius
        )
        matched = filter_by_cuisine(nearby, cuisine_tags)
        from engine.recommender import RecommendationResult
        result = RecommendationResult(places=matched[:5])
        result.crossover_suggestion = text
        result.expanded_search = True

    shown_names = [p.name for p in result.places]
    exclude_names = set(context.user_data.get("exclude_place_names", []))
    exclude_names.update(shown_names)
    context.user_data["exclude_place_names"] = sorted(exclude_names)
    message = format_recommendations_message(
        places=result.places,
        area_name=area_name,
        place_type="restaurant",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )
    context.user_data["last_recommendation"] = {
        "flow": "eat",
        "place_type": "restaurant",
        "area_name": area_name,
        "lat": lat,
        "lng": lng,
        "cuisine": cuisine,
        "shown_place_names": shown_names,
    }
    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=None if result.expanded_search else build_more_button_keyboard("eat"),
    )
    return ConversationHandler.END


async def eat_surprise_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle shared location for surprise mode."""
    location = update.message.location
    if not location:
        await update.message.reply_text("Please tap the location button so I can find nearby places.")
        return SURPRISE_LOCATION

    all_places = context.user_data.get("all_places", [])
    lat, lng = location.latitude, location.longitude
    result = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=lat,
        area_lng=lng,
        cuisine="surprise",
        max_distance_m=2000,
        area_name=None,
    )
    shown_names = [p.name for p in result.places]
    exclude_names = set(context.user_data.get("exclude_place_names", []))
    exclude_names.update(shown_names)
    context.user_data["exclude_place_names"] = sorted(exclude_names)
    message = format_recommendations_message(
        places=result.places,
        area_name="Near you",
        place_type="restaurant",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )
    context.user_data["last_recommendation"] = {
        "flow": "eat",
        "place_type": "restaurant",
        "area_name": "Near you",
        "lat": lat,
        "lng": lng,
        "cuisine": "surprise",
        "shown_place_names": shown_names,
    }
    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=None if result.expanded_search else build_more_button_keyboard("eat"),
    )
    return ConversationHandler.END

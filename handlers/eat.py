"""
/eat? command handler.

Flow: /eat? → area picker → cuisine picker → 5 restaurant recommendations
"""

import logging
import random
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from data.loader import get_all_places
from engine.recommender import recommend, get_available_cuisines
from engine.taste import get_cuisine_weight
from handlers.common import (
    HK_AREAS,
    build_area_keyboard,
    build_cuisine_keyboard,
    format_recommendations_message,
)

logger = logging.getLogger(__name__)

LOCATION, CUISINE = range(2)


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

    # Load data (cached in bot_data to avoid re-reading CSV on every request)
    config = context.bot_data.get("config", {})
    csv_path = Path(context.bot_data.get("bot_dir", ".")) / config.get("data", {}).get("places_csv", "data/merged_places.csv")
    all_places = context.bot_data.get("_cached_places")
    if all_places is None:
        all_places = get_all_places(csv_path)
        context.bot_data["_cached_places"] = all_places
    context.user_data["all_places"] = all_places

    # Get available cuisines for this area
    cuisines = get_available_cuisines(all_places, "restaurant", lat, lng)

    if not cuisines:
        try:
            await query.edit_message_text(
                f"😅 No restaurants found in {area_name}. Try another area!",
                reply_markup=build_area_keyboard(),
            )
        except Exception:
            logger.error("Failed to edit message for no cuisines", exc_info=True)
        return LOCATION

    # Weight toward user preferences
    weighted = [(c, get_cuisine_weight(c)) for c in cuisines]
    weighted.sort(key=lambda x: x[1], reverse=True)

    top_pool = [c for c, _ in weighted[:8]]
    suggestions = random.sample(top_pool, min(5, len(top_pool)))

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
    """Handle cuisine selection — deliver 5 recommendations."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)

    cuisine = query.data.replace("cuisine:", "")
    all_places = context.user_data.get("all_places", [])
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))

    result = recommend(
        all_places=all_places,
        place_type="restaurant",
        area_lat=lat,
        area_lng=lng,
        cuisine=cuisine if cuisine != "surprise" else "surprise",
    )

    message = format_recommendations_message(
        places=result.places,
        area_name=area_name,
        place_type="restaurant",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.error("Failed to edit message with recommendations", exc_info=True)
    return ConversationHandler.END

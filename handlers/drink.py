"""
/drink? command handler.

Flow: /drink? → area picker → cuisine picker → 5 bar recommendations
"""

import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters

from data.loader import get_all_places
from engine.recommender import recommend, get_available_spot_types
from handlers.common import (
    CUISINE,
    LOCATION,
    PRICE,
    OTHER_INPUT,
    SURPRISE_LOCATION,
    HK_AREAS,
    build_area_keyboard,
    build_cuisine_keyboard,
    build_price_keyboard,
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
    cuisines = get_available_spot_types(all_places, lat, lng, area_name=area_name)
    if not cuisines:
        return []
    # Deduplicate preserving order — sorting happens in build_cuisine_keyboard
    choices = list(dict.fromkeys(cuisines))
    return choices


async def drink_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /drink? — ask for location."""
    context.user_data["place_type"] = "bar"
    await update.message.reply_text(
        "🍸 Looking for a bar!\n\n📍 Which area are you in or near?",
        reply_markup=build_area_keyboard(),
    )
    return LOCATION


async def drink_location_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle area selection — show price filter options."""
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

    try:
        await query.edit_message_text(
            f"📍 <b>{area_name}</b> selected.\n\n💰 Any budget preference?",
            parse_mode="HTML",
            reply_markup=build_price_keyboard(),
        )
    except Exception:
        logger.error("Failed to edit message for price selection", exc_info=True)
        return ConversationHandler.END
    return PRICE


async def drink_price_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle price selection — show drink type options."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)

    price = query.data.replace("price:", "")
    context.user_data["price_filter"] = price

    all_places = _get_places_from_cache(context)
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))
    suggestions = _build_cuisine_suggestions(all_places, area_name, lat, lng)

    if not suggestions:
        try:
            await query.edit_message_text(
                f"😅 No bars found in {area_name}. Try another area!",
                reply_markup=build_area_keyboard(),
            )
        except Exception:
            logger.error("Failed to edit message for no bar types", exc_info=True)
        return LOCATION

    try:
        await query.edit_message_text(
            f"📍 <b>{area_name}</b> selected.\n\n🍸 What kind of drinks spot?",
            parse_mode="HTML",
            reply_markup=build_cuisine_keyboard(suggestions),
        )
    except Exception:
        logger.error("Failed to edit message for drink type selection", exc_info=True)
        return ConversationHandler.END
    return CUISINE


async def drink_cuisine_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle drink type selection — either recommend or ask for extra input/location."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer callback query", exc_info=True)

    drink_type = query.data.replace("cuisine:", "")
    if drink_type == "surprise":
        await query.message.reply_text(
            "🎲 Surprise mode needs your rough location. Share it below and I’ll keep results within 2km.",
            reply_markup=build_location_request_keyboard(),
        )
        context.user_data["surprise_place_type"] = "bar"
        return SURPRISE_LOCATION

    if drink_type == "other":
        await query.message.reply_text(
            "✍️ Type the drink style you want and I’ll search for it.",
        )
        context.user_data["awaiting_cuisine_text"] = True
        return OTHER_INPUT

    all_places = context.user_data.get("all_places", [])
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))

    result = recommend(
        all_places=all_places,
        place_type="bar",
        area_lat=lat,
        area_lng=lng,
        cuisine=drink_type,
        area_name=area_name,
        price_filter=context.user_data.get("price_filter"),
    )

    shown_names = [p.name for p in result.places]
    exclude_names = set(context.user_data.get("exclude_place_names", []))
    exclude_names.update(shown_names)
    context.user_data["exclude_place_names"] = sorted(exclude_names)

    message = format_recommendations_message(
        places=result.places,
        area_name=area_name,
        place_type="bar",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )

    context.user_data["last_recommendation"] = {
        "flow": "drink",
        "place_type": "bar",
        "area_name": area_name,
        "lat": lat,
        "lng": lng,
        "cuisine": drink_type,
        "shown_place_names": shown_names,
    }

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=None if result.expanded_search else build_more_button_keyboard("drink"),
        )
    except Exception:
        logger.error("Failed to edit message with recommendations", exc_info=True)
    return ConversationHandler.END


async def drink_other_cuisine_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle typed drink style and return recommendations. Supports fuzzy regional matching."""
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Type a style name, e.g. cocktail bar, speakeasy, wine bar, cocktail.")
        return OTHER_INPUT

    from engine.cuisine_groups import resolve_cuisine_input
    cuisine_tags = resolve_cuisine_input(text)

    all_places = context.user_data.get("all_places", [])
    area_name, lat, lng = context.user_data.get("location", ("Unknown", 22.2783, 114.1747))

    if len(cuisine_tags) == 1:
        drink_type = cuisine_tags[0]
        result = recommend(
            all_places=all_places,
            place_type="bar",
            area_lat=lat,
            area_lng=lng,
            cuisine=drink_type,
            area_name=area_name,
            price_filter=context.user_data.get("price_filter"),
        )
    else:
        from data.loader import filter_by_any_tag, filter_by_type
        scope_radius = 1500 if area_name else 25000
        from engine.recommender import _filter_nearby_places
        nearby = _filter_nearby_places(
            filter_by_type(all_places, "bar"),
            area_name, lat, lng, scope_radius
        )
        matched = filter_by_any_tag(nearby, cuisine_tags)
        # Apply price filter
        price_filter = context.user_data.get("price_filter")
        if price_filter and price_filter != "any":
            from handlers.common import price_matches
            matched = [p for p in matched if price_matches(p.price_range, price_filter)]
        from engine.recommender import RecommendationResult
        result = RecommendationResult(places=matched[:5])
        result.crossover_suggestion = text
        result.expanded_search = True
        drink_type = text

    shown_names = [p.name for p in result.places]
    message = format_recommendations_message(
        places=result.places,
        area_name=area_name,
        place_type="bar",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )
    context.user_data["last_recommendation"] = {
        "flow": "drink",
        "place_type": "bar",
        "area_name": area_name,
        "lat": lat,
        "lng": lng,
        "cuisine": drink_type,
        "shown_place_names": shown_names,
    }
    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=None if result.expanded_search else build_more_button_keyboard("drink"),
    )
    return ConversationHandler.END


async def drink_surprise_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle shared location for surprise mode."""
    location = update.message.location
    if not location:
        await update.message.reply_text("Please tap the location button so I can find nearby bars.")
        return SURPRISE_LOCATION

    all_places = context.user_data.get("all_places", [])
    lat, lng = location.latitude, location.longitude
    result = recommend(
        all_places=all_places,
        place_type="bar",
        area_lat=lat,
        area_lng=lng,
        cuisine="surprise",
        max_distance_m=1500,
        area_name=None,
    )
    shown_names = [p.name for p in result.places]
    exclude_names = set(context.user_data.get("exclude_place_names", []))
    exclude_names.update(shown_names)
    context.user_data["exclude_place_names"] = sorted(exclude_names)
    message = format_recommendations_message(
        places=result.places,
        area_name="Near you",
        place_type="bar",
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
    )
    context.user_data["last_recommendation"] = {
        "flow": "drink",
        "place_type": "bar",
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
        reply_markup=None if result.expanded_search else build_more_button_keyboard("drink"),
    )
    return ConversationHandler.END

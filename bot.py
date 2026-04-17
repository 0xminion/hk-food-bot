"""
HK Restaurant & Bar Recommendation Bot
Telegram bot for discovering restaurants and bars in Hong Kong.

Usage:
    python bot.py

Requires bot token in config.yaml.
"""

import logging
import os
from pathlib import Path

import yaml
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers.eat import (
    eat_entry,
    eat_location_chosen,
    eat_price_chosen,
    eat_cuisine_chosen,
    eat_other_cuisine_received,
    eat_surprise_location_received,
)
from handlers.drink import (
    drink_entry,
    drink_location_chosen,
    drink_price_chosen,
    drink_cuisine_chosen,
    drink_other_cuisine_received,
    drink_surprise_location_received,
)
from engine.recommender import recommend
from handlers.common import LOCATION, PRICE, CUISINE, OTHER_INPUT, SURPRISE_LOCATION, format_recommendations_message

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BOT_DIR = Path(__file__).parent
CONFIG_PATH = BOT_DIR / "config.yaml"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE .env file without an extra dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config() -> dict:
    load_env_file(BOT_DIR / ".env")
    if not CONFIG_PATH.exists():
        logger.warning(f"Config file not found: {CONFIG_PATH}, using defaults")
        return {"telegram": {"token": ""}, "data": {"places_csv": "data/merged_places.csv"}}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("telegram", {})
    cfg.setdefault("data", {})
    cfg["telegram"]["token"] = os.getenv("TELEGRAM_BOT_TOKEN", cfg["telegram"].get("token", ""))
    cfg["telegram"]["user_id"] = os.getenv("TELEGRAM_USER_ID", cfg["telegram"].get("user_id", ""))
    return cfg


config = load_config()

# ---------------------------------------------------------------------------
# Conversation states (shared)
# ---------------------------------------------------------------------------
# Imported from handlers.common

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def handle_more_recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Expand the current recommendation search when the user taps More."""
    from handlers.common import build_more_button_keyboard

    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        logger.warning("Failed to answer more callback query", exc_info=True)

    flow = (query.data or "").split(":", 1)[-1]
    state = context.user_data.get("last_recommendation") or {}
    if not state or state.get("flow") != flow:
        await query.edit_message_text("I lost the thread. Run /eat? or /drink? again.")
        return ConversationHandler.END

    current_excludes = set(context.user_data.get("exclude_place_names", []))
    current_excludes.update(state.get("shown_place_names", []))

    result = recommend(
        all_places=context.user_data.get("all_places", []),
        place_type=state.get("place_type", "restaurant"),
        area_lat=state.get("lat", 22.2783),
        area_lng=state.get("lng", 114.1747),
        cuisine=state.get("cuisine"),
        area_name=state.get("area_name"),
        allow_expansion=True,
        exclude_place_names=current_excludes,
        price_filter=context.user_data.get("price_filter"),
    )
    new_shown_names = [p.name for p in result.places]
    current_excludes.update(new_shown_names)
    context.user_data["exclude_place_names"] = sorted(current_excludes)

    # Cumulative count: all previously shown + current batch
    all_previously_shown = state.get("all_shown_place_names", state.get("shown_place_names", []))
    cumulative_shown = all_previously_shown + new_shown_names
    start_idx = len(all_previously_shown) + 1

    context.user_data["last_recommendation"] = {
        **state,
        "expanded": True,
        "shown_place_names": new_shown_names,
        "all_shown_place_names": cumulative_shown,
    }

    message = format_recommendations_message(
        places=result.places,
        area_name=state.get("area_name", "Unknown"),
        place_type=state.get("place_type", "restaurant"),
        crossover=result.crossover_suggestion,
        expanded=result.expanded_search,
        start_idx=start_idx,
    )
    message = f"─── More results ───\n\n{message}"

    # Keep "More" button unless search was fully expanded
    markup = None if result.expanded_search else build_more_button_keyboard(flow)

    try:
        await query.message.reply_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=markup,
        )
    except Exception:
        logger.error("Failed to expand recommendations", exc_info=True)
    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "🇭🇰 <b>HK Food & Drinks Bot</b>\n\n"
        "Looking for somewhere great to eat or drink?\n\n"
        "/eat?  — find a restaurant\n"
        "/drink? — find a bar\n"
        "/cancel — cancel current flow",
        parse_mode="HTML",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel."""
    await update.message.reply_text("No worries! Use /eat? or /drink? when you're ready.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Start the bot."""
    token = config["telegram"]["token"]
    if (
        not token
        or token == "YOUR_BOT_TOKEN_HERE"
        or len(token) < 10
        or ":" not in token
    ):
        print("ERROR: Set your bot token in config.yaml first!")
        print("Get one from @BotFather on Telegram.")
        return

    # Startup health check: validate data file exists and is loadable
    csv_path = BOT_DIR / config.get("data", {}).get("places_csv", "data/merged_places.csv")
    if not csv_path.exists():
        print(f"ERROR: Data file not found: {csv_path}")
        print("Run the data pipeline first: python scripts/merge_data.py")
        return
    from data.loader import load_places
    places = load_places(csv_path)
    if not places:
        print(f"ERROR: Data file exists but loaded 0 places from {csv_path}")
        print("Check that the CSV has valid data and correct column headers.")
        return
    logger.info(f"Health check passed: {len(places)} places loaded from {csv_path.name}")

    app = Application.builder().token(token).build()

    # Store config, bot dir, and pre-loaded places in bot_data for handlers
    app.bot_data["config"] = config
    app.bot_data["bot_dir"] = str(BOT_DIR)
    app.bot_data["_cached_places"] = places  # Pre-loaded at startup, not lazy

    # Conversation handler for /eat?
    eat_handler = ConversationHandler(
        entry_points=[CommandHandler("eat", eat_entry)],
        states={
            LOCATION: [
                CallbackQueryHandler(eat_location_chosen, pattern=r"^loc:"),
            ],
            PRICE: [
                CallbackQueryHandler(eat_price_chosen, pattern=r"^price:"),
            ],
            CUISINE: [
                CallbackQueryHandler(eat_cuisine_chosen, pattern=r"^cuisine:"),
            ],
            OTHER_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, eat_other_cuisine_received),
            ],
            SURPRISE_LOCATION: [
                MessageHandler(filters.LOCATION, eat_surprise_location_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, eat_surprise_location_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    # Conversation handler for /drink?
    drink_handler = ConversationHandler(
        entry_points=[CommandHandler("drink", drink_entry)],
        states={
            LOCATION: [
                CallbackQueryHandler(drink_location_chosen, pattern=r"^loc:"),
            ],
            PRICE: [
                CallbackQueryHandler(drink_price_chosen, pattern=r"^price:"),
            ],
            CUISINE: [
                CallbackQueryHandler(drink_cuisine_chosen, pattern=r"^cuisine:"),
            ],
            OTHER_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, drink_other_cuisine_received),
            ],
            SURPRISE_LOCATION: [
                MessageHandler(filters.LOCATION, drink_surprise_location_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, drink_surprise_location_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_more_recommendations, pattern=r"^more:"))
    app.add_handler(eat_handler)
    app.add_handler(drink_handler)

    logger.info("Starting HK Food Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

"""
HK Restaurant & Bar Recommendation Bot
Telegram bot for discovering restaurants and bars in Hong Kong.

Usage:
    python bot.py

Requires bot token in config.yaml.
"""

import logging
from pathlib import Path

import yaml
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from handlers.eat import eat_entry, eat_location_chosen, eat_cuisine_chosen
from handlers.drink import drink_entry, drink_location_chosen, drink_cuisine_chosen

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
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        logger.warning(f"Config file not found: {CONFIG_PATH}, using defaults")
        return {"telegram": {"token": ""}, "data": {"places_csv": "data/merged_places.csv"}}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

config = load_config()

# ---------------------------------------------------------------------------
# Conversation states (shared)
# ---------------------------------------------------------------------------
LOCATION, CUISINE = range(2)

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
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

    app = Application.builder().token(token).build()

    # Store config and bot dir in bot_data for handlers to access
    app.bot_data["config"] = config
    app.bot_data["bot_dir"] = str(BOT_DIR)

    # Conversation handler for /eat?
    eat_handler = ConversationHandler(
        entry_points=[CommandHandler("eat", eat_entry)],
        states={
            LOCATION: [
                CallbackQueryHandler(eat_location_chosen, pattern=r"^loc:"),
            ],
            CUISINE: [
                CallbackQueryHandler(eat_cuisine_chosen, pattern=r"^cuisine:"),
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
            CUISINE: [
                CallbackQueryHandler(drink_cuisine_chosen, pattern=r"^cuisine:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(eat_handler)
    app.add_handler(drink_handler)

    logger.info("Starting HK Food Bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

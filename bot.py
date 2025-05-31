# Main bot file for ChatGPTPlus2FABot

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage

# Import handlers
from handlers import commands, callback_query, admin # We will create admin and callback_query logic later
from utils import load_config, load_groups, load_users, logger # Use the logger from utils

# Load environment variables (especially the bot token)
load_dotenv()

async def main():
    """Initializes and starts the bot."""
    # Load initial data
    config_data = load_config()
    groups_data = load_groups()
    users_data = load_users()

    # It's good practice to load the token from environment variables
    # TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM" # Direct token as requested, but not recommended
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
    if not bot_token:
        logger.critical("Bot token not found. Please set TELEGRAM_BOT_TOKEN environment variable or add it directly to bot.py (not recommended).")
        return

    # Initialize bot and dispatcher
    # Using MemoryStorage for FSM, consider Redis or other persistent storage for production
    storage = MemoryStorage()
    bot = Bot(token=bot_token)
    dp = Dispatcher(storage=storage)

    # Pass loaded data to the dispatcher context if needed, or handlers can load it themselves via utils
    # dp["config_data"] = config_data
    # dp["groups_data"] = groups_data
    # dp["users_data"] = users_data

    # Register routers
    dp.include_router(commands.router)
    dp.include_router(admin.router) # Will be created later
    dp.include_router(callback_query.router) # Will be created later

    logger.info("Starting bot...")
    # Start polling
    # Make sure to delete webhook if it was set previously
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


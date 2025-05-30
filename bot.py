# -*- coding: utf-8 -*-
import logging
import os
import asyncio
import fcntl  # For file locking
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    PicklePersistence,
    Defaults
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz  # Required for scheduler timezone

from utils import load_groups, load_config, load_users, CONFIG_FILE, GROUPS_FILE, USERS_FILE
from handlers.admin import admin_command, cancel_admin_conversation
from handlers.callback_query import get_admin_conversation_handler, get_copy_code_handler
from handlers.scheduled_message import send_scheduled_message

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Bot Configuration --- #
# It is STRONGLY recommended to use environment variables for the token
# TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"  # As requested by user
BOT_NAME = "ChatGPTPlus2FABot"
PROJECT_DIR = "/home/ec2-user/projects/ChatGPTPlus2FABot"  # Updated path as per EC2 environment
PERSISTENCE_FILE = os.path.join(PROJECT_DIR, "bot_persistence.pickle")
LOCK_FILE = os.path.join(PROJECT_DIR, "bot.lock")  # File to ensure single instance

# Ensure async function is defined at the top level
async def post_init(application: Application) -> None:
    """Post-initialization function to set bot commands and schedule jobs."""
    logger.info("Running post_init...")
    # Set bot commands
    await application.bot.set_my_commands([
        BotCommand("admin", "الوصول إلى لوحة تحكم المسؤول")
    ])
    logger.info("Bot commands set.")

    # Initialize and start the scheduler (do not store in bot_data)
    scheduler = AsyncIOScheduler(timezone=pytz.utc)  # Use UTC for the scheduler itself

    # Load existing groups and schedule jobs
    groups = load_groups()
    logger.info(f"Loaded {len(groups)} groups from {GROUPS_FILE}.")
    for group_id_str, config in groups.items():
        try:
            group_id = int(group_id_str)
            if config.get("active", False) and config.get("secret") and config.get("interval_minutes"):
                interval = config["interval_minutes"]
                job_id = config.get("job_id", f"job_{group_id}")
                scheduler.add_job(
                    send_scheduled_message,
                    trigger=IntervalTrigger(minutes=interval),
                    args=[application, group_id],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=60  # Allow 1 minute grace time
                )
                logger.info(f"Scheduled job {job_id} for active group {group_id} with interval {interval} minutes.")
            else:
                logger.info(f"Skipping scheduling for inactive/incomplete group {group_id}.")
        except ValueError:
            logger.error(f"Invalid group ID found in groups.json: {group_id_str}")
        except Exception as e:
            logger.error(f"Error scheduling job for group {group_id_str} on startup: {e}")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Scheduler started with existing jobs.")
    else:
        # Start the scheduler even if no jobs initially, it might get jobs later
        scheduler.start()
        logger.info("Scheduler started (no initial jobs).")

    # Store scheduler in a custom attribute (not bot_data)
    application.scheduler = scheduler

async def shutdown_scheduler(application: Application) -> None:
    """Shutdown the scheduler when the application stops."""
    if hasattr(application, "scheduler"):
        scheduler = application.scheduler
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Scheduler has been shut down.")

def main() -> None:
    """Start the bot with a lock to ensure only one instance runs."""
    # Try to acquire a lock to prevent multiple instances
    lock_fd = None
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        logger.error("Another instance of the bot is already running. Exiting.")
        return

    if not TOKEN:
        logger.error("Telegram bot token not found. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        return

    # Ensure data files exist (handled by load_json in utils, but good practice)
    load_config()
    load_groups()
    load_users()

    # Create persistence object
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

    # Set default parse mode
    defaults = Defaults(parse_mode="MarkdownV2")
    # Build the application
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .persistence(persistence)
        .defaults(defaults)
        .post_init(post_init)
        .post_shutdown(shutdown_scheduler)  # Only use supported hooks
        .get_updates_timeout(30)  # زيادة الـ timeout إلى 30 ثانية (الافتراضي هو 10 ثوانٍ)
        .build()
    )

    # Get handlers
    admin_handler = get_admin_conversation_handler()
    copy_code_handler = get_copy_code_handler()

    # Add handlers
    application.add_handler(admin_handler)
    application.add_handler(copy_code_handler)

    # Start the Bot
    logger.info(f"Starting bot {BOT_NAME}...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        # Release the lock when the bot stops
        if lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass

if __name__ == "__main__":
    # Note: python-telegram-bot's run_polling handles the asyncio loop.
    # We call the main function which sets up and runs the polling.
    main()

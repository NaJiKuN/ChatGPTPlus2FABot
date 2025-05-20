import os
import time
import pyotp
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from threading import Thread

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
BOT_CHAT_ID = 792534650
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# Initialize the bot and TOTP generator
bot = Bot(token=BOT_TOKEN)
totp = pyotp.TOTP(TOTP_SECRET)

def generate_2fa_code():
    """Generate a new 2FA code"""
    return totp.now()

def send_2fa_code(context: CallbackContext):
    """Send the 2FA code to the group with copy button"""
    code = generate_2fa_code()
    message = f"""🔑 New Authentication Code Received

You have received a new authentication code.

Code: <code>{code}</code> (click to copy)

This code is valid for the next 10 minutes. Please use it promptly."""

    # Send message with reply markup for better mobile copying
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode="HTML",
        reply_markup={
            "inline_keyboard": [[
                {
                    "text": "📋 Copy Code",
                    "callback_data": f"copy_{code}"
                }
            ]]
        }
    )

def handle_copy_button(update: Update, context: CallbackContext):
    """Handle the copy button callback"""
    query = update.callback_query
    code = query.data.replace("copy_", "")
    query.answer(f"Code {code} copied to clipboard", show_alert=True)

def start(update: Update, context: CallbackContext):
    """Handler for the /start command"""
    update.message.reply_text("Bot is running and will send 2FA codes every 10 minutes.")

def start_code_scheduler():
    """Start the scheduler to send codes every 10 minutes"""
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Send initial code immediately
    send_2fa_code(CallbackContext.from_update(Update(0), dispatcher))
    
    # Schedule to run every 10 minutes (600 seconds)
    updater.job_queue.run_repeating(send_2fa_code, interval=600, first=600)
    
    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(handle_copy_button, pattern="^copy_"))
    
    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    print("Starting 2FA Telegram Bot...")
    start_code_scheduler()

import os
import time
import pyotp
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# Initialize TOTP generator
totp = pyotp.TOTP(TOTP_SECRET)

def generate_2fa_code():
    """Generate a new 2FA code"""
    return totp.now()

def send_2fa_code(context: CallbackContext):
    """Send the 2FA code to the group"""
    code = generate_2fa_code()
   # Create a keyboard with the code as a button for easy copying
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text=f"📋 Copy Code: {code}", callback_data=code)]
    ])
    
    message = f"""
🔑 New Authentication Code Received

You have received a new authentication code.

Code: {code}

This code is valid until {expiry_time}. Please use it promptly.
"""
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode="HTML"
    )

def start(update: Update, context: CallbackContext):
    """Handler for the /start command"""
    update.message.reply_text("Bot is running and will send 2FA codes every 10 minutes.")

def start_code_scheduler():
    """Start the scheduler to send codes every 10 minutes"""
    updater = Updater(BOT_TOKEN, use_context=True)
    job_queue = updater.job_queue
    
    # Send initial code immediately
    send_2fa_code(CallbackContext.from_update(Update(0), updater.dispatcher))
    
    # Schedule to run every 10 minutes (600 seconds)
    job_queue.run_repeating(send_2fa_code, interval=600, first=0)
    
    # Start the bot
    updater.dispatcher.add_handler(CommandHandler("start", start))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    print("Starting 2FA Telegram Bot...")
    start_code_scheduler()

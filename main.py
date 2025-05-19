import os
import time
import pyotp
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# Initialize the bot and TOTP
bot = Bot(token=BOT_TOKEN)
totp = pyotp.TOTP(TOTP_SECRET)

def send_2fa_code(context: CallbackContext):
    # Generate current code
    current_code = totp.now()
    expiry_time = datetime.now() + timedelta(minutes=10)
    
    # Format the message with copyable code
    message = f"""
🔑 *New Authentication Code Received*

You have received a new authentication code.

`Code: {current_code}`

This code is valid until *{expiry_time.strftime('%H:%M:%S')}* (UTC). Please use it promptly.
    """
    
    # Send the message to the group
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode="Markdown"
    )

def start(update: Update, context: CallbackContext):
    update.message.reply_text("2FA Code Bot is running. Codes will be sent to the group every 10 minutes.")

def main():
    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Add command handler
    dp.add_handler(CommandHandler("start", start))

    # Schedule the 2FA code to be sent every 10 minutes
    job_queue = updater.job_queue
    job_queue.run_repeating(send_2fa_code, interval=600, first=0)

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

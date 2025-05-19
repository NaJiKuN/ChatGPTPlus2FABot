import os
import threading
import pyotp
from telegram import Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response
from werkzeug.utils import quote as url_quote

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
PORT = int(os.environ.get('PORT', 10000))  # Default to 10000 if not set

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def health_check():
    return Response("2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    current_code = pyotp.TOTP(TOTP_SECRET).now()
    expiry_time = datetime.now() + timedelta(minutes=10)
    
    message = f"""
🔑 *New Authentication Code Received*

You have received a new authentication code.

`Code: {current_code}`

This code is valid until *{expiry_time.strftime('%H:%M:%S')}* (UTC). Please use it promptly.
    """
    
    try:
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending message: {e}")

def run_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("2FA Bot is running!")))
    
    job_queue = updater.job_queue
    job_queue.run_repeating(send_2fa_code, interval=600, first=0)
    
    print("Bot started successfully")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=PORT)

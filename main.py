import os
import threading
import pyotp
from telegram import Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response

# Initialize Flask app
app = Flask(__name__)

# Configuration - Recommended to use environment variables in production
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
PORT = int(os.environ.get('PORT', 10000))

@app.route('/')
def health_check():
    """Simple health check endpoint"""
    return Response("✅ 2FA Bot is running and healthy", status=200)

def send_2fa_code(context: CallbackContext):
    """Send 2FA code to the group"""
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔑 *New Authentication Code Received*

`Code: {current_code}`

⏳ Valid until: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"⚠️ Error sending message: {e}")

def run_bot():
    """Run the Telegram bot in a separate thread"""
    try:
        # For python-telegram-bot v20.0+
        application = Updater(BOT_TOKEN).application
        
        # Add command handlers
        application.add_handler(CommandHandler("start", 
            lambda update, context: update.message.reply_text("🤖 2FA Bot is active and sending codes every 10 minutes!")))
        
        # Schedule the recurring job
        job_queue = application.job_queue
        job_queue.run_repeating(
            send_2fa_code,
            interval=600,  # Every 10 minutes
            first=10       # Start after 10 seconds
        )
        
        print("🟢 Bot started successfully")
        application.run_polling()
    except Exception as e:
        print(f"🔴 Failed to start bot: {e}")

if __name__ == '__main__':
    print("🚀 Starting application...")
    
    # Start bot in a daemon thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask app
    try:
        app.run(host='0.0.0.0', port=PORT, use_reloader=False)
    except Exception as e:
        print(f"🔴 Failed to start Flask app: {e}")

import os
import sys
import subprocess
import threading
import logging

# محاولة استيراد الحزم المطلوبة، وتثبيتها إذا لزم الأمر
try:
    from flask import Flask, Response, request
    import pyotp
    from telegram.ext import Updater, CommandHandler, CallbackContext
    from datetime import datetime, timedelta
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    from flask import Flask, Response, request
    import pyotp
    from telegram.ext import Updater, CommandHandler, CallbackContext
    from datetime import datetime, timedelta

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# التكوينات
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
PORT = int(os.environ.get('PORT', 10000))

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔑 New Authentication Code Received

Code: {current_code}

Valid until: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message
        )
        logger.info(f"Sent 2FA code: {current_code}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def start_command(update, context):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🤖 2FA Bot is active and sending codes every 10 minutes!"
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def run_bot():
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", start_command))
        
        job_queue = updater.job_queue
        job_queue.run_repeating(send_2fa_code, interval=600, first=0)
        
        logger.info("Bot started successfully")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == '__main__':
    logger.info("Starting application...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

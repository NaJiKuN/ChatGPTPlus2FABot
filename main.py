import os
import logging
import pyotp
from telegram import Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response

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

# متغير عالمي لتخزين حالة البوت
bot_running = False

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
    global bot_running
    if bot_running:
        logger.warning("Bot is already running!")
        return

    try:
        bot_running = True
        updater = Updater(BOT_TOKEN, use_context=True)
        
        # إضافة معالج للأخطاء
        updater.dispatcher.add_error_handler(error_handler)
        
        updater.dispatcher.add_handler(CommandHandler("start", start_command))
        
        job_queue = updater.job_queue
        job_queue.run_repeating(send_2fa_code, interval=600, first=10)
        
        logger.info("Bot started successfully")
        updater.start_polling(drop_pending_updates=True)
        updater.idle()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        bot_running = False

def error_handler(update, context):
    logger.error(f"Error occurred: {context.error}")

if __name__ == '__main__':
    logger.info("Starting application...")
    
    # بدء البوت مباشرة بدون thread منفصل
    run_bot()
    
    # بدء Flask فقط إذا لم يتم تشغيله من قبل gunicorn
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        app.run(host='0.0.0.0', port=PORT, use_reloader=False)

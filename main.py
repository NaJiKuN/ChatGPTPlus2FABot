import os
import logging
import pyotp
from telegram import ParseMode
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

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔐 *كود المصادقة الثنائية*

📋 الكود: `{current_code}`

⏳ صالح حتى: {expiry_time.strftime('%H:%M:%S')} UTC

_يرجى استخدامه خلال 10 دقائق_
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"تم إرسال الكود: {current_code}")
    except Exception as e:
        logger.error(f"خطأ في الإرسال: {e}")

def start_command(update, context):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🤖 البوت يعمل ويقوم بإرسال أكواد المصادقة كل 10 دقائق",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"خطأ في أمر البدء: {e}")

def run_bot():
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", start_command))
        
        job_queue = updater.job_queue
        job_queue.run_repeating(send_2fa_code, interval=600, first=10)
        
        logger.info("🟢 تم تشغيل البوت بنجاح")
        updater.start_polling()
        updater.idle()
    except Exception as e:
        logger.error(f"🔴 فشل تشغيل البوت: {e}")

if __name__ == '__main__':
    # إذا كان التشغيل كـ Worker
    if os.getenv('RUN_AS_WORKER') == 'true':
        logger.info("🚀 بدء تشغيل خدمة البوت...")
        run_bot()
    else:
        # إذا كان التشغيل كـ Web Service
        PORT = int(os.environ.get('PORT', 10000))
        logger.info("🌐 بدء تشغيل خدمة الويب...")
        app.run(host='0.0.0.0', port=PORT)

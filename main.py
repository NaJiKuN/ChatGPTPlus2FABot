import os
import threading
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

# التكوينات - تأكد من تعيينها في متغيرات البيئة
BOT_TOKEN = os.getenv('BOT_TOKEN')
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
TOTP_SECRET = os.getenv('TOTP_SECRET')

# التحقق من المتغيرات
if not all([BOT_TOKEN, GROUP_CHAT_ID, TOTP_SECRET]):
    logger.error("❌ متغيرات البيئة ناقصة! يلزم تعيين: BOT_TOKEN, GROUP_CHAT_ID, TOTP_SECRET")
    exit(1)

try:
    GROUP_CHAT_ID = int(GROUP_CHAT_ID)
except ValueError:
    logger.error("❌ GROUP_CHAT_ID يجب أن يكون رقماً صحيحاً")
    exit(1)

@app.route('/')
def health_check():
    return Response("✅ البوت يعمل بشكل طبيعي", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔐 *كود التحقق*

📋 `{current_code}`

⏳ صالح حتى: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"تم إرسال الكود: {current_code}")
    except Exception as e:
        logger.error(f"خطأ في الإرسال: {str(e)}")

def start_bot():
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", 
            lambda update, ctx: update.message.reply_text("🤖 البوت يعمل!")))
        
        job_queue = updater.job_queue
        job_queue.run_repeating(send_2fa_code, interval=600, first=10)
        
        logger.info("🟢 البوت يعمل الآن")
        updater.start_polling()
    except Exception as e:
        logger.error(f"🔴 فشل تشغيل البوت: {str(e)}")

# تشغيل البوت في خيط منفصل
bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()

if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=PORT)

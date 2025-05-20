import os
import threading
import logging
import pyotp
from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response
from dotenv import load_dotenv  # جديد

# تحميل المتغيرات من ملف .env (للتطوير المحلي)
load_dotenv()

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============= إعداد المتغيرات البيئية =============
CONFIG = {
    'BOT_TOKEN': os.getenv('BOT_TOKEN', '8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM'),
    'GROUP_CHAT_ID': os.getenv('GROUP_CHAT_ID', '-1002329495586'),
    'TOTP_SECRET': os.getenv('TOTP_SECRET', 'ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI'),
    'PORT': int(os.getenv('PORT', '10000')),
    'ENVIRONMENT': os.getenv('ENVIRONMENT', 'production')
}

# التحقق من صحة المتغيرات
try:
    CONFIG['GROUP_CHAT_ID'] = int(CONFIG['GROUP_CHAT_ID'])
except ValueError:
    logger.error("❌ خطأ: GROUP_CHAT_ID يجب أن يكون رقماً صحيحاً")
    exit(1)

if not all(CONFIG.values()):
    missing = [k for k, v in CONFIG.items() if not v]
    logger.error(f"❌ متغيرات ناقصة: {', '.join(missing)}")
    exit(1)

# ============= وظائف البوت =============
@app.route('/')
def health_check():
    return Response(f"✅ البوت يعمل (بيئة: {CONFIG['ENVIRONMENT']})", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(CONFIG['TOTP_SECRET']).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔐 *كود التحقق الجديد*

📋 `{current_code}`

⏳ وقت الكود التالي: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        context.bot.send_message(
            chat_id=CONFIG['GROUP_CHAT_ID'],
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"تم إرسال الكود: {current_code}")
    except Exception as e:
        logger.error(f"خطأ في الإرسال: {str(e)}")

def start_bot():
    try:
        updater = Updater(CONFIG['BOT_TOKEN'], use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", 
            lambda update, ctx: update.message.reply_text(
                "🤖 بوت المصادقة يعمل بشكل صحيح ✅",
                parse_mode=ParseMode.MARKDOWN_V2
            )))
        
        job_queue = updater.job_queue
        job_queue.run_repeating(
            send_2fa_code,
            interval=600,  # كل 10 دقائق
            first=10       # بدء بعد 10 ثواني
        )
        
        logger.info("🟢 تم تشغيل البوت بنجاح")
        updater.start_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"🔴 فشل تشغيل البوت: {str(e)}")
        os._exit(1)  # إغلاق كامل للتطبيق عند فشل البوت

# ============= تشغيل الخدمة =============
if __name__ == '__main__':
    logger.info(f"🚀 بدء التشغيل في بيئة {CONFIG['ENVIRONMENT']}")
    
    # تشغيل البوت في خيط منفصل
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    # تشغيل خادم الويب
    app.run(
        host='0.0.0.0',
        port=CONFIG['PORT'],
        debug=(CONFIG['ENVIRONMENT'] == 'development'),
        use_reloader=False
    )

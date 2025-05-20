import os
import logging
import pyotp
from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta

# محاولة استيراد Flask مع تثبيت تلقائي إذا لزم الأمر
try:
    from flask import Flask, Response
except ImportError:
    print("Flask غير مثبت، جاري التثبيت...")
    import subprocess
    subprocess.check_call(['pip', 'install', 'Flask==2.0.2', 'Werkzeug==2.0.2'])
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

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        # رسالة مع رمز قابل للنسخ
        message = f"""
🔐 *كود المصادقة الثنائية الجديد*

📋 يمكنك نسخ الكود من هنا:
`{current_code}`

⏳ صالح حتى: {expiry_time.strftime('%H:%M:%S')} UTC

_يرجى استخدامه خلال 10 دقائق_
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"تم إرسال كود المصادقة: {current_code}")
    except Exception as e:
        logger.error(f"خطأ في إرسال الرسالة: {e}")

def start_command(update, context):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🤖 بوت المصادقة الثنائية يعمل ويقوم بإرسال الأكواد كل 10 دقائق",
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.error(f"خطأ في أمر البدء: {e}")

def error_handler(update, context):
    logger.error(f"حدث خطأ: {context.error}")

def run_bot():
    try:
        updater = Updater(BOT_TOKEN, use_context=True)
        
        # إضافة معالج للأخطاء
        updater.dispatcher.add_error_handler(error_handler)
        
        # إضافة الأوامر
        updater.dispatcher.add_handler(CommandHandler("start", start_command))
        
        # جدولة إرسال الأكواد
        job_queue = updater.job_queue
        job_queue.run_repeating(
            send_2fa_code,
            interval=600,  # كل 10 دقائق
            first=10       # بدء بعد 10 ثواني
        )
        
        logger.info("تم تشغيل البوت بنجاح")
        updater.start_polling(drop_pending_updates=True)
        updater.idle()
    except Exception as e:
        logger.error(f"فشل تشغيل البوت: {e}")

if __name__ == '__main__':
    logger.info("جاري بدء التطبيق...")
    run_bot()
    
    # تشغيل Flask فقط إذا لم يتم تشغيله من قبل gunicorn
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        app.run(host='0.0.0.0', port=PORT, use_reloader=False)

import logging
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import pyotp
import time
from threading import Thread

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# تهيئة التسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)

def generate_2fa_code():
    """توليد رمز المصادقة الثنائية"""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def send_2fa_code(context: CallbackContext):
    """إرسال رمز المصادقة إلى المجموعة"""
    code = generate_2fa_code()
    message = f"""
🔑 New Authentication Code Received

You have received a new authentication code.

`Code: {code}`

This code is valid for the next 10 minutes. Please use it promptly.
    """
    context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message, parse_mode='Markdown')

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    update.message.reply_text('Bot is running and will send 2FA codes every 10 minutes to the group.')

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    """الدالة الرئيسية"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # إضافة معالجات الأوامر
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", start))
    
    # تسجيل معالج الأخطاء
    dp.add_error_handler(error)

    # بدء البوت
    updater.start_polling()

    # جدولة إرسال الرمز كل 10 دقائق
    jq = updater.job_queue
    jq.run_repeating(send_2fa_code, interval=600, first=0)

    # تشغيل البوت حتى الضغط على Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

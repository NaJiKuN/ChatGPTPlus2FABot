import os
import time
import pyotp
import logging
from telegram import Bot
from dotenv import load_dotenv

# تحميل المتغيرات من .env
load_dotenv()

# إعدادات التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تحميل المتغيرات من البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
TOTP_SECRET = os.getenv("TOTP_SECRET")

# التحقق من القيم
if not BOT_TOKEN or not GROUP_CHAT_ID or not TOTP_SECRET:
    logger.error("❌ BOT_TOKEN أو GROUP_CHAT_ID أو TOTP_SECRET غير معرف!")
    exit(1)

bot = Bot(token=BOT_TOKEN)
totp = pyotp.TOTP(TOTP_SECRET)

def send_code():
    try:
        code = totp.now()
        message = f"""🔑 New Authentication Code Received

You have received a new authentication code.

Code: {code}

This code is valid for the next 10 minutes. Please use it promptly."""
        bot.send_message(chat_id=GROUP_CHAT_ID, text=message)
        logger.info(f"✅ تم إرسال الكود بنجاح: {code}")
    except Exception as e:
        logger.error(f"❌ خطأ أثناء إرسال الكود: {e}")

if __name__ == "__main__":
    logger.info("🚀 بدأ تشغيل البوت...")
    while True:
        send_code()
        time.sleep(600)  # كل 10 دقائق

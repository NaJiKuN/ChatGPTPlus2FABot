import telegram
import pyotp
import schedule
import time
import asyncio
from telegram.ext import Application
import logging

# إعداد التسجيل لتتبع الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# توكن البوت من BotFather
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
# معرف المجموعة
CHAT_ID = "-1002329495586"
# مفتاح إعداد المصادقة الثنائية
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# إعداد TOTP باستخدام المفتاح
totp = pyotp.TOTP(TOTP_SECRET, interval=600)  # الرمز صالح لمدة 10 دقائق (600 ثانية)

# دالة لإرسال رمز المصادقة
async def send_2fa_code():
    bot = telegram.Bot(token=TOKEN)
    code = totp.now()  # توليد رمز TOTP الحالي
    message = "🔑 *New Authentication Code Received*\n\n"
        "You have received a new authentication code -.\n\n"
        f"Code: ```{code}```\n\n"
        "This code is valid for the next 10 minutes. Please use it promptly."
   
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logger.info(f"Sent 2FA code: {code}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

# دالة لجدولة المهام
def schedule_jobs():
    # جدولة إرسال الرسالة كل 10 دقائق
    schedule.every(10).minutes.do(lambda: asyncio.run(send_2fa_code()))

async def main():
    # إعداد البوت
    application = Application.builder().token(TOKEN).build()
    
    # تشغيل الجدولة في خيط منفصل
    schedule_jobs()
    
    # بدء البوت
    await application.initialize()
    await application.start()
    
    # الحفاظ على تشغيل الجدولة
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(main())

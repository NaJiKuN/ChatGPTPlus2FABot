import pyotp
import os
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),  # حفظ السجلات في ملف
        logging.StreamHandler()  # عرض السجلات في الطرفية
    ]
)
logger = logging.getLogger(__name__)

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات البوت
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
SECRET_KEY = os.getenv("SECRET_KEY")

# التحقق من متغيرات البيئة
if not all([BOT_TOKEN, GROUP_CHAT_ID, SECRET_KEY]):
    logger.error("متغيرات البيئة مفقودة! تأكد من إعداد ملف .env بشكل صحيح.")
    raise ValueError("مطلوب BOT_TOKEN وGROUP_CHAT_ID وSECRET_KEY في ملف .env")

try:
    GROUP_CHAT_ID = int(GROUP_CHAT_ID)  # تحويل GROUP_CHAT_ID إلى عدد صحيح
except ValueError:
    logger.error("GROUP_CHAT_ID يجب أن يكون عددًا صحيحًا!")
    raise

# إعداد TOTP
totp = pyotp.TOTP(SECRET_KEY, interval=30)  # ضبط الفاصل الزمني لـ TOTP على 30 ثانية (القيمة القياسية)

# دالة إرسال الرمز مع إعادة المحاولة
@retry(
    stop=stop_after_attempt(5),  # 5 محاولات
    wait=wait_exponential(multiplier=1, min=4, max=60),  # انتظار متزايد بين المحاولات
    retry=retry_if_exception_type(TelegramError)  # إعادة المحاولة عند أخطاء تيليجرام فقط
)
async def send_2fa_code(bot, code):
    message = f"رمز المصادقة الثنائية: {code}"
    await bot.send_message(chat_id=GROUP_CHAT_ID, text=message)
    logger.info(f"تم إرسال الرمز: {code}")

async def main():
    bot = Bot(token=BOT_TOKEN)
    last_code = None  # تتبع آخر رمز تم إرساله لتجنب التكرار

    while True:
        try:
            # توليد رمز 2FA
            current_code = totp.now()
            
            # إرسال الرمز فقط إذا كان جديدًا
            if current_code != last_code:
                await send_2fa_code(bot, current_code)
                last_code = current_code
            
            # الانتظار لمدة 10 دقائق (600 ثانية)
            await asyncio.sleep(600)
            
        except TelegramError as e:
            logger.error(f"خطأ في إرسال الرسالة: {e}")
            await asyncio.sleep(60)  # الانتظار دقيقة قبل إعادة المحاولة
        except Exception as e:
            logger.error(f"خطأ غير متوقع: {e}")
            await asyncio.sleep(60)  # الانتظار دقيقة قبل إعادة المحاولة

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("تم إيقاف البوت بواسطة المستخدم.")
    except Exception as e:
        logger.error(f"خطأ في بدء البوت: {e}")
if __name__ == '__main__':
    main()

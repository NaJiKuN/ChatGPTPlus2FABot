import asyncio
import logging
from telegram import Bot
import pyotp

# إعداد السجلّات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ضع هنا بياناتك مباشرة:
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
CHAT_ID = "-1002329495586"
SECRET_KEY = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# تأكد من أن القيم موجودة (اختياري)
if not BOT_TOKEN or not CHAT_ID or not SECRET_KEY:
    logger.error("❌ BOT_TOKEN, CHAT_ID, or SECRET_KEY are missing!")
    exit(1)

bot = Bot(token=BOT_TOKEN)

def generate_code():
    totp = pyotp.TOTP(SECRET_KEY, interval=600)  # كل 10 دقائق
    return totp.now()

def build_message(code):
    return 
        "🔑 *New Authentication Code Received*\n\n"
        "You have received a new authentication code.\n\n"
        "Code: "
        f"`{current_code}`\n\n"
        "*This code is valid for the next 10 minutes. Please use it promptly.*"

async def send_code():
    try:
        code = generate_code()
        message = build_message(code)
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logger.info(f"✅ Sent code: {code}")
    except Exception as e:
        logger.error(f"❌ Failed to send message: {e}")

async def main():
    logger.info("🚀 Bot started.")
    while True:
        await send_code()
        await asyncio.sleep(600)  # 10 دقائق

if __name__ == "__main__":
    asyncio.run(main())

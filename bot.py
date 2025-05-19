import asyncio
import logging
from telegram import Bot
import pyotp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
CHAT_ID = "-1002329495586"
SECRET_KEY = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

bot = Bot(token=BOT_TOKEN)

def generate_code():
    totp = pyotp.TOTP(SECRET_KEY, interval=600)  # 10 دقائق
    return totp.now()

def build_message(code: str) -> str:
    return (
        "🔑 *New Authentication Code Received*\n\n"
        "You have received a new authentication code -.\n\n"
        f"Code: ```{code}```\n\n"
        "This code is valid for the next 10 minutes. Please use it promptly."
    )

async def send_code():
    try:
        current_code = generate_code()  # هنا عرفنا current_code
        message = build_message(current_code)  # تمرير المتغير للدالة
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='MarkdownV2')
        logger.info(f"✅ Sent code: {current_code}")
    except Exception as e:
        logger.error(f"❌ Failed to send message: {e}")

async def main():
    logger.info("🚀 Bot started.")
    while True:
        await send_code()
        await asyncio.sleep(600)  # 10 دقائق

if __name__ == "__main__":
    asyncio.run(main())

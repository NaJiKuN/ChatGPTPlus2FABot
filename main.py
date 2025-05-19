import time
import pyotp
import logging
import telegram
from telegram.error import TelegramError

# إعدادات البوت
BOT_TOKEN = '8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM'
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = 'ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI'

# إنشاء كائن البوت
bot = telegram.Bot(token=BOT_TOKEN)

# إعداد Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_code():
    try:
        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()

        message = (
            "🔑 New Authentication Code Received\n\n"
            "You have received a new authentication code.\n\n"
            f"Code: {code}\n\n"
            "This code is valid for the next 10 minutes. Please use it promptly."
        )

        bot.send_message(chat_id=GROUP_CHAT_ID, text=message)
        logger.info(f"Sent code: {code}")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == '__main__':
    logger.info("Bot started and running every 10 minutes.")
    while True:
        send_code()
        time.sleep(600)  # 10 دقائق

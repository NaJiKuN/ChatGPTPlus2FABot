import pyotp
import logging
from telegram import Bot
from telegram.ext import Updater, CallbackContext, JobQueue

BOT_TOKEN = '8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM'
GROUP_CHAT_ID = -4985579920
TOTP_SECRET = 'ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

totp = pyotp.TOTP(TOTP_SECRET)

def send_totp_code(context: CallbackContext):
    code = totp.now()
    context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"رمز المصادقة الثنائية الحالي: {code}")

def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    job_queue: JobQueue = updater.job_queue
    job_queue.run_repeating(send_totp_code, interval=600, first=0)
    updater.start_polling()
    logger.info("البوت يعمل...")
    updater.idle()

if __name__ == '__main__':
    main()

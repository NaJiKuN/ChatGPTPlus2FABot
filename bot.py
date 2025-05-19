import logging
import os
import time
import pyotp
from telegram import Bot

BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
CHAT_ID = "-1002329495586"
SECRET_KEY = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

bot = Bot(token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO)

def generate_code():
    totp = pyotp.TOTP(SECRET_KEY, interval=600)  # كل 10 دقائق
    return totp.now()

def build_message(code):
    return f"""🔑 New Authentication Code Received

You have received a new authentication code.

Code: {code}

This code is valid for the next 10 minutes. Please use it promptly."""

def send_code():
    code = generate_code()
    message = build_message(code)
    bot.send_message(chat_id=CHAT_ID, text=message)
    logging.info(f"Sent code: {code}")

def main():
    logging.info("Bot started.")
    while True:
        send_code()
        time.sleep(600)  # كل 10 دقائق

if __name__ == "__main__":
    main()

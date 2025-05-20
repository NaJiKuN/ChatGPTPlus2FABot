import os
import time
import pytz
from datetime import datetime
import schedule
import pyotp
from telegram import Bot, ParseMode
from telegram.error import TelegramError

# Bot configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
CHAT_ID = -1002329495586  # Group chat ID
BOT_CHAT_ID = 792534650   # Bot chat ID (optional, for logging)
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"  # 2FA secret key

# Initialize the bot
bot = Bot(token=BOT_TOKEN)

def send_2fa_code():
    try:
        # Generate the 2FA code
        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()

        # Format the message with copyable code
        message = (
            "🔑 New Authentication Code Received\n\n"
            "You have received a new authentication code.\n\n"
            f"Code: <code>{code}</code>\n\n"
            "This code is valid for the next 10 minutes. Please use it promptly."
        )

        # Send the message to the group
        bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML
        )
        print(f"Code sent: {code} at {datetime.now(pytz.utc)}")
    except TelegramError as e:
        print(f"Error sending message: {e}")

def main():
    print("Bot is running...")
    # Schedule the code to be sent every 10 minutes
    schedule.every(10).minutes.do(send_2fa_code)

    # Initial send
    send_2fa_code()

    # Keep the bot running
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()

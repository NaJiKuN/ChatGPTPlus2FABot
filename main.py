import os
import random
import time
from datetime import datetime, timedelta
import pytz
import telegram
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
BOT_CHAT_ID = 792534650
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
BOT_NAME = "ChatGPTPlus2FA"
BOT_USERNAME = "@ChatGPTPlus2FABot"
GITHUB_URL = "https://github.com/NaJiKuN"

# Initialize bot
bot = telegram.Bot(token=BOT_TOKEN)

def generate_2fa_code():
    """Generate a random 6-digit 2FA code"""
    return str(random.randint(100000, 999999))

def send_2fa_code():
    """Generate and send a new 2FA code to the group"""
    code = generate_2fa_code()
    expiry_time = (datetime.now(pytz.utc) + timedelta(minutes=10)).strftime('%H:%M:%S UTC')
    
    # Create a keyboard with the code as a button for easy copying
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text=f"📋 Copy Code: {code}", callback_data=code)]
    ])
    
    message = f"""
🔑 New Authentication Code Received

You have received a new authentication code.

Code: {code}

This code is valid until {expiry_time}. Please use it promptly.
"""
    
    bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        reply_markup=keyboard
    )
    print(f"Sent new 2FA code: {code} at {datetime.now(pytz.utc)}")

def main():
    print(f"{BOT_NAME} bot is starting...")
    print(f"GitHub: {GITHUB_URL}")
    
    # Send initial message to confirm bot is running
    bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"🔄 {BOT_NAME} bot is now active and will send new 2FA codes every 10 minutes."
    )
    
    # Main loop to send codes every 10 minutes
    while True:
        try:
            send_2fa_code()
            time.sleep(600)  # 10 minutes in seconds
        except Exception as e:
            print(f"Error occurred: {e}")
            time.sleep(60)  # Wait 1 minute before retrying if error occurs

if __name__ == "__main__":
    main()

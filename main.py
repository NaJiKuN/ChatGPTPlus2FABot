import os
import threading
import pyotp
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime, timedelta
from flask import Flask, Response

app = Flask(__name__)

# التكوينات
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
PORT = int(os.environ.get('PORT', 10000))

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running and healthy", status=200)

async def send_2fa_code(context: ContextTypes.DEFAULT_TYPE):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔑 *New Authentication Code Received*

`Code: {current_code}`

⏳ Valid until: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"⚠️ Error sending message: {e}")

async def start_command(update, context):
    await update.message.reply_text("🤖 2FA Bot is active and sending codes every 10 minutes!")

def run_bot():
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        
        # Schedule the recurring job
        job_queue = application.job_queue
        job_queue.run_repeating(
            send_2fa_code,
            interval=600,  # Every 10 minutes
            first=10       # Start after 10 seconds
        )
        
        print("🟢 Bot started successfully")
        application.run_polling()
    except Exception as e:
        print(f"🔴 Failed to start bot: {e}")

if __name__ == '__main__':
    print("🚀 Starting application...")
    
    # Start bot in a daemon thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask app
    try:
        app.run(host='0.0.0.0', port=PORT, use_reloader=False)
    except Exception as e:
        print(f"🔴 Failed to start Flask app: {e}")

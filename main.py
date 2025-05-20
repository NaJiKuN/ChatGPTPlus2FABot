import os
import threading
import pyotp
from telegram import Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response

app = Flask(__name__)

# التكوينات - يُفضل وضعها في متغيرات البيئة
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
PORT = int(os.environ.get('PORT', 10000))

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    try:
        current_code = pyotp.TOTP(TOTP_SECRET).now()
        expiry_time = datetime.now() + timedelta(minutes=10)
        
        message = f"""
🔑 *New Authentication Code Received*

Code: `{current_code}`

Valid until: {expiry_time.strftime('%H:%M:%S')} UTC
        """
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"⚠️ Error: {str(e)}")

def run_bot():
    # الطريقة الحديثة للإصدار 20.0+
    application = Updater(BOT_TOKEN).application
    
    application.add_handler(CommandHandler("start", 
        lambda u,c: u.message.reply_text("🤖 2FA Bot is active!")))
    
    job_queue = application.job_queue
    job_queue.run_repeating(send_2fa_code, interval=600, first=0)
    
    print("🟢 Bot started successfully")
    application.run_polling()

if __name__ == '__main__':
    print("🚀 Starting application...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

import os
import time
import pyotp
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from datetime import datetime, timedelta
from flask import Flask, Response

app = Flask(__name__)

# التكوينات
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
ADMIN_IDS = [792534650]  # أرقام معرفات المشرفين

# حالة البوت
bot_active = True
updater = None

@app.route('/')
def health_check():
    return Response("✅ 2FA Bot is running", status=200)

def send_2fa_code(context: CallbackContext):
    global bot_active
    if not bot_active:
        return
        
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

def start(update: Update, context: CallbackContext):
    global bot_active
    bot_active = True
    update.message.reply_text("🤖 Bot is running! Use /stop to pause code sending.")

def stop(update: Update, context: CallbackContext):
    global bot_active
    user_id = update.effective_user.id
    
    if user_id in ADMIN_IDS:
        bot_active = False
        update.message.reply_text("⏸️ Bot paused. No more codes will be sent. Use /start to resume.")
    else:
        update.message.reply_text("🚫 You are not authorized to stop this bot.")

def run_bot():
    global updater
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop))
    
    job_queue = updater.job_queue
    job_queue.run_repeating(send_2fa_code, interval=600, first=0)
    
    print("🟢 Bot started successfully")
    updater.start_polling()

if __name__ == '__main__':
    print("🚀 Starting application...")
    
    # تشغيل البوت
    run_bot()
    
    # تشغيل Flask في نفس الخيط (للتجنب مشاكل Render)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), use_reloader=False, threaded=True)

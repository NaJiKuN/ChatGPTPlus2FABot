from flask import Flask
import threading
import time
import pyotp
import requests
import os

# قراءة المتغيرات البيئية
BOT_TOKEN = '8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM'
CHAT_ID = '-1002329495586'
SECRET_KEY = 'ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI'

# تهيئة مكتبة TOTP
totp = pyotp.TOTP(SECRET_KEY)

def send_2fa_code():
    current_code = totp.now()
    
    # رسالة منسقة بـ Markdown
    message = (
        "🔑 *New Authentication Code Received*\n\n"
        "You have received a new authentication code.\n\n"
        "Code: "
        f"`{current_code}`\n\n"
        "*This code is valid for the next 10 minutes. Please use it promptly.*"
    )
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, data=payload)
    print(f"تم الإرسال: {current_code} | حالة الطلب: {response.status_code}")

def main():
    while True:
        send_2fa_code()
        time.sleep(600)  # كل 10 دقائق

# Flask dummy server to keep Render happy
app = Flask(__name__)

@app.route("/")
def home():
    return "2FA bot is running..."

if __name__ == "__main__":
    threading.Thread(target=send_2fa_code).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

import time
import pyotp
import requests

# إعدادات البوت
BOT_TOKEN = '8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM'
CHAT_ID = '-4985579920'
SECRET_KEY = 'ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI'

# تهيئة مكتبة TOTP
totp = pyotp.TOTP(SECRET_KEY)

def send_2fa_code():
    current_code = totp.now()
    message = f'رمز المصادقة الثنائية الحالي هو: {current_code}'
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    response = requests.post(url, data=payload)
    print(f"تم الإرسال: {message} | حالة الطلب: {response.status_code}")

def main():
    while True:
        send_2fa_code()
        time.sleep(600)  # كل 10 دقائق = 600 ثانية

if __name__ == "__main__":
    main()

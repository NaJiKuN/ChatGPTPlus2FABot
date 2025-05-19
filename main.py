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
        if response.status_code != 200:
            print("❌ فشل الإرسال:", response.status_code, response.text)
        else:
            print(f"✅ تم إرسال الكود: {current_code}")
    except Exception as e:
        print("⚠️ حدث خطأ:", e)
def main():
    while True:
        send_2fa_code()
        time.sleep(600)  # كل 10 دقائق

if __name__ == "__main__":
    main()

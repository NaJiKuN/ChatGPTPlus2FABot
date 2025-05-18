# Telegram 2FA Bot

بوت تليجرام يقوم بإرسال رمز المصادقة الثنائية TOTP إلى مجموعة تليجرام كل 10 دقائق.

## المتطلبات

```bash
pip install python-telegram-bot pyotp
```

## التشغيل المحلي

```bash
python3 bot.py
```

## تشغيل دائم باستخدام systemd

1. عدل ملف الخدمة `telegram-2fa-bot.service` وضع اسم المستخدم الصحيح.
2. انسخ الملف إلى المسار التالي:

```bash
sudo cp telegram-2fa-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-2fa-bot.service
sudo systemctl start telegram-2fa-bot.service
```

## النشر على Render

- اربط المستودع بحسابك على GitHub.
- استخدم Python Web Service وقم بضبط `Start Command` إلى:

```bash
python bot.py
```


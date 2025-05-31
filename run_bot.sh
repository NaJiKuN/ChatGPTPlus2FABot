#!/bin/bash

# هذا السكريبت يستخدم لتشغيل بوت التليجرام للمصادقة الثنائية 2FA
# يقوم بتشغيل البوت وإعادة تشغيله في حالة توقفه

# المسار إلى ملف البوت
BOT_PATH="/home/ec2-user/projects/ChatGPTPlus2FABot/bot.py"

# تأكد من وجود المجلد
mkdir -p "$(dirname "$BOT_PATH")"

# تثبيت المتطلبات إذا لم تكن موجودة
pip3 install python-telegram-bot pyotp python-dateutil

# وظيفة لتشغيل البوت
run_bot() {
    echo "بدء تشغيل بوت المصادقة الثنائية 2FA..."
    python3 "$BOT_PATH"
}

# وظيفة للتحقق من حالة البوت وإعادة تشغيله إذا توقف
check_and_restart() {
    if ! pgrep -f "$BOT_PATH" > /dev/null; then
        echo "تم اكتشاف توقف البوت. إعادة التشغيل..."
        run_bot &
    fi
}

# تشغيل البوت في الخلفية
run_bot &

# حلقة للتحقق من حالة البوت كل دقيقة
while true; do
    sleep 60
    check_and_restart
done

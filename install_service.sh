#!/bin/bash

# هذا السكريبت يستخدم لتثبيت وتشغيل بوت التليجرام للمصادقة الثنائية 2FA على خادم AWS EC2
# يقوم بتثبيت المتطلبات وإعداد البوت كخدمة نظام

# تأكد من تشغيل السكريبت كمستخدم root
if [ "$(id -u)" -ne 0 ]; then
    echo "يجب تشغيل هذا السكريبت كمستخدم root"
    exit 1
fi

# المسار إلى مجلد المشروع
PROJECT_DIR="/home/ec2-user/projects/ChatGPTPlus2FABot"
BOT_PATH="$PROJECT_DIR/bot.py"

# إنشاء مجلد المشروع إذا لم يكن موجوداً
mkdir -p "$PROJECT_DIR"

# تثبيت المتطلبات
echo "تثبيت المتطلبات..."
yum update -y
yum install -y python3 python3-pip git

# تثبيت المكتبات المطلوبة
pip3 install python-telegram-bot pyotp python-dateutil

# نسخ ملف البوت إلى المجلد المطلوب
echo "نسخ ملفات البوت..."
cp bot.py "$BOT_PATH"
chmod +x "$BOT_PATH"

# إنشاء ملف خدمة systemd
echo "إعداد البوت كخدمة نظام..."
cat > /etc/systemd/system/telegram-2fa-bot.service << EOL
[Unit]
Description=Telegram 2FA Bot Service
After=network.target

[Service]
User=ec2-user
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $BOT_PATH
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=telegram-2fa-bot

[Install]
WantedBy=multi-user.target
EOL

# تفعيل وتشغيل الخدمة
systemctl daemon-reload
systemctl enable telegram-2fa-bot.service
systemctl start telegram-2fa-bot.service

echo "تم تثبيت وتشغيل بوت التليجرام للمصادقة الثنائية 2FA بنجاح!"
echo "يمكنك التحقق من حالة البوت باستخدام الأمر: systemctl status telegram-2fa-bot.service"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت إرسال رموز المصادقة 2FA
يستخدم هذا السكريبت مع cron job لإرسال رموز المصادقة بشكل دوري
"""

import logging
import sqlite3
import os
import pyotp
import datetime
import pytz
import sys
import telegram
import asyncio

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filename="/home/ec2-user/projects/ChatGPTPlus2FABot/send_codes.log"
)
logger = logging.getLogger(__name__)

# توكن البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"

# مسار ملف قاعدة البيانات
DB_FILE = "/home/ec2-user/projects/ChatGPTPlus2FABot/bot_data.db"

# وظائف قاعدة البيانات
def get_active_groups():
    """الحصول على جميع المجموعات النشطة من قاعدة البيانات."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT group_id, totp_secret, interval_minutes, message_format, timezone, time_format FROM groups WHERE is_active = 1"
        )
        active_groups = cursor.fetchall()
        conn.close()
        return active_groups
    except Exception as e:
        logger.error(f"خطأ في الحصول على المجموعات النشطة: {e}")
        return []

# وظائف TOTP
def generate_totp(secret):
    """توليد رمز TOTP من سر."""
    totp = pyotp.TOTP(secret)
    return totp.now()

def format_next_time(interval_minutes, timezone_str="Asia/Jerusalem", time_format="12h"):
    """تنسيق الوقت التالي للرسالة."""
    tz = pytz.timezone(timezone_str)
    now = datetime.datetime.now(tz)
    next_time = now + datetime.timedelta(minutes=interval_minutes)
    
    if time_format == "12h":
        return next_time.strftime("%I:%M:%S %p")  # تنسيق 12 ساعة مع AM/PM
    else:
        return next_time.strftime("%H:%M:%S")  # تنسيق 24 ساعة

# وظيفة إرسال رموز التحقق
async def send_verification_codes():
    """إرسال رموز التحقق إلى المجموعات النشطة."""
    try:
        # إنشاء كائن البوت
        bot = telegram.Bot(token=TOKEN)
        
        # الحصول على المجموعات النشطة
        active_groups = get_active_groups()
        
        if not active_groups:
            logger.info("لا توجد مجموعات نشطة.")
            return
        
        for group in active_groups:
            group_id, totp_secret, interval, message_format, timezone, time_format = group
            
            if not totp_secret:
                logger.warning(f"المجموعة {group_id} ليس لديها سر TOTP مكون.")
                continue
            
            # تنسيق الوقت التالي
            next_time = format_next_time(interval, timezone, time_format)
            
            # تنسيق الرسالة
            if not message_format:
                message_format = '🔐 2FA Verification Code\n\nNext code at: {next_time}'
            
            message = message_format.format(next_time=next_time)
            
            # إنشاء لوحة مفاتيح مضمنة مع زر Copy Code
            keyboard = [[telegram.InlineKeyboardButton("Copy Code", callback_data=f'copy_code_{group_id}')]]
            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            
            try:
                # إرسال رسالة إلى المجموعة
                await bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)
                logger.info(f"تم إرسال رسالة رمز التحقق إلى المجموعة {group_id}")
            except Exception as e:
                logger.error(f"فشل إرسال رسالة إلى المجموعة {group_id}: {e}")
    
    except Exception as e:
        logger.error(f"خطأ في send_verification_codes: {e}")

# الوظيفة الرئيسية
async def main():
    """الوظيفة الرئيسية للسكريبت."""
    try:
        logger.info("بدء تشغيل سكريبت إرسال رموز المصادقة...")
        await send_verification_codes()
        logger.info("اكتمل إرسال رموز المصادقة.")
    except Exception as e:
        logger.error(f"خطأ في الوظيفة الرئيسية: {e}")

if __name__ == "__main__":
    # تشغيل الوظيفة الرئيسية
    asyncio.run(main())

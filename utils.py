#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف الوظائف المساعدة لبوت تليجرام للمصادقة 2FA
"""

import pyotp
import time
from datetime import datetime, timedelta
import pytz
import re

def generate_totp(secret):
    """توليد رمز TOTP من السر المقدم"""
    try:
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        print(f"خطأ في توليد رمز TOTP: {e}")
        return None

def get_next_update_time(interval, timezone_str="UTC", time_format="12"):
    """حساب وقت التحديث القادم"""
    try:
        # الحصول على الوقت الحالي في المنطقة الزمنية المحددة
        timezone = pytz.timezone(timezone_str)
        now = datetime.now(timezone)
        
        # حساب وقت التحديث القادم
        minutes_to_add = interval - (now.minute % interval)
        if minutes_to_add == interval:
            minutes_to_add = 0
        
        next_time = now + timedelta(minutes=minutes_to_add)
        next_time = next_time.replace(second=0, microsecond=0)
        
        # تنسيق الوقت حسب الصيغة المطلوبة
        if time_format == "12":
            time_str = next_time.strftime("%I:%M:%S %p")
        else:
            time_str = next_time.strftime("%H:%M:%S")
        
        return time_str
    except Exception as e:
        print(f"خطأ في حساب وقت التحديث القادم: {e}")
        return "??:??:??"

def is_valid_totp_secret(secret):
    """التحقق من صحة سر TOTP"""
    try:
        # محاولة إنشاء كائن TOTP للتحقق
        totp = pyotp.TOTP(secret)
        # محاولة توليد رمز للتأكد من عدم وجود أخطاء
        totp.now()
        return True
    except Exception:
        return False

def is_valid_group_id(group_id):
    """التحقق من صحة معرف المجموعة"""
    # معرفات المجموعات تبدأ بـ - وتتكون من أرقام فقط
    return bool(re.match(r'^-\d+$', str(group_id)))

def format_time_remaining(seconds):
    """تنسيق الوقت المتبقي"""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    if hours > 0:
        return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
    else:
        return f"{int(minutes):02d}:{int(seconds):02d}"

def is_midnight(timezone_str="UTC"):
    """التحقق مما إذا كان الوقت منتصف الليل"""
    timezone = pytz.timezone(timezone_str)
    now = datetime.now(timezone)
    return now.hour == 0 and now.minute == 0

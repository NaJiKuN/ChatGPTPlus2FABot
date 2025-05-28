#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف الإعدادات الخاص ببوت تليجرام للمصادقة 2FA
"""

import os
import json
from pathlib import Path

# المسار الأساسي للمشروع
BASE_DIR = Path(__file__).resolve().parent

# مسار ملف قاعدة البيانات
DB_PATH = os.path.join(BASE_DIR, "database.json")

# إعدادات البوت الأساسية
BOT_CONFIG = {
    "TOKEN": "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM",
    "ADMIN_IDS": ["764559466"],  # يمكن إضافة مسؤولين آخرين هنا
    "DEFAULT_INTERVAL": 10,  # الفترة الافتراضية لإرسال الرموز (بالدقائق)
    "DEFAULT_TIMEZONE": "Asia/Jerusalem",  # التوقيت الافتراضي (فلسطين)
    "DEFAULT_TIME_FORMAT": "12",  # صيغة الوقت الافتراضية (12 ساعة)
    "DEFAULT_ATTEMPTS": 3,  # عدد محاولات النسخ الافتراضية لكل مستخدم
}

# قوالب الرسائل
MESSAGE_TEMPLATES = {
    "header": "🔐 2FA Verification Code",
    "footer": "Next code at: {next_time}",
    "welcome": "مرحباً بك في بوت المصادقة 2FA!\nاستخدم الأمر /admin للوصول إلى لوحة التحكم.",
    "admin_welcome": "مرحباً بك في لوحة تحكم المسؤول",
    "group_id_request": "الرجاء إدخال معرف المجموعة الخاصة:",
    "totp_secret_request": "الرجاء إدخال TOTP_SECRET:",
    "success": "تمت العملية بنجاح!",
    "error": "حدث خطأ: {error}",
    "attempts_left": "عدد المحاولات المتبقية: {attempts}",
    "copy_button": "Copy Code",
    "no_permission": "ليس لديك صلاحية لاستخدام هذا الأمر.",
}

def load_config():
    """تحميل الإعدادات من الملف"""
    if not os.path.exists(DB_PATH):
        save_default_config()
    
    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"خطأ في تحميل الإعدادات: {e}")
        return save_default_config()

def save_default_config():
    """حفظ الإعدادات الافتراضية"""
    default_config = {
        "groups": {},  # معرفات المجموعات والإعدادات الخاصة بها
        "users": {},   # بيانات المستخدمين وعدد محاولات النسخ
        "settings": {  # إعدادات عامة
            "admin_ids": BOT_CONFIG["ADMIN_IDS"],
            "default_interval": BOT_CONFIG["DEFAULT_INTERVAL"],
            "default_timezone": BOT_CONFIG["DEFAULT_TIMEZONE"],
            "default_time_format": BOT_CONFIG["DEFAULT_TIME_FORMAT"],
            "default_attempts": BOT_CONFIG["DEFAULT_ATTEMPTS"],
        }
    }
    
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, ensure_ascii=False, indent=4)
    
    return default_config

def get_token():
    """الحصول على رمز البوت"""
    return BOT_CONFIG["TOKEN"]

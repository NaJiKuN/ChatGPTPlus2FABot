#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ChatGPTPlus2FABot - بوت تليجرام للمصادقة الثنائية 2FA
يقوم بإرسال رمز مصادقة ثنائية للمستخدمين بشكل دوري
(الإصدار مع التأكيدات وتخصيص المحاولات ودعم اللغات - مصحح)
"""

import os
import json
import time
import logging
import threading
import pyotp
import datetime
import asyncio
from dateutil import tz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ContextTypes, filters, ConversationHandler
)

# تكوين السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ثوابت البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM" # استبدل بالتوكن الخاص بك
ADMIN_ID = 764559466  # استبدل بمعرف المسؤول الرئيسي الخاص بك
DEFAULT_LANG = "ar" # اللغة الافتراضية

# حالات المحادثة (تم إضافة حالات إدارة اللغة)
(
    MAIN_MENU, MANAGE_GROUPS, ADD_GROUP, DELETE_GROUP, EDIT_GROUP,
    ADD_SECRET, EDIT_SECRET, MANAGE_INTERVAL,
    MANAGE_MESSAGE_STYLE, MANAGE_USER_ATTEMPTS, SELECT_GROUP_FOR_USER,
    SELECT_USER, MANAGE_USER, ADD_ATTEMPTS, REMOVE_ATTEMPTS,
    MANAGE_ADMINS, ADD_ADMIN, REMOVE_ADMIN,
    CONFIRM_ADD_GROUP, CONFIRM_DELETE_GROUP,
    CONFIRM_ADD_ADMIN, CONFIRM_REMOVE_ADMIN,
    SELECT_GROUP_FOR_DEFAULT_ATTEMPTS, SET_DEFAULT_ATTEMPTS,
    MANAGE_LANGUAGE, SELECT_LANGUAGE # حالات جديدة لإدارة اللغة
) = range(26) # تم تحديث العدد إلى 26

# ملفات البيانات
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
LANG_DIR = DATA_DIR # مجلد ملفات اللغة

# هيكل البيانات الافتراضي
DEFAULT_CONFIG = {
    "groups": {},  # {"group_id": {"totp_secret": "SECRET", "interval": 600, "message_style": 1, "timezone": "UTC", "default_attempts": 5}}
    "admins": [ADMIN_ID]
}

DEFAULT_USERS = {
    # "user_id": {"attempts": {"group_id": {"remaining": 5, "reset_date": "YYYY-MM-DD"}}, "banned": False, "username": "telegram_username", "language": "ar"}
}

# متغيرات عالمية للتحكم بالمهام الدورية والترجمة
scheduled_tasks = {}
stop_flags = {}
translations = {}

# --- وظائف إدارة البيانات واللغة ---
def load_translations():
    """تحميل ملفات الترجمة"""
    global translations
    translations = {}
    try:
        for filename in os.listdir(LANG_DIR):
            if filename.endswith(".json") and filename != "config.json" and filename != "users.json":
                lang_code = filename.split(".")[0]
                filepath = os.path.join(LANG_DIR, filename)
                try:
                    # تصحيح: استخدام علامات اقتباس صحيحة
                    with open(filepath, 'r', encoding='utf-8') as f:
                        translations[lang_code] = json.load(f)
                    logger.info(f"تم تحميل ملف اللغة: {filename}")
                except json.JSONDecodeError:
                    logger.error(f"خطأ في قراءة ملف اللغة {filename}. الملف تالف.")
                except Exception as e:
                    logger.error(f"خطأ غير متوقع عند تحميل ملف اللغة {filename}: {e}")
        if DEFAULT_LANG not in translations:
             logger.error(f"ملف اللغة الافتراضي ({DEFAULT_LANG}.json) غير موجود أو تالف. سيتم استخدام الإنجليزية كبديل إن وجدت.")
             if "en" not in translations:
                 logger.critical("لا يمكن العثور على ملفات لغة صالحة. لا يمكن للبوت العمل بدون ترجمة.")
                 # يمكن إضافة آلية للخروج أو استخدام قيم افتراضية بسيطة هنا
    except Exception as e:
        logger.error(f"خطأ في الوصول إلى مجلد اللغات {LANG_DIR}: {e}")

def get_user_language(user_id):
    """الحصول على لغة المستخدم"""
    users = load_users()
    return users.get(str(user_id), {}).get("language", DEFAULT_LANG)

def set_user_language(user_id, lang_code):
    """تعيين لغة المستخدم"""
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        users[user_id_str] = DEFAULT_USERS.get(user_id_str, {"language": lang_code, "attempts": {}, "banned": False, "username": "Unknown"})
    else:
        users[user_id_str]["language"] = lang_code
    save_users(users)

def _(user_id, key, **kwargs):
    """الحصول على النص المترجم"""
    lang_code = get_user_language(user_id)
    # محاولة الحصول على الترجمة باللغة المحددة
    lang_dict = translations.get(lang_code)
    if lang_dict and key in lang_dict:
        try:
            return lang_dict[key].format(**kwargs)
        except KeyError as e:
            # تصحيح: استخدام علامات اقتباس صحيحة
            logger.warning(f"المفتاح '{e}' غير موجود في الوسائط للنص '{key}' باللغة {lang_code}")
            return lang_dict[key] # إرجاع النص بدون تنسيق
        except Exception as e:
             # تصحيح: استخدام علامات اقتباس صحيحة
             logger.error(f"خطأ في تنسيق النص '{key}' باللغة {lang_code}: {e}")
             return f"ErrorFormatting:{key}"

    # إذا فشل، محاولة استخدام اللغة الافتراضية
    # تصحيح: استخدام علامات اقتباس صحيحة
    logger.warning(f"المفتاح '{key}' غير موجود في اللغة {lang_code}. محاولة اللغة الافتراضية {DEFAULT_LANG}.")
    lang_dict = translations.get(DEFAULT_LANG)
    if lang_dict and key in lang_dict:
        try:
            return lang_dict[key].format(**kwargs)
        except KeyError as e:
            # تصحيح: استخدام علامات اقتباس صحيحة
            logger.warning(f"المفتاح '{e}' غير موجود في الوسائط للنص '{key}' باللغة الافتراضية {DEFAULT_LANG}")
            return lang_dict[key]
        except Exception as e:
             # تصحيح: استخدام علامات اقتباس صحيحة
             logger.error(f"خطأ في تنسيق النص '{key}' باللغة الافتراضية {DEFAULT_LANG}: {e}")
             return f"ErrorFormatting:{key}"

    # إذا فشل، محاولة استخدام الإنجليزية كحل أخير
    # تصحيح: استخدام علامات اقتباس صحيحة
    logger.warning(f"المفتاح '{key}' غير موجود في اللغة الافتراضية {DEFAULT_LANG}. محاولة اللغة الإنجليزية.")
    lang_dict = translations.get("en")
    if lang_dict and key in lang_dict:
        try:
            return lang_dict[key].format(**kwargs)
        except KeyError as e:
            # تصحيح: استخدام علامات اقتباس صحيحة
            logger.warning(f"المفتاح '{e}' غير موجود في الوسائط للنص '{key}' باللغة الإنجليزية")
            return lang_dict[key]
        except Exception as e:
             # تصحيح: استخدام علامات اقتباس صحيحة
             logger.error(f"خطأ في تنسيق النص '{key}' باللغة الإنجليزية: {e}")
             return f"ErrorFormatting:{key}"

    # إذا فشل كل شيء
    # تصحيح: استخدام علامات اقتباس صحيحة
    logger.error(f"المفتاح '{key}' غير موجود في أي لغة متاحة.")
    return f"MissingTranslation:{key}"

def load_config():
    """تحميل ملف الإعدادات والتأكد من وجود default_attempts"""
    if os.path.exists(CONFIG_FILE):
        try:
            # تصحيح: استخدام علامات اقتباس صحيحة
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if "admins" not in config: config["admins"] = [ADMIN_ID]
                config_changed = False
                if "groups" in config and isinstance(config["groups"], dict):
                    for group_id in config["groups"]:
                        if "default_attempts" not in config["groups"][group_id]:
                            config["groups"][group_id]["default_attempts"] = 5
                            config_changed = True
                        elif not isinstance(config["groups"][group_id]["default_attempts"], int) or config["groups"][group_id]["default_attempts"] < 0:
                             logger.warning(f"قيمة default_attempts غير صالحة للمجموعة {group_id}. سيتم تعيينها إلى 5.")
                             config["groups"][group_id]["default_attempts"] = 5
                             config_changed = True
                else: config["groups"] = {}
                if config_changed: save_config(config)
                return config
        except json.JSONDecodeError:
            logger.error(f"خطأ في قراءة ملف الإعدادات {CONFIG_FILE}. سيتم استخدام الإعدادات الافتراضية.")
            # تصحيح: استخدام علامات اقتباس صحيحة
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"خطأ غير متوقع عند تحميل الإعدادات: {e}. سيتم استخدام الإعدادات الافتراضية.")
            return DEFAULT_CONFIG
    else:
        # تصحيح: استخدام علامات اقتباس صحيحة
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
        return DEFAULT_CONFIG

def save_config(config):
    """حفظ ملف الإعدادات"""
    try:
        # تصحيح: استخدام علامات اقتباس صحيحة
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e: logger.error(f"فشل حفظ ملف الإعدادات {CONFIG_FILE}: {e}")

def load_users():
    """تحميل بيانات المستخدمين والتأكد من وجود مفتاح اللغة"""
    if os.path.exists(USERS_FILE):
        try:
            # تصحيح: استخدام علامات اقتباس صحيحة
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
                # التأكد من وجود مفتاح اللغة لكل مستخدم
                users_changed = False
                for user_id in users:
                    if "language" not in users[user_id]:
                        users[user_id]["language"] = DEFAULT_LANG
                        users_changed = True
                if users_changed: save_users(users)
                return users
        except json.JSONDecodeError:
             logger.error(f"خطأ في قراءة ملف المستخدمين {USERS_FILE}. سيتم استخدام البيانات الافتراضية.")
             # تصحيح: استخدام علامات اقتباس صحيحة
             with open(USERS_FILE, 'w', encoding='utf-8') as f: json.dump(DEFAULT_USERS, f, ensure_ascii=False, indent=4)
             return DEFAULT_USERS
        except Exception as e:
             logger.error(f"خطأ غير متوقع عند تحميل المستخدمين: {e}. سيتم استخدام البيانات الافتراضية.")
             return DEFAULT_USERS
    else:
        # تصحيح: استخدام علامات اقتباس صحيحة
        with open(USERS_FILE, 'w', encoding='utf-8') as f: json.dump(DEFAULT_USERS, f, ensure_ascii=False, indent=4)
        return DEFAULT_USERS

def save_users(users):
    """حفظ بيانات المستخدمين"""
    try:
        # تصحيح: استخدام علامات اقتباس صحيحة
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
    except Exception as e: logger.error(f"فشل حفظ ملف المستخدمين {USERS_FILE}: {e}")

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً"""
    config = load_config()
    admins_list = config.get("admins", [])
    if not isinstance(admins_list, list): admins_list = [ADMIN_ID]
    return user_id in admins_list

# --- وظائف الوقت والتنسيق (مع إصلاح الترجمة) ---
def get_time_format(timezone_name="UTC"):
    try:
        timezone = tz.gettz(timezone_name)
        if timezone is None: timezone = tz.gettz("UTC")
    except Exception as e: timezone = tz.gettz("UTC")
    now = datetime.datetime.now(timezone)
    return now.strftime("%I:%M:%S %p")

def get_next_time(interval_seconds, timezone_name="UTC"):
    try:
        timezone = tz.gettz(timezone_name)
        if timezone is None: timezone = tz.gettz("UTC")
    except Exception as e: timezone = tz.gettz("UTC")
    now = datetime.datetime.now(timezone)
    next_time = now + datetime.timedelta(seconds=interval_seconds)
    return next_time.strftime("%I:%M:%S %p")

def format_interval(user_id, seconds):
    """تنسيق الفاصل الزمني باستخدام لغة المستخدم ومفاتيح الترجمة"""
    if seconds < 60:
        # تصحيح: استخدام علامات اقتباس صحيحة
        return f"{seconds} {_(user_id, 'interval_seconds')}"
    elif seconds < 3600:
        minutes = seconds // 60
        # تصحيح: استخدام علامات اقتباس صحيحة
        key = 'interval_minute' if minutes == 1 else 'interval_minutes'
        return f"{minutes} {_(user_id, key)}"
    elif seconds < 86400:
        hours = seconds // 3600
        # تصحيح: استخدام علامات اقتباس صحيحة
        key = 'interval_hour' if hours == 1 else 'interval_hours'
        return f"{hours} {_(user_id, key)}"
    else:
        days = seconds // 86400
        # تصحيح: استخدام علامات اقتباس صحيحة
        key = 'interval_day' if days == 1 else 'interval_days'
        return f"{days} {_(user_id, key)}"

def get_remaining_validity(totp):
    try: return totp.interval - (int(time.time()) % totp.interval)
    except Exception as e: logger.error(f"خطأ في حساب صلاحية الرمز: {e}"); return 30

# --- وظائف البوت الأساسية (مع الترجمة) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    # تسجيل المستخدم وتعيين اللغة الافتراضية إذا لم يكن موجوداً
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {"language": DEFAULT_LANG, "attempts": {}, "banned": False, "username": user.username or f"{user.first_name} (No Username)"}
        save_users(users)
        # يمكن إضافة رسالة ترحيب خاصة للمستخدم الجديد أو سؤال عن اللغة هنا
    
    await update.message.reply_text(_(user_id, "welcome_message", name=user.first_name))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(_(user_id, "admin_only_command"))
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton(_(user_id, "manage_groups_button"), callback_data="manage_groups")],
        [InlineKeyboardButton(_(user_id, "manage_interval_button"), callback_data="manage_interval")],
        [InlineKeyboardButton(_(user_id, "manage_style_button"), callback_data="manage_message_style")],
        [InlineKeyboardButton(_(user_id, "manage_attempts_button"), callback_data="manage_user_attempts")],
        [InlineKeyboardButton(_(user_id, "manage_admins_button"), callback_data="manage_admins")],
        [InlineKeyboardButton(_(user_id, "manage_language_button"), callback_data="manage_language")], # زر إدارة اللغة
        [InlineKeyboardButton(_(user_id, "cancel_button"), callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = _(user_id, "admin_panel_welcome")
    if update.callback_query:
        try: await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except Exception as e: 
            logger.warning(f"فشل تعديل رسالة لوحة الإدارة: {e}. محاولة إرسال رسالة جديدة.")
            # في حالة فشل التعديل (مثل انتهاء صلاحية الاستعلام)، أرسل رسالة جديدة
            await update.effective_message.reply_text(text, reply_markup=reply_markup)
    else: 
        # إصلاح: إضافة await هنا
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    return MAIN_MENU

# --- وظائف إدارة المجموعات (مع الترجمة والتأكيد) ---
async def manage_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(_(user_id, "add_group_button"), callback_data="add_group")],
        [InlineKeyboardButton(_(user_id, "delete_group_button"), callback_data="delete_group")],
        [InlineKeyboardButton(_(user_id, "edit_secret_button"), callback_data="edit_group")],
        [InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "manage_groups_menu_title"), reply_markup=reply_markup)
    return MANAGE_GROUPS

# --- إضافة مجموعة (مع الترجمة والتأكيد) ---
async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    await query.edit_message_text(_(user_id, "add_group_prompt"))
    return ADD_GROUP

async def process_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group_id = update.message.text.strip()
    if not group_id.startswith("-100") or not group_id[1:].isdigit():
        await update.message.reply_text(_(user_id, "invalid_group_id"))
        return ADD_GROUP
    
    config = load_config()
    if group_id in config.get("groups", {}):
         await update.message.reply_text(_(user_id, "group_already_exists", group_id=group_id))
         return ADD_GROUP

    context.user_data["group_id"] = group_id
    await update.message.reply_text(_(user_id, "group_id_saved"))
    return ADD_SECRET

async def process_add_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("group_id")
    try: pyotp.TOTP(totp_secret).now()
    except Exception as e:
        await update.message.reply_text(_(user_id, "invalid_totp_secret", error=str(e)))
        return ADD_SECRET
    
    context.user_data["totp_secret"] = totp_secret
    keyboard = [
        [InlineKeyboardButton(_(user_id, "confirm_add_group_yes"), callback_data="confirm_add_group_yes")],
        [InlineKeyboardButton(_(user_id, "confirm_add_group_no"), callback_data="manage_groups")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(_(user_id, "confirm_add_group_prompt", group_id=group_id), reply_markup=reply_markup)
    return CONFIRM_ADD_GROUP

async def execute_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = context.user_data.get("group_id")
    totp_secret = context.user_data.get("totp_secret")
    
    if not group_id or not totp_secret:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    config = load_config()
    if "groups" not in config or not isinstance(config["groups"], dict): config["groups"] = {}
        
    config["groups"][group_id] = {"totp_secret": totp_secret, "interval": 600, "message_style": 1, "timezone": "UTC", "default_attempts": 5}
    save_config(config)
    await start_periodic_task(context.application, group_id)
    
    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_groups_button"), callback_data="manage_groups")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "add_group_success", group_id=group_id), reply_markup=reply_markup)
    
    context.user_data.pop("group_id", None)
    context.user_data.pop("totp_secret", None)
    return MAIN_MENU

# --- حذف مجموعة (مع الترجمة والتأكيد) ---
async def delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    groups = config.get("groups", {})
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_groups")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_to_delete"), reply_markup=reply_markup)
        return MANAGE_GROUPS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(_(user_id, "group_button_format", group_id=group_id), callback_data=f"confirm_del_group_{group_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_groups")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_group_to_delete"), reply_markup=reply_markup)
    return DELETE_GROUP

async def confirm_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = query.data.replace("confirm_del_group_", "")
    context.user_data["delete_group_id"] = group_id
    keyboard = [
        [InlineKeyboardButton(_(user_id, "confirm_delete_group_yes"), callback_data="execute_del_group_yes")],
        [InlineKeyboardButton(_(user_id, "confirm_delete_group_no"), callback_data="manage_groups")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "confirm_delete_group_prompt", group_id=group_id), reply_markup=reply_markup)
    return CONFIRM_DELETE_GROUP

async def execute_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = context.user_data.get("delete_group_id")
    if not group_id:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    await stop_periodic_task(context.application, group_id)
    config = load_config()
    message = ""
    if "groups" in config and group_id in config["groups"]:
        del config["groups"][group_id]
        save_config(config)
        users = load_users()
        users_changed = False
        for user_id_str in list(users.keys()):
            if "attempts" in users[user_id_str] and group_id in users[user_id_str]["attempts"]:
                del users[user_id_str]["attempts"][group_id]
                users_changed = True
                if not users[user_id_str]["attempts"]: del users[user_id_str]["attempts"]
        if users_changed: save_users(users)
        message = _(user_id, "delete_group_success", group_id=group_id)
    else: message = _(user_id, "group_not_found_or_deleted", group_id=group_id)

    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_groups_button"), callback_data="manage_groups")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    context.user_data.pop("delete_group_id", None)
    return MAIN_MENU

# --- تعديل TOTP Secret (مع الترجمة) ---
async def edit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    groups = config.get("groups", {})
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_groups")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_to_edit"), reply_markup=reply_markup)
        return MANAGE_GROUPS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(_(user_id, "group_button_format", group_id=group_id), callback_data=f"edit_group_{group_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_groups")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_group_to_edit_secret"), reply_markup=reply_markup)
    return EDIT_GROUP

async def process_edit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = query.data.replace("edit_group_", "")
    context.user_data["edit_group_id"] = group_id
    await query.edit_message_text(_(user_id, "enter_new_secret_prompt", group_id=group_id))
    return EDIT_SECRET

async def process_edit_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("edit_group_id")
    try: pyotp.TOTP(totp_secret).now()
    except Exception as e:
        await update.message.reply_text(_(user_id, "invalid_totp_secret", error=str(e)))
        return EDIT_SECRET
    
    config = load_config()
    message = ""
    if "groups" in config and group_id in config["groups"]:
        config["groups"][group_id]["totp_secret"] = totp_secret
        save_config(config)
        message = _(user_id, "edit_secret_success", group_id=group_id)
        if group_id in scheduled_tasks:
            await stop_periodic_task(context.application, group_id)
            await start_periodic_task(context.application, group_id)
    else: message = _(user_id, "group_not_found", group_id=group_id)

    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_groups_button"), callback_data="manage_groups")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)
    context.user_data.pop("edit_group_id", None)
    return MAIN_MENU

# --- وظائف إدارة فترة التكرار (مع الترجمة) ---
async def manage_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    groups = config.get("groups", {})
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_for_interval"), reply_markup=reply_markup)
        return MAIN_MENU
    
    keyboard = []
    for group_id, group_data in groups.items():
        interval = group_data.get("interval", 600)
        # إصلاح: استخدام user_id لتنسيق الفاصل الزمني
        interval_text = format_interval(user_id, interval)
        keyboard.append([InlineKeyboardButton(_(user_id, "group_interval_button_format", group_id=group_id, interval_text=interval_text), callback_data=f"interval_{group_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_group_for_interval"), reply_markup=reply_markup)
    return MANAGE_INTERVAL

async def process_manage_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = query.data.replace("interval_", "")
    context.user_data["interval_group_id"] = group_id
    keyboard = [
        [InlineKeyboardButton(_(user_id, "interval_1_min"), callback_data="set_interval_60"), InlineKeyboardButton(_(user_id, "interval_5_min"), callback_data="set_interval_300")],
        [InlineKeyboardButton(_(user_id, "interval_10_min"), callback_data="set_interval_600"), InlineKeyboardButton(_(user_id, "interval_15_min"), callback_data="set_interval_900")],
        [InlineKeyboardButton(_(user_id, "interval_30_min"), callback_data="set_interval_1800"), InlineKeyboardButton(_(user_id, "interval_1_hour"), callback_data="set_interval_3600")],
        [InlineKeyboardButton(_(user_id, "interval_3_hours"), callback_data="set_interval_10800"), InlineKeyboardButton(_(user_id, "interval_12_hours"), callback_data="set_interval_43200")],
        [InlineKeyboardButton(_(user_id, "interval_24_hours"), callback_data="set_interval_86400")],
        [InlineKeyboardButton(_(user_id, "interval_stop"), callback_data="set_interval_0")],
        [InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_interval")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    config = load_config()
    current_interval = config.get("groups", {}).get(group_id, {}).get("interval", 600)
    # إصلاح: استخدام user_id لتنسيق الفاصل الزمني
    interval_status = _(user_id, "interval_status_stopped") if current_interval <= 0 else f"{format_interval(user_id, current_interval)} ✅"
    await query.edit_message_text(
        _(user_id, "select_new_interval_prompt", group_id=group_id, interval_status=interval_status),
        reply_markup=reply_markup
    )
    return MANAGE_INTERVAL

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = context.user_data.get("interval_group_id")
    if not group_id:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    try: interval = int(query.data.replace("set_interval_", ""))
    except ValueError:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_to_manage_interval_button"), callback_data="manage_interval")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "invalid_selection"), reply_markup=reply_markup)
        return MANAGE_INTERVAL

    config = load_config()
    message = ""
    if "groups" in config and group_id in config["groups"]:
        config["groups"][group_id]["interval"] = interval
        save_config(config)
        await stop_periodic_task(context.application, group_id)
        if interval > 0:
            await start_periodic_task(context.application, group_id)
            # إصلاح: استخدام user_id لتنسيق الفاصل الزمني
            message = _(user_id, "set_interval_success", group_id=group_id, interval_text=format_interval(user_id, interval))
        else: message = _(user_id, "stop_interval_success", group_id=group_id)
    else: message = _(user_id, "group_not_found", group_id=group_id)

    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_interval_button"), callback_data="manage_interval")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    context.user_data.pop("interval_group_id", None)
    return MAIN_MENU

# --- وظائف إدارة شكل الرسالة (مع الترجمة) ---
async def manage_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    groups = config.get("groups", {})
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_for_style"), reply_markup=reply_markup)
        return MAIN_MENU
    
    keyboard = []
    for group_id, group_data in groups.items():
        style = group_data.get("message_style", 1)
        timezone = group_data.get("timezone", "UTC")
        keyboard.append([InlineKeyboardButton(_(user_id, "group_style_button_format", group_id=group_id, style=style, timezone=timezone), callback_data=f"style_{group_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_group_for_style"), reply_markup=reply_markup)
    return MANAGE_MESSAGE_STYLE

async def process_manage_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = query.data.replace("style_", "")
    context.user_data["style_group_id"] = group_id
    # أمثلة الأنماط (يمكن جعلها قابلة للترجمة أيضاً إذا لزم الأمر)
    style1_example = "🔐 2FA Verification Code\n\nNext code at: HH:MM:SS AM/PM"
    style2_example = "🔐 2FA Verification Code\n\nNext code in: X minutes\n\nNext code at: HH:MM:SS AM/PM"
    style3_example = "🔐 2FA Verification Code\nNext code in: X minutes\nCorrect Time: HH:MM:SS AM/PM\nNext Code at: HH:MM:SS AM/PM"
    keyboard = [
        [InlineKeyboardButton(_(user_id, "style1_button"), callback_data="set_style_1")],
        [InlineKeyboardButton(_(user_id, "style2_button"), callback_data="set_style_2")],
        [InlineKeyboardButton(_(user_id, "style3_button"), callback_data="set_style_3")],
        [InlineKeyboardButton(_(user_id, "timezone_utc_button"), callback_data="set_timezone_UTC")],
        [InlineKeyboardButton(_(user_id, "timezone_gaza_button"), callback_data="set_timezone_Asia/Gaza")],
        [InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_message_style")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    config = load_config()
    current_style = config.get("groups", {}).get(group_id, {}).get("message_style", 1)
    current_timezone = config.get("groups", {}).get(group_id, {}).get("timezone", "UTC")
    await query.edit_message_text(
        _(user_id, "select_new_style_prompt", group_id=group_id, style=current_style, timezone=current_timezone, style1_example=style1_example, style2_example=style2_example, style3_example=style3_example),
        reply_markup=reply_markup
    )
    return MANAGE_MESSAGE_STYLE

async def set_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = context.user_data.get("style_group_id")
    if not group_id:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    config = load_config()
    message = ""
    style_changed = False
    
    if query.data.startswith("set_style_"):
        try:
            style = int(query.data.replace("set_style_", ""))
            if "groups" in config and group_id in config["groups"]:
                config["groups"][group_id]["message_style"] = style
                save_config(config)
                message = _(user_id, "set_style_success", group_id=group_id, style=style)
                style_changed = True
            else: message = _(user_id, "group_not_found", group_id=group_id)
        except ValueError: message = _(user_id, "invalid_style_selection")
             
    elif query.data.startswith("set_timezone_"):
        timezone = query.data.replace("set_timezone_", "")
        try: tz.gettz(timezone)
        except Exception:
             keyboard = [[InlineKeyboardButton(_(user_id, "back_to_manage_style_button"), callback_data="manage_message_style")]]
             reply_markup = InlineKeyboardMarkup(keyboard)
             await query.edit_message_text(_(user_id, "invalid_timezone", timezone=timezone), reply_markup=reply_markup)
             return MANAGE_MESSAGE_STYLE
             
        if "groups" in config and group_id in config["groups"]:
            config["groups"][group_id]["timezone"] = timezone
            save_config(config)
            message = _(user_id, "set_timezone_success", group_id=group_id, timezone=timezone)
            style_changed = True
        else: message = _(user_id, "group_not_found", group_id=group_id)
    else: message = _(user_id, "invalid_selection")

    if style_changed:
        context.user_data.pop("style_group_id", None)
        keyboard = [
            [InlineKeyboardButton(_(user_id, "back_to_manage_style_button"), callback_data="manage_message_style")],
            [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)
        return MAIN_MENU
    else:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_to_manage_style_button"), callback_data="manage_message_style")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)
        return MANAGE_MESSAGE_STYLE

# --- وظائف إدارة محاولات المستخدمين (مع الترجمة) ---
async def manage_user_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton(_(user_id, "edit_user_attempts_button"), callback_data="select_group_for_user")],
        [InlineKeyboardButton(_(user_id, "set_group_default_attempts_button"), callback_data="select_group_default_attempts")],
        [InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "manage_user_attempts_menu_title"), reply_markup=reply_markup)
    
    return MANAGE_USER_ATTEMPTS

# --- تحديد العدد الافتراضي للمحاولات لمجموعة (مع الترجمة) --- 
async def select_group_for_default_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_user_attempts")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_for_default_attempts"), reply_markup=reply_markup)
        return MANAGE_USER_ATTEMPTS
    
    keyboard = []
    for group_id, group_data in groups.items():
        default_attempts = group_data.get("default_attempts", 5)
        keyboard.append([InlineKeyboardButton(_(user_id, "group_default_attempts_button_format", group_id=group_id, default_attempts=default_attempts), callback_data=f"set_default_attempts_{group_id}")])
    
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_user_attempts")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(_(user_id, "select_group_for_default_attempts"), reply_markup=reply_markup)
    
    return SELECT_GROUP_FOR_DEFAULT_ATTEMPTS

async def request_new_default_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    group_id = query.data.replace("set_default_attempts_", "")
    context.user_data["default_attempts_group_id"] = group_id
    
    config = load_config()
    current_default = config.get("groups", {}).get(group_id, {}).get("default_attempts", 5)
    
    await query.edit_message_text(_(user_id, "request_new_default_attempts_prompt", group_id=group_id, current_default=current_default))
    
    return SET_DEFAULT_ATTEMPTS

async def process_set_default_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        new_default_attempts = int(update.message.text.strip())
        if new_default_attempts < 0: raise ValueError("Must be >= 0")
    except ValueError:
        await update.message.reply_text(_(user_id, "invalid_default_attempts_input"))
        return SET_DEFAULT_ATTEMPTS
    
    group_id = context.user_data.get("default_attempts_group_id")
    
    if not group_id:
        await update.message.reply_text(_(user_id, "generic_error"))
        return ConversationHandler.END
        
    config = load_config()
    message = ""
    
    if "groups" in config and group_id in config["groups"]:
        config["groups"][group_id]["default_attempts"] = new_default_attempts
        save_config(config)
        message = _(user_id, "set_default_attempts_success", group_id=group_id, new_default_attempts=new_default_attempts)
    else: message = _(user_id, "group_not_found", group_id=group_id)
    
    await update.message.reply_text(message)
    await asyncio.sleep(1)
    
    context.user_data.pop("default_attempts_group_id", None)
    
    keyboard = [[InlineKeyboardButton(_(user_id, "back_to_select_group_default_attempts_button"), callback_data="select_group_default_attempts")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # إصلاح: إضافة await هنا
    await update.message.reply_text(_(user_id, "press_to_go_back"), reply_markup=reply_markup)
    
    return SELECT_GROUP_FOR_DEFAULT_ATTEMPTS

# --- تعديل محاولات مستخدم معين (مع الترجمة) ---
async def select_group_for_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    groups = config.get("groups", {})
    if not groups:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_user_attempts")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_groups_for_user_attempts"), reply_markup=reply_markup)
        return MANAGE_USER_ATTEMPTS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(_(user_id, "group_button_format", group_id=group_id), callback_data=f"select_users_{group_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_user_attempts")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_group_for_user_attempts"), reply_markup=reply_markup)
    return SELECT_GROUP_FOR_USER

async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    group_id = query.data.replace("select_users_", "")
    context.user_data["attempts_group_id"] = group_id
    users = load_users()
    group_users = {}
    for user_id_str, user_data in users.items():
        if "attempts" in user_data and group_id in user_data["attempts"]:
            group_users[user_id_str] = user_data
    
    if not group_users:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_to_select_group_for_user_button"), callback_data="select_group_for_user")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "no_users_in_group"), reply_markup=reply_markup)
        return SELECT_GROUP_FOR_USER
    
    keyboard = []
    for user_id_str, user_data in group_users.items():
        remaining = user_data["attempts"][group_id]["remaining"]
        username = user_data.get("username", f"ID: {user_id_str}")
        keyboard.append([InlineKeyboardButton(
            _(user_id, "user_attempts_button_format", username=username, remaining=remaining),
            callback_data=f"manage_user_{user_id_str}"
        )])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_to_select_group_for_user_button"), callback_data="select_group_for_user")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_user_for_attempts"), reply_markup=reply_markup)
    return SELECT_USER

async def manage_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user_id = query.from_user.id
    await query.answer()
    target_user_id = query.data.replace("manage_user_", "")
    context.user_data["attempts_user_id"] = target_user_id
    group_id = context.user_data.get("attempts_group_id")
    users = load_users()
    
    if target_user_id in users and "attempts" in users[target_user_id] and group_id in users[target_user_id]["attempts"]:
        user_data = users[target_user_id]
        group_attempts = user_data["attempts"][group_id]
        remaining = group_attempts["remaining"]
        reset_date = group_attempts["reset_date"]
        banned = user_data.get("banned", False)
        username = user_data.get("username", f"ID: {target_user_id}")
        status = _(admin_user_id, "user_status_banned") if banned else _(admin_user_id, "user_status_active")
        ban_button_text = _(admin_user_id, "unban_user_button") if banned else _(admin_user_id, "ban_user_button")
        keyboard = [
            [InlineKeyboardButton(_(admin_user_id, "add_attempts_button"), callback_data="add_attempts")],
            [InlineKeyboardButton(_(admin_user_id, "remove_attempts_button"), callback_data="remove_attempts")],
            [InlineKeyboardButton(ban_button_text, callback_data="toggle_ban")],
            [InlineKeyboardButton(_(admin_user_id, "back_to_select_user_button"), callback_data=f"select_users_{group_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            _(admin_user_id, "manage_user_prompt", username=username, group_id=group_id, remaining=remaining, reset_date=reset_date, status=status),
            reply_markup=reply_markup
        )
        return MANAGE_USER
    else:
        keyboard = [[InlineKeyboardButton(_(admin_user_id, "back_to_select_user_button"), callback_data=f"select_users_{group_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(admin_user_id, "user_data_not_found"), reply_markup=reply_markup)
        return SELECT_USER

async def toggle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user_id = query.from_user.id
    await query.answer()
    target_user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    if not target_user_id or not group_id:
        await query.edit_message_text(_(admin_user_id, "generic_error"))
        return await admin_command(update, context)
        
    users = load_users()
    message = ""
    if target_user_id in users:
        current_ban = users[target_user_id].get("banned", False)
        users[target_user_id]["banned"] = not current_ban
        save_users(users)
        username = users[target_user_id].get("username", target_user_id)
        message = _(admin_user_id, "user_banned_message", username=username, user_id=target_user_id) if not current_ban else _(admin_user_id, "user_unbanned_message", username=username, user_id=target_user_id)
    else: message = _(admin_user_id, "user_not_found", user_id=target_user_id)
    
    await query.edit_message_text(message)
    await asyncio.sleep(1)
    query.data = f"manage_user_{target_user_id}" 
    return await manage_user(update, context)

async def add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user_id = query.from_user.id
    await query.answer()
    target_user_id = context.user_data.get("attempts_user_id")
    users = load_users()
    username = users.get(target_user_id, {}).get("username", target_user_id)
    await query.edit_message_text(_(admin_user_id, "add_attempts_prompt", username=username, user_id=target_user_id))
    return ADD_ATTEMPTS

async def process_add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_user_id = update.effective_user.id
    try:
        attempts_to_add = int(update.message.text.strip())
        if attempts_to_add <= 0: raise ValueError("Must be positive")
    except ValueError:
        await update.message.reply_text(_(admin_user_id, "invalid_positive_integer"))
        return ADD_ATTEMPTS
    
    target_user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    if not target_user_id or not group_id:
        await update.message.reply_text(_(admin_user_id, "generic_error"))
        return ConversationHandler.END
        
    users = load_users()
    message = ""
    today = datetime.date.today().isoformat()
    if target_user_id not in users: users[target_user_id] = {"attempts": {}, "banned": False, "username": "Unknown", "language": DEFAULT_LANG}
    if "attempts" not in users[target_user_id]: users[target_user_id]["attempts"] = {}
    if group_id not in users[target_user_id]["attempts"]:
        config = load_config()
        default_attempts = config.get("groups", {}).get(group_id, {}).get("default_attempts", 5)
        users[target_user_id]["attempts"][group_id] = {"remaining": 0, "reset_date": today}
        
    users[target_user_id]["attempts"][group_id]["remaining"] += attempts_to_add
    users[target_user_id]["attempts"][group_id]["reset_date"] = today
    save_users(users)
    username = users[target_user_id].get("username", target_user_id)
    new_total = users[target_user_id]["attempts"][group_id]["remaining"]
    message = _(admin_user_id, "add_attempts_success", added_count=attempts_to_add, username=username, user_id=target_user_id, new_total=new_total)
    
    await update.message.reply_text(message)
    await asyncio.sleep(1)
    keyboard = [[InlineKeyboardButton(_(admin_user_id, "back_to_manage_user_button"), callback_data=f"manage_user_{target_user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # إصلاح: إضافة await هنا
    await update.message.reply_text(_(admin_user_id, "press_to_go_back"), reply_markup=reply_markup)
    return MANAGE_USER

async def remove_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user_id = query.from_user.id
    await query.answer()
    target_user_id = context.user_data.get("attempts_user_id")
    users = load_users()
    username = users.get(target_user_id, {}).get("username", target_user_id)
    await query.edit_message_text(_(admin_user_id, "remove_attempts_prompt", username=username, user_id=target_user_id))
    return REMOVE_ATTEMPTS

async def process_remove_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_user_id = update.effective_user.id
    try:
        attempts_to_remove = int(update.message.text.strip())
        if attempts_to_remove <= 0: raise ValueError("Must be positive")
    except ValueError:
        await update.message.reply_text(_(admin_user_id, "invalid_positive_integer"))
        return REMOVE_ATTEMPTS
    
    target_user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    if not target_user_id or not group_id:
        await update.message.reply_text(_(admin_user_id, "generic_error"))
        return ConversationHandler.END
        
    users = load_users()
    message = ""
    today = datetime.date.today().isoformat()
    if (target_user_id in users and "attempts" in users[target_user_id] and group_id in users[target_user_id]["attempts"]):
        current = users[target_user_id]["attempts"][group_id]["remaining"]
        removed_count = min(attempts_to_remove, current)
        users[target_user_id]["attempts"][group_id]["remaining"] = max(0, current - attempts_to_remove)
        users[target_user_id]["attempts"][group_id]["reset_date"] = today
        save_users(users)
        username = users[target_user_id].get("username", target_user_id)
        new_total = users[target_user_id]["attempts"][group_id]["remaining"]
        message = _(admin_user_id, "remove_attempts_success", removed_count=removed_count, username=username, user_id=target_user_id, new_total=new_total)
    else: message = _(admin_user_id, "user_attempts_not_found", user_id=target_user_id, group_id=group_id)
    
    await update.message.reply_text(message)
    await asyncio.sleep(1)
    keyboard = [[InlineKeyboardButton(_(admin_user_id, "back_to_manage_user_button"), callback_data=f"manage_user_{target_user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # إصلاح: إضافة await هنا
    await update.message.reply_text(_(admin_user_id, "press_to_go_back"), reply_markup=reply_markup)
    return MANAGE_USER

# --- وظائف إدارة المسؤولين (مع الترجمة والتأكيد) ---
async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(_(user_id, "add_admin_button"), callback_data="add_admin")],
        [InlineKeyboardButton(_(user_id, "remove_admin_button"), callback_data="remove_admin")],
        [InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    config = load_config()
    admins = config.get("admins", [ADMIN_ID])
    admins_text = ""
    users = load_users()
    for admin_id in admins:
        admin_id_str = str(admin_id)
        username = users.get(admin_id_str, {}).get("username", f"ID: {admin_id}")
        is_main_admin = _(user_id, "admin_list_main_suffix") if admin_id == ADMIN_ID else ""
        admins_text += _(user_id, "admin_list_item_format", username=username, is_main=is_main_admin) + "\n"
    if not admins_text: admins_text = _(user_id, "no_admins_found")
    await query.edit_message_text(
        _(user_id, "manage_admins_menu_title", admins_list=admins_text.strip()),
        reply_markup=reply_markup
    )
    return MANAGE_ADMINS

# --- إضافة مسؤول (مع الترجمة والتأكيد) ---
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    await query.edit_message_text(_(user_id, "add_admin_prompt"))
    return ADD_ADMIN

async def process_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try: admin_id_to_add = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(_(user_id, "invalid_user_id"))
        return ADD_ADMIN
    
    config = load_config()
    admins_list = config.get("admins", [])
    if not isinstance(admins_list, list): admins_list = [ADMIN_ID]
        
    if admin_id_to_add in admins_list:
        await update.message.reply_text(_(user_id, "user_already_admin", admin_id=admin_id_to_add))
        keyboard = [[InlineKeyboardButton(_(user_id, "back_to_manage_admins_button"), callback_data="manage_admins")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # إصلاح: إضافة await هنا
        await update.message.reply_text(_(user_id, "press_to_go_back"), reply_markup=reply_markup)
        return MANAGE_ADMINS
    else:
        context.user_data["add_admin_id"] = admin_id_to_add
        keyboard = [
            [InlineKeyboardButton(_(user_id, "confirm_add_admin_yes"), callback_data="confirm_add_admin_yes")],
            [InlineKeyboardButton(_(user_id, "confirm_add_admin_no"), callback_data="manage_admins")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        username_info = ""
        try:
            chat = await context.bot.get_chat(admin_id_to_add)
            if chat.username: username_info = f" (@{chat.username})"
            elif chat.first_name: username_info = f" ({chat.first_name})"
        except Exception as e: logger.warning(f"لم نتمكن من جلب معلومات المستخدم {admin_id_to_add}: {e}")
        await update.message.reply_text(
            _(user_id, "confirm_add_admin_prompt", admin_id=admin_id_to_add, username_info=username_info),
            reply_markup=reply_markup
        )
        return CONFIRM_ADD_ADMIN

async def execute_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    admin_id_to_add = context.user_data.get("add_admin_id")
    if not admin_id_to_add:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    config = load_config()
    if "admins" not in config or not isinstance(config["admins"], list): config["admins"] = [ADMIN_ID]
    message = ""
    if admin_id_to_add in config["admins"]:
        message = _(user_id, "user_already_admin", admin_id=admin_id_to_add)
    else:
        config["admins"].append(admin_id_to_add)
        save_config(config)
        message = _(user_id, "add_admin_success", admin_id=admin_id_to_add)
    
    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_admins_button"), callback_data="manage_admins")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    context.user_data.pop("add_admin_id", None)
    return MAIN_MENU

# --- إزالة مسؤول (مع الترجمة والتأكيد) ---
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    config = load_config()
    admins = config.get("admins", [ADMIN_ID])
    removable_admins = [admin for admin in admins if admin != ADMIN_ID]
    if not removable_admins:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_admins")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "cannot_remove_main_admin"), reply_markup=reply_markup)
        return MANAGE_ADMINS
    
    keyboard = []
    users = load_users()
    for admin_id in removable_admins:
        admin_id_str = str(admin_id)
        username = users.get(admin_id_str, {}).get("username", f"ID: {admin_id}")
        keyboard.append([InlineKeyboardButton(_(user_id, "admin_remove_button_format", username=username), callback_data=f"confirm_del_admin_{admin_id}")])
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="manage_admins")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(_(user_id, "select_admin_to_remove"), reply_markup=reply_markup)
    return REMOVE_ADMIN

async def confirm_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    try: admin_id_to_remove = int(query.data.replace("confirm_del_admin_", ""))
    except ValueError:
        keyboard = [[InlineKeyboardButton(_(user_id, "back_to_manage_admins_button"), callback_data="manage_admins")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "invalid_selection"), reply_markup=reply_markup)
        return MANAGE_ADMINS
        
    context.user_data["remove_admin_id"] = admin_id_to_remove
    keyboard = [
        [InlineKeyboardButton(_(user_id, "confirm_remove_admin_yes"), callback_data="execute_del_admin_yes")],
        [InlineKeyboardButton(_(user_id, "confirm_remove_admin_no"), callback_data="manage_admins")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    username_info = ""
    try:
        chat = await context.bot.get_chat(admin_id_to_remove)
        if chat.username: username_info = f" (@{chat.username})"
        elif chat.first_name: username_info = f" ({chat.first_name})"
    except Exception as e: logger.warning(f"لم نتمكن من جلب معلومات المستخدم {admin_id_to_remove}: {e}")
    await query.edit_message_text(
        _(user_id, "confirm_remove_admin_prompt", admin_id=admin_id_to_remove, username_info=username_info),
        reply_markup=reply_markup
    )
    return CONFIRM_REMOVE_ADMIN

async def execute_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    admin_id_to_remove = context.user_data.get("remove_admin_id")
    if not admin_id_to_remove:
        await query.edit_message_text(_(user_id, "generic_error"))
        return await admin_command(update, context)
        
    config = load_config()
    message = ""
    if admin_id_to_remove == ADMIN_ID:
        message = _(user_id, "cannot_remove_main_admin_error")
    elif "admins" in config and isinstance(config["admins"], list) and admin_id_to_remove in config["admins"]:
        config["admins"].remove(admin_id_to_remove)
        save_config(config)
        message = _(user_id, "remove_admin_success", admin_id=admin_id_to_remove)
    else: message = _(user_id, "user_not_admin_or_removed", admin_id=admin_id_to_remove)
    
    keyboard = [
        [InlineKeyboardButton(_(user_id, "back_to_manage_admins_button"), callback_data="manage_admins")],
        [InlineKeyboardButton(_(user_id, "back_to_main_button"), callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    context.user_data.pop("remove_admin_id", None)
    return MAIN_MENU

# --- وظائف إدارة اللغة --- 
async def manage_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    keyboard = []
    available_langs = translations.keys()
    # عرض اللغات المتاحة
    for lang_code in available_langs:
        # الحصول على اسم اللغة من ملف الترجمة نفسه (اختياري)
        lang_name = translations.get(lang_code, {}).get(f"language_{lang_code}", lang_code)
        keyboard.append([InlineKeyboardButton(lang_name, callback_data=f"set_lang_{lang_code}")])
        
    keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(_(user_id, "select_language_prompt"), reply_markup=reply_markup)
    return SELECT_LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    lang_code = query.data.replace("set_lang_", "")
    
    if lang_code in translations:
        set_user_language(user_id, lang_code)
        lang_name = translations.get(lang_code, {}).get(f"language_{lang_code}", lang_code)
        await query.edit_message_text(_(user_id, "language_set_success", language_name=lang_name))
        await asyncio.sleep(1.5) # إعطاء المستخدم وقتاً لقراءة الرسالة
        # العودة إلى القائمة الرئيسية باللغة الجديدة
        return await admin_command(update, context)
    else:
        await query.answer(_(user_id, "invalid_selection"), show_alert=True)
        # البقاء في نفس القائمة
        keyboard = []
        available_langs = translations.keys()
        for lc in available_langs:
            ln = translations.get(lc, {}).get(f"language_{lc}", lc)
            keyboard.append([InlineKeyboardButton(ln, callback_data=f"set_lang_{lc}")])
        keyboard.append([InlineKeyboardButton(_(user_id, "back_button"), callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(_(user_id, "select_language_prompt"), reply_markup=reply_markup)
        return SELECT_LANGUAGE

# --- وظائف التنقل والعودة (مع الترجمة) ---
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    return await admin_command(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    message_text = _(user_id, "cancel_message")
    if query:
        await query.answer()
        try: await query.edit_message_text(message_text)
        except Exception as e: logger.info(f"لم نتمكن من تعديل الرسالة عند الإلغاء: {e}")
    elif update.message: 
        # إصلاح: إضافة await هنا
        await update.message.reply_text(message_text)
    context.user_data.clear()
    return ConversationHandler.END

# --- وظائف المهام الدورية (مع الترجمة للرسائل) ---
async def start_periodic_task(application, group_id):
    config = load_config()
    if group_id not in config.get("groups", {}): return
    await stop_periodic_task(application, group_id)
    interval = config["groups"][group_id].get("interval", 600)
    if interval <= 0: return
    stop_flags[group_id] = threading.Event()
    thread = threading.Thread(target=periodic_task_thread, args=(application.bot, group_id, interval, stop_flags[group_id]), daemon=True)
    thread.start()
    scheduled_tasks[group_id] = thread
    logger.info(f"تم بدء المهمة الدورية للمجموعة {group_id} بفاصل زمني {interval} ثانية")

async def stop_periodic_task(application, group_id):
    if group_id in stop_flags:
        stop_flags[group_id].set()
        if group_id in scheduled_tasks:
            thread = scheduled_tasks.pop(group_id)
            thread.join(timeout=5)
            if thread.is_alive(): logger.warning(f"الخيط الدوري للمجموعة {group_id} لم ينتهِ بعد المهلة.")
        if group_id in stop_flags: del stop_flags[group_id]

def periodic_task_thread(bot, group_id, interval, stop_flag):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while not stop_flag.is_set():
        start_time = time.time()
        try: loop.run_until_complete(send_auth_message(bot, group_id))
        except Exception as e: logger.error(f"[Thread-{group_id}] خطأ في خيط المهمة الدورية: {e}", exc_info=True)
        elapsed_time = time.time() - start_time
        wait_time = max(0, interval - elapsed_time)
        check_interval = 1
        end_wait_time = time.time() + wait_time
        while time.time() < end_wait_time and not stop_flag.is_set():
            time.sleep(min(check_interval, end_wait_time - time.time()))
    loop.close()
    logger.info(f"[Thread-{group_id}] تم إنهاء خيط المهمة الدورية.")

async def send_auth_message(bot, group_id):
    config = load_config()
    if group_id not in config.get("groups", {}): return
    
    group_config = config["groups"][group_id]
    totp_secret = group_config.get("totp_secret")
    interval = group_config.get("interval", 600)
    message_style = group_config.get("message_style", 1)
    timezone_name = group_config.get("timezone", "UTC")
    if not totp_secret: return
        
    try:
        totp = pyotp.TOTP(totp_secret)
        code = totp.now()
        remaining_validity = get_remaining_validity(totp)
    except Exception as e:
        logger.error(f"خطأ في توليد رمز TOTP للمجموعة {group_id}: {e}")
        try: await bot.send_message(chat_id=int(group_id), text=_(ADMIN_ID, "error_generating_totp", group_id=group_id)) # استخدام لغة المسؤول الافتراضي للرسائل العامة
        except Exception as send_error: logger.error(_(ADMIN_ID, "error_sending_totp_error", group_id=group_id, error=str(send_error)))
        return

    current_time = get_time_format(timezone_name)
    next_time = get_next_time(interval, timezone_name)
    # إصلاح: استخدام لغة المسؤول الافتراضي لتنسيق الفاصل الزمني في الرسائل العامة
    interval_text = format_interval(ADMIN_ID, interval)
    message_text = ""
    # استخدام لغة المسؤول الافتراضي للرسائل العامة المرسلة للمجموعة
    if message_style == 1: message_text = _(ADMIN_ID, "auth_message_style1", next_time=next_time)
    elif message_style == 2: message_text = _(ADMIN_ID, "auth_message_style2", interval_text=interval_text, next_time=next_time)
    else: message_text = _(ADMIN_ID, "auth_message_style3", interval_text=interval_text, current_time=current_time, next_time=next_time)
    
    # إصلاح: ترجمة زر النسخ باستخدام لغة المسؤول الافتراضي
    keyboard = [[InlineKeyboardButton(_(ADMIN_ID, "copy_code_button"), callback_data=f"copy_code_{group_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await bot.send_message(chat_id=int(group_id), text=message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"خطأ في إرسال رسالة المصادقة إلى المجموعة {group_id}: {str(e)}")
        if "chat not found" in str(e).lower() or "bot was kicked" in str(e).lower():
             if group_id in stop_flags: stop_flags[group_id].set()

# --- وظائف معالجة الأزرار (مع الترجمة) ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("copy_code_"):
        await query.answer()
        group_id = query.data.replace("copy_code_", "")
        await handle_copy_code(update, context, group_id)

async def handle_copy_code(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id):
    query = update.callback_query
    user = query.from_user
    user_id = str(user.id)
    username = user.username or f"{user.first_name} (No Username)"
    
    config = load_config()
    users = load_users()
    
    if group_id not in config.get("groups", {}):
        try: await query.edit_message_reply_markup(reply_markup=None)
        except Exception as e: pass
        await query.answer(_(user.id, "error_group_does_not_exist"), show_alert=True)
        return
    
    today = datetime.date.today().isoformat()
    # تحديث بيانات المستخدم وتعيين اللغة إذا لم تكن موجودة
    if user_id not in users:
        users[user_id] = {"attempts": {}, "banned": False, "username": username, "language": DEFAULT_LANG}
    else:
        users[user_id]["username"] = username
        if "language" not in users[user_id]: users[user_id]["language"] = DEFAULT_LANG
        
    if users[user_id].get("banned", False):
        await query.answer(_(user.id, "user_banned_from_copy"), show_alert=True)
        return
    
    default_attempts = config.get("groups", {}).get(group_id, {}).get("default_attempts", 5)
    
    if "attempts" not in users[user_id]: users[user_id]["attempts"] = {}
    if group_id not in users[user_id]["attempts"]:
        users[user_id]["attempts"][group_id] = {"remaining": default_attempts, "reset_date": today}
    
    if users[user_id]["attempts"][group_id]["reset_date"] != today:
        users[user_id]["attempts"][group_id] = {"remaining": default_attempts, "reset_date": today}
    
    if users[user_id]["attempts"][group_id]["remaining"] <= 0:
        await query.answer(_(user.id, "attempts_exhausted_alert", default_attempts=default_attempts), show_alert=True)
        try: await context.bot.send_message(chat_id=user.id, text=_(user.id, "attempts_exhausted_message", group_id=group_id))
        except Exception as e: pass
        return
    
    users[user_id]["attempts"][group_id]["remaining"] -= 1
    save_users(users)
    
    totp_secret = config["groups"][group_id]["totp_secret"]
    try:
        totp = pyotp.TOTP(totp_secret)
        code = totp.now()
        remaining_validity = get_remaining_validity(totp)
    except Exception as e:
        logger.error(f"خطأ في توليد رمز TOTP عند النسخ للمجموعة {group_id}: {e}")
        await query.answer(_(user.id, "error_generating_code_on_copy"), show_alert=True)
        users[user_id]["attempts"][group_id]["remaining"] += 1
        save_users(users)
        return
        
    remaining_attempts = users[user_id]["attempts"][group_id]["remaining"]
    # استخدام MarkdownV2 يتطلب تهريب الأحرف الخاصة
    # تصحيح: استخدام علامات اقتباس صحيحة وتهريب صحيح لـ MarkdownV2
    code_escaped = code.replace('`', '\\`')
    message_text_md2 = _(user.id, "code_copied_alert_md2", code=code_escaped, remaining_validity=remaining_validity, remaining_attempts=remaining_attempts)
    message_text_md = _(user.id, "code_copied_alert_md", code=code, remaining_validity=remaining_validity, remaining_attempts=remaining_attempts)
    
    try:
        # تصحيح: استخدام علامات اقتباس صحيحة
        await query.answer(message_text_md2, show_alert=True, parse_mode='MarkdownV2')
    except Exception as e:
        logger.warning(f"فشل إرسال الرمز كـ Alert (MarkdownV2): {e}. محاولة Markdown.")
        try: 
            # تصحيح: استخدام علامات اقتباس صحيحة
            await query.answer(message_text_md, show_alert=True, parse_mode='Markdown')
        except Exception as e2:
            logger.warning(f"فشل إرسال الرمز كـ Alert (Markdown): {e2}. محاولة رسالة عادية.")
            try: 
                # إصلاح: إضافة await هنا
                # تصحيح: استخدام علامات اقتباس صحيحة
                await context.bot.send_message(chat_id=user.id, text=message_text_md, parse_mode='Markdown')
            except Exception as send_error:
                 logger.error(f"فشل إرسال الرمز كرسالة للمستخدم {user_id}: {send_error}")
                 await query.answer(_(user.id, "error_sending_code_alert"), show_alert=True)
                 users[user_id]["attempts"][group_id]["remaining"] += 1
                 save_users(users)

# --- دالة رئيسية وإعداد المحادثة (مع تحديث الحالات للغة) ---
def main():
    logger.info("بدء تحميل الترجمة...")
    load_translations()
    if not translations or (DEFAULT_LANG not in translations and "en" not in translations):
        logger.critical("فشل تحميل ملفات الترجمة الأساسية. لا يمكن المتابعة.")
        return
        
    logger.info("بدء تحميل الإعدادات والمستخدمين...")
    load_config()
    load_users()
    logger.info("تم تحميل الإعدادات والمستخدمين.")
    
    application = Application.builder().token(TOKEN).build()
    
    logger.info("بدء تشغيل المهام الدورية للمجموعات الموجودة...")
    config = load_config()
    if "groups" in config:
        for group_id in config["groups"]:
            asyncio.create_task(start_periodic_task(application, group_id))
            
    logger.info("إعداد معالج المحادثة...")
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
                CallbackQueryHandler(manage_interval, pattern="^manage_interval$"),
                CallbackQueryHandler(manage_message_style, pattern="^manage_message_style$"),
                CallbackQueryHandler(manage_user_attempts, pattern="^manage_user_attempts$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
                CallbackQueryHandler(manage_language, pattern="^manage_language$"), # معالج زر اللغة
                CallbackQueryHandler(cancel, pattern="^cancel$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
            ],
            # ... (الحالات الأخرى كما هي مع إضافة حالات اللغة)
            MANAGE_GROUPS: [
                CallbackQueryHandler(add_group, pattern="^add_group$"),
                CallbackQueryHandler(delete_group, pattern="^delete_group$"),
                CallbackQueryHandler(edit_group, pattern="^edit_group$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
            ],
            ADD_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_group)],
            ADD_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_secret)],
            CONFIRM_ADD_GROUP: [
                CallbackQueryHandler(execute_add_group, pattern="^confirm_add_group_yes$"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
            ],
            DELETE_GROUP: [
                CallbackQueryHandler(confirm_delete_group, pattern="^confirm_del_group_"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
            ],
            CONFIRM_DELETE_GROUP: [
                 CallbackQueryHandler(execute_delete_group, pattern="^execute_del_group_yes$"),
                 CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
            ],
            EDIT_GROUP: [
                CallbackQueryHandler(process_edit_group, pattern="^edit_group_"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
            ],
            EDIT_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_secret)],
            MANAGE_INTERVAL: [
                CallbackQueryHandler(process_manage_interval, pattern="^interval_"),
                CallbackQueryHandler(set_interval, pattern="^set_interval_"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_interval, pattern="^manage_interval$"),
            ],
            MANAGE_MESSAGE_STYLE: [
                CallbackQueryHandler(process_manage_message_style, pattern="^style_"),
                CallbackQueryHandler(set_message_style, pattern="^set_style_"),
                CallbackQueryHandler(set_message_style, pattern="^set_timezone_"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_message_style, pattern="^manage_message_style$"),
            ],
            MANAGE_ADMINS: [
                CallbackQueryHandler(add_admin, pattern="^add_admin$"),
                CallbackQueryHandler(remove_admin, pattern="^remove_admin$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
            ],
            ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_admin)],
            CONFIRM_ADD_ADMIN: [
                CallbackQueryHandler(execute_add_admin, pattern="^confirm_add_admin_yes$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
            ],
            REMOVE_ADMIN: [
                CallbackQueryHandler(confirm_remove_admin, pattern="^confirm_del_admin_"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
            ],
            CONFIRM_REMOVE_ADMIN: [
                CallbackQueryHandler(execute_remove_admin, pattern="^execute_del_admin_yes$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
            ],
            MANAGE_USER_ATTEMPTS: [
                CallbackQueryHandler(select_group_for_user, pattern="^select_group_for_user$"),
                CallbackQueryHandler(select_group_for_default_attempts, pattern="^select_group_default_attempts$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
            ],
            SELECT_GROUP_FOR_DEFAULT_ATTEMPTS: [
                CallbackQueryHandler(request_new_default_attempts, pattern="^set_default_attempts_"),
                CallbackQueryHandler(manage_user_attempts, pattern="^manage_user_attempts$"),
                CallbackQueryHandler(select_group_for_default_attempts, pattern="^select_group_default_attempts$"),
            ],
            SET_DEFAULT_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_set_default_attempts)],
            SELECT_GROUP_FOR_USER: [
                CallbackQueryHandler(select_user, pattern="^select_users_"),
                CallbackQueryHandler(manage_user_attempts, pattern="^manage_user_attempts$"),
            ],
            SELECT_USER: [
                CallbackQueryHandler(manage_user, pattern="^manage_user_"),
                CallbackQueryHandler(select_group_for_user, pattern="^select_group_for_user$"),
            ],
            MANAGE_USER: [
                CallbackQueryHandler(add_attempts, pattern="^add_attempts$"),
                CallbackQueryHandler(remove_attempts, pattern="^remove_attempts$"),
                CallbackQueryHandler(toggle_ban, pattern="^toggle_ban$"),
                CallbackQueryHandler(select_user, pattern="^select_users_"),
                CallbackQueryHandler(manage_user, pattern="^manage_user_"),
            ],
            ADD_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_attempts)],
            REMOVE_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_remove_attempts)],
            # --- حالات إدارة اللغة ---
            SELECT_LANGUAGE: [
                CallbackQueryHandler(set_language, pattern="^set_lang_"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
            ],
        },
        fallbacks=[
            CommandHandler("admin", admin_command),
            CommandHandler("start", start),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, lambda update, context: update.message.reply_text(_(update.effective_user.id, "unexpected_input_in_conversation"))),
            CallbackQueryHandler(lambda update, context: update.callback_query.answer(_(update.effective_user.id, "invalid_button_alert"), show_alert=True)),
        ],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^copy_code_"))
    
    logger.info("بدء تشغيل البوت...")
    application.run_polling()

if __name__ == '__main__':
    main()


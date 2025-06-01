#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ChatGPTPlus2FABot - بوت تليجرام للمصادقة الثنائية 2FA
يقوم بإرسال رمز مصادقة ثنائية للمستخدمين بشكل دوري
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
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466  # تحويل النص إلى رقم

# حالات المحادثة
(
    MAIN_MENU, MANAGE_GROUPS, ADD_GROUP, DELETE_GROUP, EDIT_GROUP,
    ADD_SECRET, EDIT_SECRET, MANAGE_INTERVAL,
    MANAGE_MESSAGE_STYLE, MANAGE_USER_ATTEMPTS, SELECT_GROUP_FOR_USER,
    SELECT_USER, MANAGE_USER, ADD_ATTEMPTS, REMOVE_ATTEMPTS,
    MANAGE_ADMINS, ADD_ADMIN, REMOVE_ADMIN
) = range(18)  # تم تصحيح عدد الحالات ليكون 18 بدلاً من 19

# ملفات البيانات
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# هيكل البيانات الافتراضي
DEFAULT_CONFIG = {
    "groups": {},  # {"group_id": {"totp_secret": "SECRET", "interval": 600, "message_style": 1}}
    "admins": [ADMIN_ID]
}

DEFAULT_USERS = {
    # "user_id": {"attempts": {"group_id": {"remaining": 5, "reset_date": "YYYY-MM-DD"}}, "banned": False}
}

# متغيرات عالمية للتحكم بالمهام الدورية
scheduled_tasks = {}
stop_flags = {}

# وظائف إدارة البيانات
def load_config():
    """تحميل ملف الإعدادات"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # إنشاء ملف الإعدادات إذا لم يكن موجوداً
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=4)
        return DEFAULT_CONFIG

def save_config(config):
    """حفظ ملف الإعدادات"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def load_users():
    """تحميل بيانات المستخدمين"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # إنشاء ملف المستخدمين إذا لم يكن موجوداً
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_USERS, f, ensure_ascii=False, indent=4)
        return DEFAULT_USERS

def save_users(users):
    """حفظ بيانات المستخدمين"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً"""
    config = load_config()
    return user_id in config["admins"]

def get_time_format(timezone_name="UTC"):
    """الحصول على الوقت الحالي بتنسيق 12 ساعة"""
    timezone = tz.gettz(timezone_name)
    now = datetime.datetime.now(timezone)
    return now.strftime("%I:%M:%S %p")  # تنسيق 12 ساعة مع AM/PM

def get_next_time(interval_seconds, timezone_name="UTC"):
    """حساب وقت الرمز التالي"""
    timezone = tz.gettz(timezone_name)
    now = datetime.datetime.now(timezone)
    next_time = now + datetime.timedelta(seconds=interval_seconds)
    return next_time.strftime("%I:%M:%S %p")  # تنسيق 12 ساعة مع AM/PM

def format_interval(seconds):
    """تنسيق الفاصل الزمني بشكل مقروء"""
    if seconds < 60:
        return f"{seconds} ثانية"
    elif seconds < 3600:
        return f"{seconds // 60} دقيقة"
    elif seconds < 86400:
        return f"{seconds // 3600} ساعة"
    else:
        return f"{seconds // 86400} يوم"

def get_remaining_validity(totp):
    """حساب الوقت المتبقي لصلاحية الرمز بالثواني"""
    return 30 - int(time.time()) % 30

# وظائف البوت الأساسية
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"مرحباً {user.first_name}! هذا بوت المصادقة الثنائية 2FA.\n"
        f"إذا كنت مسؤولاً، يمكنك استخدام الأمر /admin للوصول إلى لوحة التحكم."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /admin"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_interval")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message_style")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_user_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")],
        [InlineKeyboardButton("إلغاء", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مرحباً بك في لوحة الإدارة. يرجى اختيار إحدى الخيارات:", reply_markup=reply_markup)
    
    return MAIN_MENU

# وظائف إدارة المجموعات
async def manage_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة المجموعات وTOTP_SECRET"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("إضافة مجموعة", callback_data="add_group")],
        [InlineKeyboardButton("حذف مجموعة", callback_data="delete_group")],
        [InlineKeyboardButton("تعديل مجموعة", callback_data="edit_group")],
        [InlineKeyboardButton("العودة", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("يرجى اختيار إحدى العمليات لإدارة المجموعات:", reply_markup=reply_markup)
    
    return MANAGE_GROUPS

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مجموعة جديدة"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "يرجى إدخال معرف المجموعة (مثال: -100XXXXXXXXXX):"
    )
    
    return ADD_GROUP

async def process_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة المجموعة"""
    group_id = update.message.text.strip()
    
    # التحقق من صحة معرف المجموعة
    if not group_id.startswith("-100") or not group_id[4:].isdigit():
        await update.message.reply_text(
            "معرف المجموعة غير صالح. يجب أن يبدأ بـ -100 متبوعاً بأرقام.\n"
            "يرجى إدخال معرف المجموعة مرة أخرى:"
        )
        return ADD_GROUP
    
    # حفظ معرف المجموعة في سياق المحادثة
    context.user_data["group_id"] = group_id
    
    await update.message.reply_text(
        "تم حفظ معرف المجموعة بنجاح.\n"
        "الآن يرجى إدخال TOTP_SECRET الخاص بالمصادقة الثنائية:"
    )
    
    return ADD_SECRET

async def process_add_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة TOTP_SECRET"""
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("group_id")
    
    # التحقق من صحة TOTP_SECRET
    try:
        # محاولة إنشاء كائن TOTP للتحقق من صحة السر
        totp = pyotp.TOTP(totp_secret)
        totp.now()  # هذا سيرفع استثناءً إذا كان السر غير صالح
    except Exception as e:
        await update.message.reply_text(
            f"TOTP_SECRET غير صالح: {str(e)}\n"
            "يرجى إدخال TOTP_SECRET صالح:"
        )
        return ADD_SECRET
    
    # إضافة المجموعة والسر إلى الإعدادات
    config = load_config()
    config["groups"][group_id] = {
        "totp_secret": totp_secret,
        "interval": 600,  # 10 دقائق افتراضياً
        "message_style": 1  # النمط الافتراضي
    }
    save_config(config)
    
    # إنشاء مهمة دورية للمجموعة
    await start_periodic_task(context, group_id)
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المجموعات", callback_data="manage_groups")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"تم إضافة المجموعة {group_id} مع TOTP_SECRET بنجاح!",
        reply_markup=reply_markup
    )
    
    return MAIN_MENU

async def delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف مجموعة"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="manage_groups")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=reply_markup)
        return MANAGE_GROUPS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f"del_group_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_groups")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
    
    return DELETE_GROUP

async def process_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة حذف المجموعة"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من بيانات الاستدعاء
    group_id = query.data.replace("del_group_", "")
    
    # إيقاف المهمة الدورية للمجموعة إذا كانت موجودة
    await stop_periodic_task(context, group_id)
    
    # حذف المجموعة من الإعدادات
    config = load_config()
    if group_id in config["groups"]:
        del config["groups"][group_id]
        save_config(config)
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المجموعات", callback_data="manage_groups")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"تم حذف المجموعة {group_id} بنجاح!", reply_markup=reply_markup)
    
    return MAIN_MENU

async def edit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعديل مجموعة"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="manage_groups")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=reply_markup)
        return MANAGE_GROUPS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f"edit_group_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_groups")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المجموعة التي تريد تعديلها:", reply_markup=reply_markup)
    
    return EDIT_GROUP

async def process_edit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تعديل المجموعة"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من بيانات الاستدعاء
    group_id = query.data.replace("edit_group_", "")
    context.user_data["edit_group_id"] = group_id
    
    await query.edit_message_text(
        f"يرجى إدخال TOTP_SECRET الجديد للمجموعة {group_id}:"
    )
    
    return EDIT_SECRET

async def process_edit_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تعديل TOTP_SECRET"""
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("edit_group_id")
    
    # التحقق من صحة TOTP_SECRET
    try:
        # محاولة إنشاء كائن TOTP للتحقق من صحة السر
        totp = pyotp.TOTP(totp_secret)
        totp.now()  # هذا سيرفع استثناءً إذا كان السر غير صالح
    except Exception as e:
        await update.message.reply_text(
            f"TOTP_SECRET غير صالح: {str(e)}\n"
            "يرجى إدخال TOTP_SECRET صالح:"
        )
        return EDIT_SECRET
    
    # تحديث TOTP_SECRET في الإعدادات
    config = load_config()
    if group_id in config["groups"]:
        config["groups"][group_id]["totp_secret"] = totp_secret
        save_config(config)
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المجموعات", callback_data="manage_groups")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"تم تحديث TOTP_SECRET للمجموعة {group_id} بنجاح!",
        reply_markup=reply_markup
    )
    
    return MAIN_MENU

# وظائف إدارة فترة التكرار
async def manage_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة فترة التكرار"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=reply_markup)
        return MAIN_MENU
    
    keyboard = []
    for group_id in groups:
        interval = config["groups"][group_id].get("interval", 600)
        interval_text = format_interval(interval)
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} ({interval_text})", callback_data=f"interval_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المجموعة لتعديل فترة التكرار:", reply_markup=reply_markup)
    
    return MANAGE_INTERVAL

async def process_manage_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدارة فترة التكرار"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من بيانات الاستدعاء
    group_id = query.data.replace("interval_", "")
    context.user_data["interval_group_id"] = group_id
    
    keyboard = [
        [InlineKeyboardButton("1 دقيقة", callback_data="set_interval_60")],
        [InlineKeyboardButton("5 دقائق", callback_data="set_interval_300")],
        [InlineKeyboardButton("10 دقائق", callback_data="set_interval_600")],
        [InlineKeyboardButton("15 دقيقة", callback_data="set_interval_900")],
        [InlineKeyboardButton("30 دقيقة", callback_data="set_interval_1800")],
        [InlineKeyboardButton("ساعة", callback_data="set_interval_3600")],
        [InlineKeyboardButton("3 ساعات", callback_data="set_interval_10800")],
        [InlineKeyboardButton("12 ساعة", callback_data="set_interval_43200")],
        [InlineKeyboardButton("24 ساعة", callback_data="set_interval_86400")],
        [InlineKeyboardButton("إيقاف التكرار", callback_data="stop_interval")],
        [InlineKeyboardButton("بدء التكرار", callback_data="start_interval")],
        [InlineKeyboardButton("العودة", callback_data="manage_interval")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    config = load_config()
    current_interval = config["groups"][group_id].get("interval", 600)
    
    await query.edit_message_text(
        f"المجموعة: {group_id}\n"
        f"فترة التكرار الحالية: {format_interval(current_interval)}\n\n"
        "اختر فترة التكرار الجديدة:",
        reply_markup=reply_markup
    )
    
    return MANAGE_INTERVAL

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين فترة التكرار"""
    query = update.callback_query
    await query.answer()
    
    group_id = context.user_data.get("interval_group_id")
    
    if query.data == "stop_interval":
        # إيقاف المهمة الدورية
        await stop_periodic_task(context, group_id)
        
        keyboard = [
            [InlineKeyboardButton("العودة إلى إدارة فترة التكرار", callback_data="manage_interval")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"تم إيقاف التكرار للمجموعة {group_id} بنجاح!",
            reply_markup=reply_markup
        )
        
    elif query.data == "start_interval":
        # بدء المهمة الدورية
        await start_periodic_task(context, group_id)
        
        keyboard = [
            [InlineKeyboardButton("العودة إلى إدارة فترة التكرار", callback_data="manage_interval")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"تم بدء التكرار للمجموعة {group_id} بنجاح!",
            reply_markup=reply_markup
        )
        
    else:
        # تعيين فترة التكرار الجديدة
        interval = int(query.data.replace("set_interval_", ""))
        
        config = load_config()
        if group_id in config["groups"]:
            config["groups"][group_id]["interval"] = interval
            save_config(config)
        
        # إعادة تشغيل المهمة الدورية بالفترة الجديدة
        await stop_periodic_task(context, group_id)
        await start_periodic_task(context, group_id)
        
        keyboard = [
            [InlineKeyboardButton("العودة إلى إدارة فترة التكرار", callback_data="manage_interval")],
            [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"تم تعيين فترة التكرار للمجموعة {group_id} إلى {format_interval(interval)} بنجاح!",
            reply_markup=reply_markup
        )
    
    return MAIN_MENU

# وظائف إدارة شكل الرسالة
async def manage_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة شكل/توقيت الرسالة"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=reply_markup)
        return MAIN_MENU
    
    keyboard = []
    for group_id in groups:
        style = config["groups"][group_id].get("message_style", 1)
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} (النمط {style})", callback_data=f"style_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المجموعة لتعديل شكل الرسالة:", reply_markup=reply_markup)
    
    return MANAGE_MESSAGE_STYLE

async def process_manage_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدارة شكل الرسالة"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من بيانات الاستدعاء
    group_id = query.data.replace("style_", "")
    context.user_data["style_group_id"] = group_id
    
    # أمثلة على أشكال الرسائل
    style1 = "🔐 2FA Verification Code\n\nNext code at: 07:05:34 PM"
    style2 = "🔐 2FA Verification Code\n\nNext code in: 10 minutes\n\nNext code at: 07:05:34 PM"
    style3 = "🔐 2FA Verification Code\nNext code in: 10 minutes\nCorrect Time: 06:55:34 PM\nNext Code at: 07:05:34 PM"
    
    keyboard = [
        [InlineKeyboardButton("النمط الأول", callback_data="set_style_1")],
        [InlineKeyboardButton("النمط الثاني", callback_data="set_style_2")],
        [InlineKeyboardButton("النمط الثالث", callback_data="set_style_3")],
        [InlineKeyboardButton("توقيت غرينتش", callback_data="set_timezone_UTC")],
        [InlineKeyboardButton("توقيت غزة", callback_data="set_timezone_Asia/Gaza")],
        [InlineKeyboardButton("العودة", callback_data="manage_message_style")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    config = load_config()
    current_style = config["groups"][group_id].get("message_style", 1)
    current_timezone = config["groups"][group_id].get("timezone", "UTC")
    
    await query.edit_message_text(
        f"المجموعة: {group_id}\n"
        f"النمط الحالي: {current_style}\n"
        f"التوقيت الحالي: {current_timezone}\n\n"
        f"النمط الأول:\n{style1}\n\n"
        f"النمط الثاني:\n{style2}\n\n"
        f"النمط الثالث:\n{style3}\n\n"
        "اختر النمط أو التوقيت الجديد:",
        reply_markup=reply_markup
    )
    
    return MANAGE_MESSAGE_STYLE

async def set_message_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين شكل الرسالة"""
    query = update.callback_query
    await query.answer()
    
    group_id = context.user_data.get("style_group_id")
    config = load_config()
    
    if query.data.startswith("set_style_"):
        # تعيين نمط الرسالة
        style = int(query.data.replace("set_style_", ""))
        
        if group_id in config["groups"]:
            config["groups"][group_id]["message_style"] = style
            save_config(config)
        
        message = f"تم تعيين نمط الرسالة للمجموعة {group_id} إلى النمط {style} بنجاح!"
        
    elif query.data.startswith("set_timezone_"):
        # تعيين المنطقة الزمنية
        timezone = query.data.replace("set_timezone_", "")
        
        if group_id in config["groups"]:
            config["groups"][group_id]["timezone"] = timezone
            save_config(config)
        
        timezone_name = "غرينتش" if timezone == "UTC" else "غزة"
        message = f"تم تعيين توقيت الرسالة للمجموعة {group_id} إلى توقيت {timezone_name} بنجاح!"
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة شكل الرسالة", callback_data="manage_message_style")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return MAIN_MENU

# وظائف إدارة محاولات المستخدمين
async def manage_user_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة محاولات المستخدمين"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("حدد عدد مرات النسخ", callback_data="select_group_for_user")],
        [InlineKeyboardButton("العودة", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("إدارة محاولات المستخدمين:", reply_markup=reply_markup)
    
    return MANAGE_USER_ATTEMPTS

async def select_group_for_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار المجموعة لإدارة المستخدمين"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    groups = config.get("groups", {})
    
    if not groups:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="manage_user_attempts")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=reply_markup)
        return MANAGE_USER_ATTEMPTS
    
    keyboard = []
    for group_id in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f"select_users_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_user_attempts")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المجموعة لإدارة المستخدمين:", reply_markup=reply_markup)
    
    return SELECT_GROUP_FOR_USER

async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار المستخدم لإدارة المحاولات"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من بيانات الاستدعاء
    group_id = query.data.replace("select_users_", "")
    context.user_data["attempts_group_id"] = group_id
    
    users = load_users()
    
    # تصفية المستخدمين الذين لديهم محاولات في هذه المجموعة
    group_users = {}
    for user_id, user_data in users.items():
        if "attempts" in user_data and group_id in user_data["attempts"]:
            group_users[user_id] = user_data
    
    if not group_users:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="select_group_for_user")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لا يوجد مستخدمون في هذه المجموعة حالياً.", reply_markup=reply_markup)
        return SELECT_GROUP_FOR_USER
    
    keyboard = []
    for user_id, user_data in group_users.items():
        remaining = user_data["attempts"][group_id]["remaining"]
        keyboard.append([InlineKeyboardButton(
            f"المستخدم: {user_id} (المحاولات المتبقية: {remaining})",
            callback_data=f"manage_user_{user_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="select_group_for_user")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المستخدم لإدارة المحاولات:", reply_markup=reply_markup)
    
    return SELECT_USER

async def manage_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة محاولات المستخدم"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المستخدم من بيانات الاستدعاء
    user_id = query.data.replace("manage_user_", "")
    context.user_data["attempts_user_id"] = user_id
    
    group_id = context.user_data.get("attempts_group_id")
    users = load_users()
    
    if user_id in users and "attempts" in users[user_id] and group_id in users[user_id]["attempts"]:
        remaining = users[user_id]["attempts"][group_id]["remaining"]
        reset_date = users[user_id]["attempts"][group_id]["reset_date"]
        banned = users[user_id].get("banned", False)
        
        status = "محظور" if banned else "نشط"
        
        keyboard = [
            [InlineKeyboardButton("إضافة محاولات", callback_data="add_attempts")],
            [InlineKeyboardButton("حذف محاولات", callback_data="remove_attempts")],
            [InlineKeyboardButton("حظر المستخدم" if not banned else "إلغاء حظر المستخدم", callback_data="toggle_ban")],
            [InlineKeyboardButton("العودة", callback_data=f"select_users_{group_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"إدارة المستخدم: {user_id}\n"
            f"المجموعة: {group_id}\n"
            f"المحاولات المتبقية: {remaining}\n"
            f"تاريخ إعادة التعيين: {reset_date}\n"
            f"الحالة: {status}\n\n"
            "اختر الإجراء:",
            reply_markup=reply_markup
        )
        
        return MANAGE_USER
    else:
        keyboard = [[InlineKeyboardButton("العودة", callback_data=f"select_users_{group_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لم يتم العثور على بيانات المستخدم.", reply_markup=reply_markup)
        return SELECT_USER

async def toggle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حالة حظر المستخدم"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    
    users = load_users()
    
    if user_id in users:
        current_ban = users[user_id].get("banned", False)
        users[user_id]["banned"] = not current_ban
        save_users(users)
        
        status = "محظور" if not current_ban else "نشط"
        message = f"تم تغيير حالة المستخدم {user_id} إلى {status} بنجاح!"
    else:
        message = f"لم يتم العثور على المستخدم {user_id}."
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المستخدم", callback_data=f"manage_user_{user_id}")],
        [InlineKeyboardButton("العودة إلى اختيار المستخدمين", callback_data=f"select_users_{group_id}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return MANAGE_USER

async def add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة محاولات للمستخدم"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get("attempts_user_id")
    
    await query.edit_message_text(
        f"يرجى إدخال عدد المحاولات التي تريد إضافتها للمستخدم {user_id}:"
    )
    
    return ADD_ATTEMPTS

async def process_add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة المحاولات"""
    try:
        attempts = int(update.message.text.strip())
        if attempts <= 0:
            raise ValueError("يجب أن يكون العدد موجباً")
    except ValueError:
        await update.message.reply_text(
            "يرجى إدخال عدد صحيح موجب:"
        )
        return ADD_ATTEMPTS
    
    user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    
    users = load_users()
    
    if user_id not in users:
        users[user_id] = {"attempts": {}, "banned": False}
    
    if "attempts" not in users[user_id]:
        users[user_id]["attempts"] = {}
    
    if group_id not in users[user_id]["attempts"]:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        users[user_id]["attempts"][group_id] = {"remaining": 0, "reset_date": today}
    
    users[user_id]["attempts"][group_id]["remaining"] += attempts
    save_users(users)
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المستخدم", callback_data=f"manage_user_{user_id}")],
        [InlineKeyboardButton("العودة إلى اختيار المستخدمين", callback_data=f"select_users_{group_id}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"تم إضافة {attempts} محاولات للمستخدم {user_id} بنجاح!",
        reply_markup=reply_markup
    )
    
    return MANAGE_USER

async def remove_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف محاولات من المستخدم"""
    query = update.callback_query
    await query.answer()
    
    user_id = context.user_data.get("attempts_user_id")
    
    await query.edit_message_text(
        f"يرجى إدخال عدد المحاولات التي تريد حذفها من المستخدم {user_id}:"
    )
    
    return REMOVE_ATTEMPTS

async def process_remove_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة حذف المحاولات"""
    try:
        attempts = int(update.message.text.strip())
        if attempts <= 0:
            raise ValueError("يجب أن يكون العدد موجباً")
    except ValueError:
        await update.message.reply_text(
            "يرجى إدخال عدد صحيح موجب:"
        )
        return REMOVE_ATTEMPTS
    
    user_id = context.user_data.get("attempts_user_id")
    group_id = context.user_data.get("attempts_group_id")
    
    users = load_users()
    
    if (user_id in users and "attempts" in users[user_id] and 
            group_id in users[user_id]["attempts"]):
        
        current = users[user_id]["attempts"][group_id]["remaining"]
        users[user_id]["attempts"][group_id]["remaining"] = max(0, current - attempts)
        save_users(users)
        
        message = f"تم حذف {min(attempts, current)} محاولات من المستخدم {user_id} بنجاح!"
    else:
        message = f"لم يتم العثور على بيانات المحاولات للمستخدم {user_id}."
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المستخدم", callback_data=f"manage_user_{user_id}")],
        [InlineKeyboardButton("العودة إلى اختيار المستخدمين", callback_data=f"select_users_{group_id}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)
    
    return MANAGE_USER

# وظائف إدارة المسؤولين
async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة المسؤولين"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin")],
        [InlineKeyboardButton("إزالة مسؤول", callback_data="remove_admin")],
        [InlineKeyboardButton("العودة", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    config = load_config()
    admins = config.get("admins", [ADMIN_ID])
    admins_text = "\n".join([f"- {admin}" for admin in admins])
    
    await query.edit_message_text(
        "إدارة المسؤولين\n\n"
        f"المسؤولون الحاليون:\n{admins_text}\n\n"
        "اختر الإجراء:",
        reply_markup=reply_markup
    )
    
    return MANAGE_ADMINS

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مسؤول جديد"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "يرجى إدخال معرف المستخدم (User ID) للمسؤول الجديد:"
    )
    
    return ADD_ADMIN

async def process_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة المسؤول"""
    try:
        admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "يرجى إدخال معرف مستخدم صالح (أرقام فقط):"
        )
        return ADD_ADMIN
    
    config = load_config()
    
    if admin_id in config["admins"]:
        message = f"المستخدم {admin_id} مسؤول بالفعل."
    else:
        config["admins"].append(admin_id)
        save_config(config)
        message = f"تم إضافة المستخدم {admin_id} كمسؤول بنجاح!"
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المسؤولين", callback_data="manage_admins")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)
    
    return MAIN_MENU

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة مسؤول"""
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    admins = config.get("admins", [ADMIN_ID])
    
    if len(admins) <= 1:
        keyboard = [[InlineKeyboardButton("العودة", callback_data="manage_admins")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "لا يمكن إزالة المسؤول الوحيد.",
            reply_markup=reply_markup
        )
        return MANAGE_ADMINS
    
    keyboard = []
    for admin in admins:
        if admin != ADMIN_ID:  # لا يمكن إزالة المسؤول الرئيسي
            keyboard.append([InlineKeyboardButton(f"المسؤول: {admin}", callback_data=f"del_admin_{admin}")])
    
    keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_admins")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("اختر المسؤول الذي تريد إزالته:", reply_markup=reply_markup)
    
    return REMOVE_ADMIN

async def process_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إزالة المسؤول"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المسؤول من بيانات الاستدعاء
    admin_id = int(query.data.replace("del_admin_", ""))
    
    config = load_config()
    
    if admin_id in config["admins"]:
        config["admins"].remove(admin_id)
        save_config(config)
        message = f"تم إزالة المسؤول {admin_id} بنجاح!"
    else:
        message = f"المستخدم {admin_id} ليس مسؤولاً."
    
    keyboard = [
        [InlineKeyboardButton("العودة إلى إدارة المسؤولين", callback_data="manage_admins")],
        [InlineKeyboardButton("العودة إلى القائمة الرئيسية", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return MAIN_MENU

# وظائف التنقل
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة إلى القائمة الرئيسية"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_interval")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message_style")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_user_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")],
        [InlineKeyboardButton("إلغاء", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("مرحباً بك في لوحة الإدارة. يرجى اختيار إحدى الخيارات:", reply_markup=reply_markup)
    
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("تم إلغاء العملية.")
    else:
        await update.message.reply_text("تم إلغاء العملية.")
    
    return ConversationHandler.END

# وظائف المهام الدورية
async def start_periodic_task(context, group_id):
    """بدء مهمة دورية لإرسال رمز المصادقة"""
    config = load_config()
    
    if group_id not in config["groups"]:
        logger.error(f"المجموعة {group_id} غير موجودة في الإعدادات")
        return
    
    # إيقاف المهمة الحالية إذا كانت موجودة
    await stop_periodic_task(context, group_id)
    
    # إنشاء علم إيقاف جديد
    stop_flags[group_id] = threading.Event()
    
    # بدء مهمة جديدة في خيط منفصل
    interval = config["groups"][group_id].get("interval", 600)
    thread = threading.Thread(
        target=periodic_task_thread,
        args=(context.bot, group_id, interval, stop_flags[group_id])
    )
    thread.daemon = True
    thread.start()
    
    # حفظ مرجع الخيط
    scheduled_tasks[group_id] = thread
    
    logger.info(f"تم بدء المهمة الدورية للمجموعة {group_id} بفاصل زمني {interval} ثانية")

async def stop_periodic_task(context, group_id):
    """إيقاف مهمة دورية لإرسال رمز المصادقة"""
    if group_id in stop_flags:
        stop_flags[group_id].set()
        
        if group_id in scheduled_tasks:
            # انتظار انتهاء الخيط (بحد أقصى ثانية واحدة)
            scheduled_tasks[group_id].join(1)
            del scheduled_tasks[group_id]
        
        del stop_flags[group_id]
        logger.info(f"تم إيقاف المهمة الدورية للمجموعة {group_id}")

def periodic_task_thread(bot, group_id, interval, stop_flag):
    """خيط للمهمة الدورية"""
    while not stop_flag.is_set():
        # إرسال رسالة المصادقة
        asyncio.run(send_auth_message(bot, group_id))
        
        # انتظار الفاصل الزمني أو حتى يتم تعيين علم الإيقاف
        for _ in range(interval):
            if stop_flag.is_set():
                break
            time.sleep(1)

async def send_auth_message(bot, group_id):
    """إرسال رسالة المصادقة إلى المجموعة"""
    config = load_config()
    
    if group_id not in config["groups"]:
        logger.error(f"المجموعة {group_id} غير موجودة في الإعدادات")
        return
    
    group_config = config["groups"][group_id]
    interval = group_config.get("interval", 600)
    message_style = group_config.get("message_style", 1)
    timezone_name = group_config.get("timezone", "UTC")
    
    # تحضير الرسالة حسب النمط المختار
    current_time = get_time_format(timezone_name)
    next_time = get_next_time(interval, timezone_name)
    interval_text = format_interval(interval)
    
    if message_style == 1:
        message = f"🔐 2FA Verification Code\n\nNext code at: {next_time}"
    elif message_style == 2:
        message = f"🔐 2FA Verification Code\n\nNext code in: {interval_text}\n\nNext code at: {next_time}"
    else:  # message_style == 3
        message = f"🔐 2FA Verification Code\nNext code in: {interval_text}\nCorrect Time: {current_time}\nNext Code at: {next_time}"
    
    # إنشاء زر Copy Code
    keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # إرسال الرسالة إلى المجموعة
        await bot.send_message(
            chat_id=int(group_id),
            text=message,
            reply_markup=reply_markup
        )
        logger.info(f"تم إرسال رسالة المصادقة إلى المجموعة {group_id}")
    except Exception as e:
        logger.error(f"خطأ في إرسال رسالة المصادقة إلى المجموعة {group_id}: {str(e)}")

# وظائف معالجة الأزرار
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النقر على الأزرار"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("copy_code_"):
        # معالجة زر Copy Code
        group_id = query.data.replace("copy_code_", "")
        await handle_copy_code(update, context, group_id)
    else:
        # معالجة الأزرار الأخرى (يتم التعامل معها في المحادثة)
        pass

async def handle_copy_code(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id):
    """معالجة زر Copy Code"""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    config = load_config()
    users = load_users()
    
    # التحقق من وجود المجموعة
    if group_id not in config["groups"]:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("خطأ: المجموعة غير موجودة", show_alert=True)
        return
    
    # التحقق من حظر المستخدم
    if user_id in users and users[user_id].get("banned", False):
        await query.answer("أنت محظور من استخدام هذا البوت", show_alert=True)
        return
    
    # التحقق من عدد المحاولات المتبقية
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    if user_id not in users:
        users[user_id] = {"attempts": {}, "banned": False}
    
    if "attempts" not in users[user_id]:
        users[user_id]["attempts"] = {}
    
    if group_id not in users[user_id]["attempts"]:
        users[user_id]["attempts"][group_id] = {"remaining": 5, "reset_date": today}
    
    # إعادة تعيين المحاولات إذا كان اليوم مختلفاً
    if users[user_id]["attempts"][group_id]["reset_date"] != today:
        users[user_id]["attempts"][group_id] = {"remaining": 5, "reset_date": today}
    
    # التحقق من المحاولات المتبقية
    if users[user_id]["attempts"][group_id]["remaining"] <= 0:
        await query.answer(
            "لا توجد محاولات متبقية. يرجى الانتظار حتى منتصف الليل لإعادة تعيين المحاولات.",
            show_alert=True
        )
        return
    
    # تقليل عدد المحاولات المتبقية
    users[user_id]["attempts"][group_id]["remaining"] -= 1
    save_users(users)
    
    # توليد رمز المصادقة
    totp_secret = config["groups"][group_id]["totp_secret"]
    totp = pyotp.TOTP(totp_secret)
    code = totp.now()
    remaining_validity = get_remaining_validity(totp)
    remaining_attempts = users[user_id]["attempts"][group_id]["remaining"]
    
    # إرسال الرمز في رسالة خاصة
    message = (
        f"🔐 رمز المصادقة الثنائية: `{code}`\n\n"
        f"⏱ الرمز صالح لمدة {remaining_validity} ثانية فقط\n"
        f"🔄 المحاولات المتبقية اليوم: {remaining_attempts}"
    )
    
    try:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=message,
            parse_mode="Markdown"
        )
        await query.answer("تم إرسال الرمز في رسالة خاصة", show_alert=True)
    except Exception as e:
        logger.error(f"خطأ في إرسال رمز المصادقة إلى المستخدم {user_id}: {str(e)}")
        await query.answer(
            "لم نتمكن من إرسال رسالة خاصة. يرجى بدء محادثة مع البوت أولاً.",
            show_alert=True
        )

# وظيفة بدء البوت
async def start_bot_tasks(application):
    """بدء المهام الدورية للبوت"""
    config = load_config()
    
    for group_id in config["groups"]:
        await start_periodic_task(application, group_id)

def main():
    """النقطة الرئيسية لتشغيل البوت"""
    # إنشاء تطبيق البوت
    application = Application.builder().token(TOKEN).build()
    
    # إنشاء محادثة لوحة الإدارة
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
                CallbackQueryHandler(manage_interval, pattern="^manage_interval$"),
                CallbackQueryHandler(manage_message_style, pattern="^manage_message_style$"),
                CallbackQueryHandler(manage_user_attempts, pattern="^manage_user_attempts$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            MANAGE_GROUPS: [
                CallbackQueryHandler(add_group, pattern="^add_group$"),
                CallbackQueryHandler(delete_group, pattern="^delete_group$"),
                CallbackQueryHandler(edit_group, pattern="^edit_group$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$")
            ],
            ADD_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_group)
            ],
            DELETE_GROUP: [
                CallbackQueryHandler(process_delete_group, pattern="^del_group_"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$")
            ],
            EDIT_GROUP: [
                CallbackQueryHandler(process_edit_group, pattern="^edit_group_"),
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$")
            ],
            ADD_SECRET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_secret)
            ],
            EDIT_SECRET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_secret)
            ],
            MANAGE_INTERVAL: [
                CallbackQueryHandler(process_manage_interval, pattern="^interval_"),
                CallbackQueryHandler(set_interval, pattern="^set_interval_"),
                CallbackQueryHandler(set_interval, pattern="^stop_interval$"),
                CallbackQueryHandler(set_interval, pattern="^start_interval$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_interval, pattern="^manage_interval$")
            ],
            MANAGE_MESSAGE_STYLE: [
                CallbackQueryHandler(process_manage_message_style, pattern="^style_"),
                CallbackQueryHandler(set_message_style, pattern="^set_style_"),
                CallbackQueryHandler(set_message_style, pattern="^set_timezone_"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$"),
                CallbackQueryHandler(manage_message_style, pattern="^manage_message_style$")
            ],
            MANAGE_USER_ATTEMPTS: [
                CallbackQueryHandler(select_group_for_user, pattern="^select_group_for_user$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$")
            ],
            SELECT_GROUP_FOR_USER: [
                CallbackQueryHandler(select_user, pattern="^select_users_"),
                CallbackQueryHandler(manage_user_attempts, pattern="^manage_user_attempts$")
            ],
            SELECT_USER: [
                CallbackQueryHandler(manage_user, pattern="^manage_user_"),
                CallbackQueryHandler(select_group_for_user, pattern="^select_group_for_user$")
            ],
            MANAGE_USER: [
                CallbackQueryHandler(add_attempts, pattern="^add_attempts$"),
                CallbackQueryHandler(remove_attempts, pattern="^remove_attempts$"),
                CallbackQueryHandler(toggle_ban, pattern="^toggle_ban$"),
                CallbackQueryHandler(select_user, pattern="^select_users_")
            ],
            ADD_ATTEMPTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_attempts)
            ],
            REMOVE_ATTEMPTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_remove_attempts)
            ],
            MANAGE_ADMINS: [
                CallbackQueryHandler(add_admin, pattern="^add_admin$"),
                CallbackQueryHandler(remove_admin, pattern="^remove_admin$"),
                CallbackQueryHandler(back_to_main, pattern="^back_to_main$")
            ],
            ADD_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_admin)
            ],
            REMOVE_ADMIN: [
                CallbackQueryHandler(process_remove_admin, pattern="^del_admin_"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # بدء المهام الدورية
    application.job_queue.run_once(start_bot_tasks, 0)
    
    # تشغيل البوت
    application.run_polling()

if __name__ == "__main__":
    main()

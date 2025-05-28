#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ChatGPTPlus2FABot - بوت تليجرام لإرسال رموز المصادقة 2FA
"""

import os
import json
import logging
import datetime
import pytz
import pyotp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, CallbackContext

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
DEFAULT_GROUP_ID = "-1002329495586"
DEFAULT_ADMIN_ID = "764559466"

# مسارات الملفات
CONFIG_FILE = "config.json"
ATTEMPTS_FILE = "attempts.json"

# الإعدادات الافتراضية
DEFAULT_CONFIG = {
    "admins": [DEFAULT_ADMIN_ID],
    "groups": {
        DEFAULT_GROUP_ID: {
            "totp_secret": "",
            "interval_minutes": 10,
            "message_format": 2,  # 1, 2, or 3
            "timezone": "UTC",    # UTC or Gaza
            "active": False
        }
    }
}

DEFAULT_ATTEMPTS = {
    "users": {},
    "default_attempts": 3
}

# تحميل الإعدادات
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

# حفظ الإعدادات
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# تحميل محاولات النسخ
def load_attempts():
    if os.path.exists(ATTEMPTS_FILE):
        with open(ATTEMPTS_FILE, 'r') as f:
            return json.load(f)
    else:
        with open(ATTEMPTS_FILE, 'w') as f:
            json.dump(DEFAULT_ATTEMPTS, f, indent=4)
        return DEFAULT_ATTEMPTS

# حفظ محاولات النسخ
def save_attempts(attempts):
    with open(ATTEMPTS_FILE, 'w') as f:
        json.dump(attempts, f, indent=4)

# التحقق من صلاحيات المسؤول
def is_admin(user_id, config):
    return str(user_id) in config["admins"]

# الحصول على التوقيت الحالي
def get_current_time(timezone_str):
    if timezone_str == "Gaza":
        tz = pytz.timezone("Asia/Gaza")
    else:
        tz = pytz.timezone("UTC")
    
    return datetime.datetime.now(tz)

# تنسيق الوقت بنظام 12 ساعة
def format_time_12h(dt):
    return dt.strftime("%I:%M:%S %p")

# توليد رمز TOTP
def generate_totp_code(secret):
    if not secret:
        return "غير متاح"
    
    totp = pyotp.TOTP(secret)
    return totp.now()

# حساب الوقت المتبقي للرمز التالي
def calculate_next_code_time(interval_minutes, current_time):
    minutes = current_time.minute
    next_interval = ((minutes // interval_minutes) + 1) * interval_minutes
    
    next_time = current_time.replace(minute=0, second=0, microsecond=0)
    next_time = next_time + datetime.timedelta(minutes=next_interval)
    
    if next_time.minute >= 60:
        next_time = next_time.replace(minute=0)
        next_time = next_time + datetime.timedelta(hours=1)
    
    return next_time

# تحديث عدد المحاولات اليومية
async def reset_daily_attempts(context: CallbackContext):
    attempts = load_attempts()
    attempts["users"] = {}
    save_attempts(attempts)
    logger.info("تم إعادة تعيين محاولات النسخ اليومية")
    
    # جدولة إعادة التعيين التالية عند منتصف الليل
    now = datetime.datetime.now(pytz.timezone("UTC"))
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    delay = (tomorrow - now).total_seconds()
    
    context.job_queue.run_once(reset_daily_attempts, delay)

# إرسال رمز المصادقة إلى المجموعة
async def send_auth_code(context: CallbackContext):
    job = context.job
    group_id = job.data["group_id"]
    config = load_config()
    
    if group_id not in config["groups"]:
        logger.error(f"المجموعة {group_id} غير موجودة في الإعدادات")
        return
    
    group_config = config["groups"][group_id]
    
    if not group_config["active"]:
        logger.info(f"المجموعة {group_id} غير نشطة، تم إيقاف الإرسال")
        return
    
    secret = group_config["totp_secret"]
    interval_minutes = group_config["interval_minutes"]
    message_format = group_config["message_format"]
    timezone_str = group_config["timezone"]
    
    current_time = get_current_time(timezone_str)
    next_time = calculate_next_code_time(interval_minutes, current_time)
    
    # إنشاء نص الرسالة حسب التنسيق المختار
    if message_format == 1:
        message_text = f"🔐 2FA Verification Code\n\nNext code at: {format_time_12h(next_time)}"
    elif message_format == 2:
        message_text = f"🔐 2FA Verification Code\n\nNext code in: {interval_minutes} minutes\n\nNext code at: {format_time_12h(next_time)}"
    else:  # message_format == 3
        message_text = f"🔐 2FA Verification Code\n\nNext code in: {interval_minutes} minutes\nCorrect Time: {format_time_12h(current_time)}\nNext Code at: {format_time_12h(next_time)}"
    
    # إنشاء زر النسخ
    keyboard = [
        [InlineKeyboardButton("Copy Code", callback_data=f"copy_code:{group_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=message_text,
            reply_markup=reply_markup
        )
        logger.info(f"تم إرسال رمز المصادقة إلى المجموعة {group_id}")
    except Exception as e:
        logger.error(f"خطأ في إرسال الرمز إلى المجموعة {group_id}: {e}")
    
    # جدولة الإرسال التالي
    context.job_queue.run_once(
        send_auth_code,
        interval_minutes * 60,
        data={"group_id": group_id}
    )

# بدء البوت وجدولة المهام
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    user_id = str(update.effective_user.id)
    
    if is_admin(user_id, config):
        await update.message.reply_text(
            "مرحباً بك في بوت ChatGPTPlus2FABot!\n"
            "استخدم الأمر /admin للوصول إلى لوحة التحكم."
        )
    else:
        await update.message.reply_text(
            "مرحباً بك في بوت ChatGPTPlus2FABot!\n"
            "هذا البوت مخصص للمسؤولين فقط."
        )

# عرض لوحة تحكم المسؤول
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    user_id = str(update.effective_user.id)
    
    if not is_admin(user_id, config):
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمسؤولين فقط.")
        return
    
    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات والـTOTP", callback_data="manage_groups")],
        [InlineKeyboardButton("إعدادات جدولة الرموز", callback_data="schedule_settings")],
        [InlineKeyboardButton("تنسيق رسائل الرموز", callback_data="message_format")],
        [InlineKeyboardButton("إدارة محاولات النسخ", callback_data="manage_attempts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "مرحباً بك في لوحة تحكم المسؤول\n"
        "اختر أحد الخيارات أدناه:",
        reply_markup=reply_markup
    )

# معالجة الضغط على الأزرار
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    config = load_config()
    user_id = str(query.from_user.id)
    
    if not is_admin(user_id, config) and not query.data.startswith("copy_code"):
        await query.edit_message_text("عذراً، هذا الإجراء مخصص للمسؤولين فقط.")
        return
    
    # معالجة الضغط على زر نسخ الرمز
    if query.data.startswith("copy_code:"):
        group_id = query.data.split(":")[1]
        await handle_copy_code(query, context, group_id)
        return
    
    # معالجة أزرار لوحة التحكم
    if query.data == "manage_groups":
        await show_manage_groups(query, context)
    elif query.data == "schedule_settings":
        await show_schedule_settings(query, context)
    elif query.data == "message_format":
        await show_message_format(query, context)
    elif query.data == "manage_attempts":
        await show_manage_attempts(query, context)
    elif query.data == "add_group":
        context.user_data["action"] = "add_group"
        await query.edit_message_text(
            "الرجاء إدخال معرف المجموعة (مثال: -1002329495586):"
        )
    elif query.data.startswith("edit_group:"):
        group_id = query.data.split(":")[1]
        context.user_data["action"] = "edit_group"
        context.user_data["group_id"] = group_id
        await query.edit_message_text(
            f"الرجاء إدخال TOTP_SECRET للمجموعة {group_id}:"
        )
    elif query.data.startswith("delete_group:"):
        group_id = query.data.split(":")[1]
        await delete_group(query, context, group_id)
    elif query.data.startswith("set_interval:"):
        group_id = query.data.split(":")[1]
        context.user_data["action"] = "set_interval"
        context.user_data["group_id"] = group_id
        await query.edit_message_text(
            f"الرجاء إدخال عدد الدقائق بين كل إرسال للمجموعة {group_id}:"
        )
    elif query.data.startswith("toggle_active:"):
        parts = query.data.split(":")
        group_id = parts[1]
        new_state = parts[2] == "true"
        await toggle_group_active(query, context, group_id, new_state)
    elif query.data.startswith("set_format:"):
        parts = query.data.split(":")
        group_id = parts[1]
        format_num = int(parts[2])
        await set_message_format(query, context, group_id, format_num)
    elif query.data.startswith("set_timezone:"):
        parts = query.data.split(":")
        group_id = parts[1]
        timezone_str = parts[2]
        await set_timezone(query, context, group_id, timezone_str)
    elif query.data.startswith("select_user:"):
        user_info = query.data.split(":", 1)[1]
        await show_user_attempts_management(query, context, user_info)
    elif query.data.startswith("set_attempts:"):
        parts = query.data.split(":")
        user_id = parts[1]
        action = parts[2]
        await manage_user_attempts(query, context, user_id, action)
    elif query.data == "back_to_admin":
        await show_admin_panel(query, context)
    elif query.data.startswith("back_to_"):
        if query.data == "back_to_groups":
            await show_manage_groups(query, context)
        elif query.data == "back_to_schedule":
            await show_schedule_settings(query, context)
        elif query.data == "back_to_format":
            await show_message_format(query, context)
        elif query.data == "back_to_attempts":
            await show_manage_attempts(query, context)

# عرض لوحة تحكم المسؤول
async def show_admin_panel(query, context):
    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات والـTOTP", callback_data="manage_groups")],
        [InlineKeyboardButton("إعدادات جدولة الرموز", callback_data="schedule_settings")],
        [InlineKeyboardButton("تنسيق رسائل الرموز", callback_data="message_format")],
        [InlineKeyboardButton("إدارة محاولات النسخ", callback_data="manage_attempts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "مرحباً بك في لوحة تحكم المسؤول\n"
        "اختر أحد الخيارات أدناه:",
        reply_markup=reply_markup
    )

# عرض إدارة المجموعات
async def show_manage_groups(query, context):
    config = load_config()
    
    keyboard = []
    for group_id, group_data in config["groups"].items():
        secret = group_data.get("totp_secret", "")
        secret_display = secret[:5] + "..." + secret[-5:] if len(secret) > 10 else secret
        keyboard.append([
            InlineKeyboardButton(f"المجموعة: {group_id} | Secret: {secret_display}", callback_data=f"edit_group:{group_id}")
        ])
        keyboard.append([
            InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_group:{group_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="add_group")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "إدارة المجموعات والـTOTP\n"
        "اختر مجموعة للتعديل أو إضافة مجموعة جديدة:",
        reply_markup=reply_markup
    )

# عرض إعدادات الجدولة
async def show_schedule_settings(query, context):
    config = load_config()
    
    keyboard = []
    for group_id, group_data in config["groups"].items():
        interval = group_data.get("interval_minutes", 10)
        active = group_data.get("active", False)
        status = "✅ نشط" if active else "❌ متوقف"
        
        keyboard.append([
            InlineKeyboardButton(f"المجموعة: {group_id} | كل {interval} دقائق | {status}", callback_data=f"set_interval:{group_id}")
        ])
        
        toggle_text = "إيقاف" if active else "تشغيل"
        toggle_value = "false" if active else "true"
        keyboard.append([
            InlineKeyboardButton(f"{toggle_text} الإرسال", callback_data=f"toggle_active:{group_id}:{toggle_value}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "إعدادات جدولة الرموز\n"
        "اختر مجموعة لتعديل إعدادات الجدولة:",
        reply_markup=reply_markup
    )

# عرض تنسيق الرسائل
async def show_message_format(query, context):
    config = load_config()
    
    keyboard = []
    for group_id, group_data in config["groups"].items():
        format_num = group_data.get("message_format", 2)
        timezone_str = group_data.get("timezone", "UTC")
        
        format_names = {
            1: "الشكل الأول",
            2: "الشكل الثاني",
            3: "الشكل الثالث"
        }
        
        keyboard.append([
            InlineKeyboardButton(f"المجموعة: {group_id} | {format_names[format_num]} | {timezone_str}", callback_data=f"group_format:{group_id}")
        ])
        
        keyboard.append([
            InlineKeyboardButton("الشكل الأول", callback_data=f"set_format:{group_id}:1"),
            InlineKeyboardButton("الشكل الثاني", callback_data=f"set_format:{group_id}:2"),
            InlineKeyboardButton("الشكل الثالث", callback_data=f"set_format:{group_id}:3")
        ])
        
        keyboard.append([
            InlineKeyboardButton("توقيت غرينتش", callback_data=f"set_timezone:{group_id}:UTC"),
            InlineKeyboardButton("توقيت غزة", callback_data=f"set_timezone:{group_id}:Gaza")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    format_examples = (
        "🔹 الشكل الأول:\n"
        "🔐 2FA Verification Code\n\n"
        "Next code at: 07:05:34 PM\n\n"
        
        "🔹 الشكل الثاني:\n"
        "🔐 2FA Verification Code\n\n"
        "Next code in: 10 minutes\n\n"
        "Next code at: 07:05:34 PM\n\n"
        
        "🔹 الشكل الثالث:\n"
        "🔐 2FA Verification Code\n\n"
        "Next code in: 10 minutes\n"
        "Correct Time: 06:55:34 PM\n"
        "Next Code at: 07:05:34 PM"
    )
    
    await query.edit_message_text(
        f"تنسيق رسائل الرموز\n"
        f"اختر تنسيق الرسالة والتوقيت لكل مجموعة:\n\n"
        f"{format_examples}",
        reply_markup=reply_markup
    )

# عرض إدارة محاولات النسخ
async def show_manage_attempts(query, context):
    attempts = load_attempts()
    
    keyboard = []
    
    # عرض الإعدادات الافتراضية
    default_attempts = attempts.get("default_attempts", 3)
    keyboard.append([
        InlineKeyboardButton(f"عدد المحاولات الافتراضي: {default_attempts}", callback_data="set_attempts:default:view")
    ])
    keyboard.append([
        InlineKeyboardButton("➖", callback_data="set_attempts:default:decrease"),
        InlineKeyboardButton("➕", callback_data="set_attempts:default:increase"),
    ])
    
    # عرض المستخدمين
    if attempts["users"]:
        keyboard.append([InlineKeyboardButton("--- المستخدمين ---", callback_data="dummy")])
        
        for user_id, user_data in attempts["users"].items():
            remaining = user_data.get("remaining", 0)
            name = user_data.get("name", "مستخدم")
            keyboard.append([
                InlineKeyboardButton(f"{name} ({user_id}) | المتبقي: {remaining}", callback_data=f"select_user:{user_id}:{name}")
            ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "إدارة محاولات النسخ\n"
        "يمكنك تعديل عدد المحاولات الافتراضي أو إدارة محاولات مستخدم محدد:",
        reply_markup=reply_markup
    )

# عرض إدارة محاولات مستخدم محدد
async def show_user_attempts_management(query, context, user_info):
    parts = user_info.split(":", 1)
    user_id = parts[0]
    name = parts[1] if len(parts) > 1 else "مستخدم"
    
    attempts = load_attempts()
    user_data = attempts["users"].get(user_id, {"remaining": 0})
    remaining = user_data.get("remaining", 0)
    
    keyboard = [
        [InlineKeyboardButton(f"المستخدم: {name} | المتبقي: {remaining}", callback_data="dummy")],
        [
            InlineKeyboardButton("➖", callback_data=f"set_attempts:{user_id}:decrease"),
            InlineKeyboardButton("➕", callback_data=f"set_attempts:{user_id}:increase"),
        ],
        [
            InlineKeyboardButton("تعيين إلى 0", callback_data=f"set_attempts:{user_id}:zero"),
            InlineKeyboardButton("إعادة تعيين", callback_data=f"set_attempts:{user_id}:reset"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_attempts")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"إدارة محاولات المستخدم: {name}\n"
        f"يمكنك زيادة أو تقليل عدد المحاولات المتبقية:",
        reply_markup=reply_markup
    )

# إدارة محاولات المستخدم
async def manage_user_attempts(query, context, user_id, action):
    attempts = load_attempts()
    
    if user_id == "default":
        default_attempts = attempts.get("default_attempts", 3)
        
        if action == "increase":
            attempts["default_attempts"] = min(default_attempts + 1, 10)
        elif action == "decrease":
            attempts["default_attempts"] = max(default_attempts - 1, 1)
        
        save_attempts(attempts)
        await show_manage_attempts(query, context)
        return
    
    if user_id not in attempts["users"]:
        attempts["users"][user_id] = {
            "remaining": 0,
            "name": "مستخدم"
        }
    
    user_data = attempts["users"][user_id]
    remaining = user_data.get("remaining", 0)
    name = user_data.get("name", "مستخدم")
    
    if action == "increase":
        user_data["remaining"] = min(remaining + 1, 10)
    elif action == "decrease":
        user_data["remaining"] = max(remaining - 1, 0)
    elif action == "zero":
        user_data["remaining"] = 0
    elif action == "reset":
        user_data["remaining"] = attempts.get("default_attempts", 3)
    
    save_attempts(attempts)
    await show_user_attempts_management(query, context, f"{user_id}:{name}")

# حذف مجموعة
async def delete_group(query, context, group_id):
    config = load_config()
    
    if group_id in config["groups"]:
        del config["groups"][group_id]
        save_config(config)
        
        # إيقاف المهام المجدولة للمجموعة
        current_jobs = context.job_queue.get_jobs_by_name(f"send_code_{group_id}")
        for job in current_jobs:
            job.schedule_removal()
    
    await show_manage_groups(query, context)

# تبديل حالة نشاط المجموعة
async def toggle_group_active(query, context, group_id, new_state):
    config = load_config()
    
    if group_id in config["groups"]:
        config["groups"][group_id]["active"] = new_state
        save_config(config)
        
        # إيقاف المهام المجدولة الحالية
        current_jobs = context.job_queue.get_jobs_by_name(f"send_code_{group_id}")
        for job in current_jobs:
            job.schedule_removal()
        
        # إذا تم التفعيل، قم بجدولة مهمة جديدة
        if new_state:
            interval_minutes = config["groups"][group_id].get("interval_minutes", 10)
            context.job_queue.run_once(
                send_auth_code,
                1,  # بدء بعد ثانية واحدة
                data={"group_id": group_id},
                name=f"send_code_{group_id}"
            )
    
    await show_schedule_settings(query, context)

# تعيين تنسيق الرسالة
async def set_message_format(query, context, group_id, format_num):
    config = load_config()
    
    if group_id in config["groups"]:
        config["groups"][group_id]["message_format"] = format_num
        save_config(config)
    
    await show_message_format(query, context)

# تعيين المنطقة الزمنية
async def set_timezone(query, context, group_id, timezone_str):
    config = load_config()
    
    if group_id in config["groups"]:
        config["groups"][group_id]["timezone"] = timezone_str
        save_config(config)
    
    await show_message_format(query, context)

# معالجة زر نسخ الرمز
async def handle_copy_code(query, context, group_id):
    config = load_config()
    attempts = load_attempts()
    user_id = str(query.from_user.id)
    user_name = query.from_user.full_name
    
    # التحقق من وجود المجموعة
    if group_id not in config["groups"]:
        await query.edit_message_text("عذراً، المجموعة غير موجودة.")
        return
    
    # التحقق من المحاولات المتبقية
    if user_id not in attempts["users"]:
        attempts["users"][user_id] = {
            "remaining": attempts.get("default_attempts", 3),
            "name": user_name
        }
    
    user_data = attempts["users"][user_id]
    remaining = user_data.get("remaining", 0)
    
    if remaining <= 0:
        await query.answer("لا توجد محاولات متبقية. حاول مرة أخرى بعد منتصف الليل.", show_alert=True)
        return
    
    # تقليل عدد المحاولات المتبقية
    user_data["remaining"] -= 1
    save_attempts(attempts)
    
    # توليد الرمز
    secret = config["groups"][group_id].get("totp_secret", "")
    if not secret:
        await query.answer("لم يتم تكوين TOTP_SECRET لهذه المجموعة.", show_alert=True)
        return
    
    code = generate_totp_code(secret)
    remaining_attempts = user_data["remaining"]
    
    # إرسال الرمز في رسالة خاصة
    message_text = (
        f"🔐 رمز المصادقة 2FA\n\n"
        f"{code}\n\n"
        f"⚠️ صالح لمدة 30 ثانية فقط!\n"
        f"عدد المحاولات المتبقية: {remaining_attempts}"
    )
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=message_text
        )
        await query.answer("تم إرسال الرمز في رسالة خاصة.", show_alert=True)
    except Exception as e:
        logger.error(f"خطأ في إرسال الرمز إلى المستخدم {user_id}: {e}")
        await query.answer("حدث خطأ في إرسال الرمز. تأكد من بدء محادثة مع البوت أولاً.", show_alert=True)

# معالجة الرسائل النصية (لإدخال البيانات)
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    user_id = str(update.effective_user.id)
    
    if not is_admin(user_id, config):
        return
    
    if "action" not in context.user_data:
        return
    
    action = context.user_data["action"]
    text = update.message.text
    
    if action == "add_group":
        group_id = text.strip()
        context.user_data["group_id"] = group_id
        context.user_data["action"] = "add_group_secret"
        
        await update.message.reply_text(
            f"تم تحديد معرف المجموعة: {group_id}\n"
            f"الرجاء إدخال TOTP_SECRET للمجموعة:"
        )
    
    elif action == "add_group_secret":
        group_id = context.user_data.get("group_id", "")
        secret = text.strip()
        
        if not group_id:
            await update.message.reply_text("حدث خطأ. الرجاء المحاولة مرة أخرى.")
            return
        
        config["groups"][group_id] = {
            "totp_secret": secret,
            "interval_minutes": 10,
            "message_format": 2,
            "timezone": "UTC",
            "active": False
        }
        
        save_config(config)
        del context.user_data["action"]
        del context.user_data["group_id"]
        
        await update.message.reply_text(
            f"تم إضافة المجموعة {group_id} بنجاح مع TOTP_SECRET."
        )
        
        # عرض لوحة التحكم مرة أخرى
        await admin_panel(update, context)
    
    elif action == "edit_group":
        group_id = context.user_data.get("group_id", "")
        secret = text.strip()
        
        if not group_id or group_id not in config["groups"]:
            await update.message.reply_text("حدث خطأ. الرجاء المحاولة مرة أخرى.")
            return
        
        config["groups"][group_id]["totp_secret"] = secret
        save_config(config)
        del context.user_data["action"]
        del context.user_data["group_id"]
        
        await update.message.reply_text(
            f"تم تحديث TOTP_SECRET للمجموعة {group_id} بنجاح."
        )
        
        # عرض لوحة التحكم مرة أخرى
        await admin_panel(update, context)
    
    elif action == "set_interval":
        group_id = context.user_data.get("group_id", "")
        
        try:
            interval = int(text.strip())
            if interval < 1:
                raise ValueError("يجب أن يكون الفاصل الزمني أكبر من صفر")
        except ValueError:
            await update.message.reply_text("الرجاء إدخال رقم صحيح أكبر من صفر.")
            return
        
        if not group_id or group_id not in config["groups"]:
            await update.message.reply_text("حدث خطأ. الرجاء المحاولة مرة أخرى.")
            return
        
        config["groups"][group_id]["interval_minutes"] = interval
        save_config(config)
        
        # إعادة جدولة المهام إذا كانت المجموعة نشطة
        if config["groups"][group_id].get("active", False):
            current_jobs = context.job_queue.get_jobs_by_name(f"send_code_{group_id}")
            for job in current_jobs:
                job.schedule_removal()
            
            context.job_queue.run_once(
                send_auth_code,
                1,  # بدء بعد ثانية واحدة
                data={"group_id": group_id},
                name=f"send_code_{group_id}"
            )
        
        del context.user_data["action"]
        del context.user_data["group_id"]
        
        await update.message.reply_text(
            f"تم تحديث الفاصل الزمني للمجموعة {group_id} إلى {interval} دقائق بنجاح."
        )
        
        # عرض لوحة التحكم مرة أخرى
        await admin_panel(update, context)

# النقطة الرئيسية للبرنامج
def main():
    # إنشاء تطبيق البوت
    application = Application.builder().token(TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # إضافة معالج الأزرار
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # إضافة معالج الرسائل النصية
    application.add_handler(MessageHandler(None, handle_text_input))
    
    # جدولة إعادة تعيين المحاولات اليومية عند منتصف الليل
    job_queue = application.job_queue
    now = datetime.datetime.now(pytz.timezone("UTC"))
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    delay = (tomorrow - now).total_seconds()
    
    job_queue.run_once(reset_daily_attempts, delay)
    
    # بدء المهام المجدولة للمجموعات النشطة
    config = load_config()
    for group_id, group_data in config["groups"].items():
        if group_data.get("active", False):
            job_queue.run_once(
                send_auth_code,
                1,  # بدء بعد ثانية واحدة
                data={"group_id": group_id},
                name=f"send_code_{group_id}"
            )
    
    # بدء البوت
    application.run_polling()

if __name__ == "__main__":
    main()

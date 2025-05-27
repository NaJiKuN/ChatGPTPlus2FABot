#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تليجرام لإرسال رموز المصادقة 2FA
يقوم بإرسال رمز مصادقة 2FA من خلال الـTOTP_SECRET كل 10 دقائق افتراضياً
أو وقت يحدد من قبل المسؤول الى مجموعة خاصة
"""

import os
import json
import time
import pyotp
import logging
import datetime
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

# تكوين نظام التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# المتغيرات الأساسية
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
DEFAULT_ADMIN_ID = "764559466"
DEFAULT_GROUP_ID = "-1002329495586"

# حالات المحادثة
(
    ADMIN_MENU,
    ADD_GROUP,
    ADD_TOTP,
    SET_INTERVAL,
    CUSTOMIZE_MESSAGE,
    SET_ATTEMPTS,
    SELECT_GROUP,
    SELECT_TIMEZONE,
    SELECT_TIME_FORMAT,
    ADD_ADMIN,
    REMOVE_ADMIN,
    REMOVE_GROUP,
    TOGGLE_GROUP_STATUS,
    WAITING_FOR_MANUAL_SEND,
    TOGGLE_MESSAGE_OPTIONS,
) = range(15)

# ملفات البيانات
CONFIG_FILE = "config.json"
USERS_FILE = "users.json"

# القيم الافتراضية
DEFAULT_CONFIG = {
    "admins": [DEFAULT_ADMIN_ID],
    "groups": {
        DEFAULT_GROUP_ID: {
            "totp_secret": "",
            "interval": 10,  # بالدقائق
            "active": False,
            "timezone": "UTC",  # UTC أو Palestine
            "time_format": 12,  # 12 أو 24
            "message_format": {
                "line1": "🔐 2FA Verification Code",
                "line2": "",
                "show_current_time": True,
                "show_next_code_in": True,
                "show_next_code_at": True
            },
            "max_attempts": 3  # عدد المحاولات المسموحة لكل مستخدم يومياً
        }
    }
}

DEFAULT_USERS = {}

# متغيرات عالمية لتخزين البيانات
config = {}
users = {}
active_tasks = {}  # لتخزين مهام الجدولة النشطة

# دوال مساعدة للتعامل مع الملفات
def load_data():
    """تحميل البيانات من الملفات"""
    global config, users
    
    # تحميل ملف الإعدادات
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        config = DEFAULT_CONFIG
        save_config()
    
    # تحميل ملف المستخدمين
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
    else:
        users = DEFAULT_USERS
        save_users()

def save_config():
    """حفظ الإعدادات في الملف"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def save_users():
    """حفظ بيانات المستخدمين في الملف"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً"""
    return str(user_id) in config.get("admins", [DEFAULT_ADMIN_ID])

def get_current_time(timezone="UTC"):
    """الحصول على الوقت الحالي بناءً على المنطقة الزمنية"""
    now = datetime.datetime.now(datetime.timezone.utc)
    
    if timezone == "Palestine":
        # توقيت فلسطين (UTC+3)
        now = now + datetime.timedelta(hours=3)
    
    return now

def format_time(dt, time_format=12):
    """تنسيق الوقت بناءً على تفضيلات المستخدم"""
    if time_format == 12:
        return dt.strftime("%I:%M:%S %p")  # 12-hour format with AM/PM
    else:
        return dt.strftime("%H:%M:%S")  # 24-hour format

def generate_totp_code(totp_secret):
    """توليد رمز TOTP باستخدام السر المقدم"""
    if not totp_secret:
        return "لم يتم تكوين TOTP_SECRET"
    
    totp = pyotp.TOTP(totp_secret)
    return totp.now()

def get_totp_remaining_seconds(totp_secret):
    """الحصول على عدد الثواني المتبقية لصلاحية الرمز الحالي"""
    if not totp_secret:
        return 0
    
    totp = pyotp.TOTP(totp_secret)
    return totp.interval - datetime.datetime.now().timestamp() % tot

# دوال إدارة المجموعات والمسؤولين
def add_group(group_id):
    """إضافة مجموعة جديدة إلى الإعدادات"""
    if group_id not in config["groups"]:
        config["groups"][group_id] = {
            "totp_secret": "",
            "interval": 10,
            "active": False,
            "timezone": "UTC",
            "time_format": 12,
            "message_format": {
                "line1": "🔐 2FA Verification Code",
                "line2": "",
                "show_current_time": True,
                "show_next_code_in": True,
                "show_next_code_at": True
            },
            "max_attempts": 3
        }
        save_config()
        return True
    return False

def remove_group(group_id):
    """حذف مجموعة من الإعدادات"""
    if group_id in config["groups"]:
        # إيقاف أي مهام جدولة مرتبطة بالمجموعة
        stop_scheduled_task(group_id)
        
        # حذف المجموعة من الإعدادات
        del config["groups"][group_id]
        save_config()
        
        # حذف بيانات المستخدمين المرتبطة بالمجموعة
        for user_id in list(users.keys()):
            if group_id in users[user_id]:
                del users[user_id][group_id]
                # إذا لم يعد لدى المستخدم أي مجموعات، قم بحذفه
                if not users[user_id]:
                    del users[user_id]
        save_users()
        return True
    return False

def set_group_totp(group_id, totp_secret):
    """تعيين سر TOTP للمجموعة"""
    if group_id in config["groups"]:
        config["groups"][group_id]["totp_secret"] = totp_secret
        save_config()
        return True
    return False

def set_group_interval(group_id, interval):
    """تعيين الفاصل الزمني لإرسال الرموز للمجموعة"""
    if group_id in config["groups"]:
        config["groups"][group_id]["interval"] = interval
        save_config()
        
        # إعادة جدولة المهمة إذا كانت المجموعة نشطة
        if config["groups"][group_id]["active"]:
            stop_scheduled_task(group_id)
            start_scheduled_task(group_id)
        return Katrina

def toggle_group_status(group_id):
    """تبديل حالة نشاط المجموعة"""
    if group_id in config["groups"]:
        current_status = config["groups"][group_id]["active"]
        config["groups"][group_id]["active"] = not current_status
        save_config()
        
        if config["groups"][group_id]["active"]:
            # إذا تم تفعيل المجموعة، ابدأ المهمة المجدولة
            start_scheduled_task(group_id)
        else:
            # إذا تم تعطيل المجموعة، أوقف المهمة المجدولة
            stop_scheduled_task(group_id)
        
        return not current_status
    return None

def set_group_timezone(group_id, timezone):
    """تعيين المنطقة الزمنية للمجموعة"""
    if group_id in config["groups"] and timezone in ["UTC", "Palestine"]:
        config["groups"][group_id]["timezone"] = timezone
        save_config()
        return True
    return False

def set_group_time_format(group_id, time_format):
    """تعيين تنسيق الوقت للمجموعة"""
    if group_id in config["groups"] and time_format in [12, 24]:
        config["groups"][group_id]["time_format"] = time_format
        save_config()
        return True
    return False

def set_group_message_format(group_id, message_format):
    """تعيين تنسيق الرسالة للمجموعة"""
    if group_id in config["groups"]:
        config["groups"][group_id]["message_format"] = message_format
        save_config()
        return True
    return False

def toggle_message_option(group_id, option):
    """تبديل خيار عرض عنصر في الرسالة"""
    if group_id in config["groups"] and option in ["show_current_time", "show_next_code_in", "show_next_code_at"]:
        current_value = config["groups"][group_id]["message_format"][option]
        config["groups"][group_id]["message_format"][option] = not current_value
        save_config()
        return not current_value
    return None

def set_group_max_attempts(group_id, max_attempts):
    """تعيين الحد الأقصى لعدد المحاولات اليومية للمجموعة"""
    if group_id in config["groups"]:
        config["groups"][group_id]["max_attempts"] = max_attempts
        save_config()
        return True
    return False

def add_admin(admin_id):
    """إضافة مسؤول جديد"""
    if admin_id not in config["admins"]:
        config["admins"].append(admin_id)
        save_config()
        return True
    return False

def remove_admin(admin_id):
    """إزالة مسؤول"""
    if admin_id in config["admins"] and len(config["admins"]) > 1:
        config["admins"].remove(admin_id)
        save_config()
        return True
    return False

def get_user_attempts(user_id, group_id):
    """الحصول على عدد محاولات المستخدم اليومية للمجموعة"""
    user_id = str(user_id)
    if user_id not in users:
        users[user_id] = {}
    
    if group_id not in users[user_id]:
        users[user_id][group_id] = {
            "attempts_today": 0,
            "total_attempts": 0
        }
        save_users()
    
    return users[user_id][group_id]["attempts_today"]

def increment_user_attempts(user_id, group_id):
    """زيادة عدد محاولات المستخدم اليومية للمجموعة"""
    user_id = str(user_id)
    if user_id not in users:
        users[user_id] = {}
    
    if group_id not in users[user_id]:
        users[user_id][group_id] = {
            "attempts_today": 0,
            "total_attempts": 0
        }
    
    users[user_id][group_id]["attempts_today"] += 1
    users[user_id][group_id]["total_attempts"] += 1
    save_users()
    
    return users[user_id][group_id]["attempts_today"]

# دوال إرسال رموز 2FA
async def send_2fa_code(context: ContextTypes.DEFAULT_TYPE, group_id):
    """إرسال رمز 2FA إلى المجموعة"""
    if group_id not in config["groups"]:
        logger.error(f"المجموعة {group_id} غير موجودة")
        return False
    
    group_config = config["groups"][group_id]
    totp_secret = group_config["totp_secret"]
    
    if not totp_secret:
        logger.error(f"لم يتم تكوين TOTP_SECRET للمجموعة {group_id}")
        return False
    
    # توليد رمز 2FA
    code = generate_totp_code(totp_secret)
    
    # الحصول على الوقت الحالي والوقت التالي
    timezone = group_config["timezone"]
    time_format = group_config["time_format"]
    interval = group_config["interval"]
    
    current_time = get_current_time(timezone)
    next_time = current_time + datetime.timedelta(minutes=interval)
    
    formatted_current_time = format_time(current_time, time_format)
    formatted_next_time = format_time(next_time, time_format)
    
    # إنشاء نص الرسالة
    message_format = group_config["message_format"]
    message_text = message_format["line1"] + "\n\n"
    
    if message_format["line2"]:
        message_text += message_format["line2"] + "\n\n"
    
    if message_format["show_current_time"]:
        message_text += f"Current time: {formatted_current_time}\n"
    
    if message_format["show_next_code_in"]:
        message_text += f"Next code in: {interval} minutes\n"
    
    if message_format["show_next_code_at"]:
        message_text += f"Next code at: {formatted_next_time}\n"
    
    # إنشاء زر Copy Code
    keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال الرسالة إلى المجموعة
    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=message_text,
            reply_markup=reply_markup
        )
        logger.info(f"تم إرسال رمز 2FA إلى المجموعة {group_id}")
        return True
    except Exception as e:
        logger.error(f"فشل في إرسال رمز 2FA إلى المجموعة {group_id}: {str(e)}")
        return False

async def copy_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النقر على زر Copy Code"""
    query = update.callback_query
    await query.answer()
    
    # استخراج معرف المجموعة من البيانات
    group_id = query.data.replace("copy_code_", "")
    user_id = str(query.from_user.id)
    
    if group_id not in config["groups"]:
        await query.message.reply_text("حدث خطأ: المجموعة غير موجودة.")
        return
    
    group_config = config["groups"][group_id]
    max_attempts = group_config["max_attempts"]
    
    # التحقق من عدد المحاولات المتبقية
    current_attempts = get_user_attempts(user_id, group_id)
    
    if current_attempts >= max_attempts:
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ لقد استنفدت جميع محاولاتك اليومية. يرجى المحاولة غداً."
        )
        return
    
    # زيادة عدد المحاولات
    new_attempts = increment_user_attempts(user_id, group_id)
    remaining_attempts = max_attempts - new_attempts
    
    # توليد رمز 2FA
    totp_secret = group_config["totp_secret"]
    code = generate_totp_code(totp_secret)
    
    # حساب الوقت المتبقي لصلاحية الرمز
    remaining_seconds = int(get_totp_remaining_seconds(totp_secret))
    
    # إرسال الرمز إلى المستخدم في رسالة خاصة
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🔐 رمز المصادقة 2FA\n\n{code}\n\n⚠️ صالح لمدة {remaining_seconds} ثانية فقط!\nعدد المحاولات المتبقية: {remaining_attempts}"
        )
        logger.info(f"تم إرسال رمز 2FA إلى المستخدم {user_id}")
    except Exception as e:
        logger.error(f"فشل في إرسال رمز 2FA إلى المستخدم {user_id}: {str(e)}")

def start_scheduled_task(group_id):
    """بدء مهمة مجدولة لإرسال رموز 2FA"""
    # ملاحظة: هذه الوظيفة تستخدم فقط للإرسال اليدوي من قبل المسؤول
    # نظراً لأن المهام المجدولة غير مدعومة حالياً
    pass

def stop_scheduled_task(group_id):
    """إيقاف مهمة مجدولة لإرسال رموز 2FA"""
    # ملاحظة: هذه الوظيفة تستخدم فقط للإرسال اليدوي من قبل المسؤول
    # نظراً لأن المهام المجدولة غير مدعومة حالياً
    pass

async def manual_send_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رمز 2FA يدوياً من قبل المسؤول"""
    query = update.callback_query
    if query:
        await query.answer()
        
        if query.data == "back_to_admin":
            # العودة إلى قائمة المسؤول الرئيسية
            return await admin_command(update, context)
        
        # استخراج معرف المجموعة من البيانات
        group_id = query.data.replace("send_code_", "")
        
        # إرسال الرمز
        success = await send_2fa_code(context, group_id)
        
        # إظهار رسالة تأكيد
        if success:
            await query.edit_message_text(
                f"تم إرسال رمز 2FA إلى المجموعة {group_id} بنجاح."
            )
        else:
            await query.edit_message_text(
                f"فشل في إرسال رمز 2FA إلى المجموعة {group_id}. تأكد من أن البوت عضو في المجموعة ولديه صلاحيات الإرسال."
            )
        
        # العودة إلى قائمة المسؤول بعد ثانيتين
        await asyncio.sleep(2)
        return await admin_command(update, context)
    
    # إذا وصلنا إلى هنا، فهناك خطأ ما
    await update.message.reply_text("حدث خطأ. الرجاء المحاولة مرة أخرى.")
    return ConversationHandler.END

# دوال البوت الأساسية
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"مرحباً {user.first_name}! هذا بوت مصادقة 2FA.\n"
        f"إذا كنت مسؤولاً، يمكنك استخدام الأمر /admin للوصول إلى لوحة التحكم."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /admin"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("عذراً",
        " هذا الأمر متاح للمسؤولين فقط.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("إضافة/تعديل مجموعة", callback_data="add_group")],
        [InlineKeyboardButton("حذف مجموعة", callback_data="remove_group")],
        [InlineKeyboardButton("تفعيل/تعطيل مجموعة", callback_data="toggle_group")],
        [InlineKeyboardButton("تعيين فاصل زمني لإرسال الرموز", callback_data="set_interval")],
        [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data="customize_message")],
        [InlineKeyboardButton("تعيين عدد المحاولات المسموحة", callback_data="set_attempts")],
        [InlineKeyboardButton("إرسال رمز 2FA يدوياً", callback_data="manual_send")],
        [InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin")],
        [InlineKeyboardButton("إزالة مسؤول", callback_data="remove_admin")],
        [InlineKeyboardButton("إلغاء", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "مرحباً بك في لوحة تحكم المسؤول. الرجاء اختيار إحدى الخيارات:",
        reply_markup=reply_markup
    )
    
    return ADMIN_MENU

async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيارات قائمة المسؤول"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_group":
        await query.edit_message_text(
            "الرجاء إدخال معرف المجموعة الخاصة (مثال: -1002329495586):"
        )
        return ADD_GROUP
    elif query.data == "remove_group":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "remove_group")
    elif query.data == "toggle_group":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "toggle_group")
    elif query.data == "set_interval":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "set_interval")
    elif query.data == "customize_message":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "customize_message")
    elif query.data == "set_attempts":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "set_attempts")
    elif query.data == "manual_send":
        # عرض قائمة المجموعات للاختيار
        return await show_group_selection(update, context, "manual_send")
    elif query.data == "add_admin":
        await query.edit_message_text(
            "الرجاء إدخال معرف المسؤول الجديد (مثال: 764559466):"
        )
        return ADD_ADMIN
    elif query.data == "remove_admin":
        # عرض قائمة المسؤولين للاختيار
        keyboard = []
        for admin_id in config["admins"]:
            keyboard.append([InlineKeyboardButton(f"المسؤول: {admin_id}", callback_data=f"remove_admin_{admin_id}")])
        
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_admin")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "الرجاء اختيار المسؤول الذي ترغب في إزالته:",
            reply_markup=reply_markup
        )
        return REMOVE_ADMIN
    elif query.data == "cancel":
        await query.edit_message_text("تم إلغاء العملية.")
        return ConversationHandler.END
    elif query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)

async def show_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, next_action):
    """عرض قائمة المجموعات للاختيار"""
    query = update.callback_query
    
    # حفظ الإجراء التالي في سياق المحادثة
    context.user_data["next_action"] = next_action
    
    keyboard = []
    for group_id in config["groups"]:
        status = "✅" if config["groups"][group_id]["active"] else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{status} المجموعة: {group_id}",
            callback_data=f"select_group_{group_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "الرجاء اختيار المجموعة:",
        reply_markup=reply_markup
    )
    return SELECT_GROUP

async def select_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المجموعة"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    # استخراج معرف المجموعة من البيانات
    group_id = query.data.replace("select_group_", "")
    context.user_data["selected_group"] = group_id
    
    next_action = context.user_data.get("next_action")
    
    if next_action == "remove_group":
        keyboard = [
            [InlineKeyboardButton("نعم، حذف المجموعة", callback_data="confirm_remove_group")],
            [InlineKeyboardButton("لا، إلغاء", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"هل أنت متأكد من حذف المجموعة {group_id}؟",
            reply_markup=reply_markup
        )
        return REMOVE_GROUP
    elif next_action == "toggle_group":
        current_status = config["groups"][group_id]["active"]
        new_status = "تعطيل" if current_status else "تفعيل"
        
        keyboard = [
            [InlineKeyboardButton(f"نعم، {new_status} المجموعة", callback_data="id")],
            [InlineKeyboardButton("لا، إلغاء", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"هل ترغب في {new_status} المجموعة {group_id}؟",
            reply_markup=reply_markup
        )
        return TOGGLE_GROUP_STATUS
    elif next_action == "set_interval":
        Ascendancy (minutes=10)
        keyboard = []
        for interval in [1, 5, 10, 15, 30, 60]:
            keyboard.append([InlineKeyboardButton(
                f"{interval} دقيقة",
                callback_data=f"interval_{interval}"
            )])
        
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_admin")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        current_interval = config["groups"][group_id]["interval"]
        
        await query.edit_message_text(
            f"الفاصل الزمني الحالي: {current_interval} دقيقة\n"
            f"الرجاء اختيار الفاصل الزمني الجديد لإرسال الرموز:",
            reply_markup=reply_markup
        )
        return SET_INTERVAL
    elif next_action == "customize_message":
        # سيتم تنفيذ هذا في الخطوة التالية
        keyboard = [
            [InlineKeyboardButton("تعديل السطر الأول", callback_data="edit_line1")],
            [InlineKeyboardButton("تعديل السطر الثاني", callback_data="edit_line2")],
            [InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data="change_timezone")],
            [InlineKeyboardButton("تغيير تنسيق الوقت", callback_data="change_time_format")],
            [InlineKeyboardButton("تغيير خيارات عرض الرسالة", callback_data="toggle_message_options")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        group_config = config["groups"][group_id]
        timezone = group_config["timezone"]
        time_format = group_config["time_format"]
        line1 = group_config["message_format"]["line1"]
        line2 = group_config["message_format"]["line2"]
        
        await query.edit_message_text(
            f"إعدادات الرسالة الحالية للمجموعة {group_id}:\n\n"
            f"السطر الأول: {line1}\n"
            f"السطر الثاني: {line2}\n"
            f"المنطقة الزمنية: {timezone}\n"
            f"تنسيق الوقت: {time_format} ساعة\n\n"
            f"الرجاء اختيار الإعداد الذي ترغب في تغييره:",
            reply_markup=reply_markup
        )
        return CUSTOMIZE_MESSAGE
    elif next_action == "set_attempts":
        keyboard = []
        for attempts in [1, 3, 5, 10, 15, 20, 30, 50]:
            keyboard.append([InlineKeyboardButton(
                f"{attempts} محاولة",
                callback_data=f"attempts_{attempts}"
            )])
        
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_admin")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        current_attempts = config["groups"][group_id]["max_attempts"]
        
        await query.edit_message_text(
            f"الحد الأقصى الحالي للمحاولات: {current_attempts}\n"
            f"الرجاء اختيار الحد الأقصى الجديد للمحاولات اليومية:",
            reply_markup=reply_markup
        )
        return SET_ATTEMPTS
    elif next_action == "manual_send":
        keyboard = [
            [InlineKeyboardButton("نعم، إرسال الرمز الآن", callback_data=f"send_code_{group_id}")],
            [InlineKeyboardButton("لا، إلغاء", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"هل ترغب في إرسال رمز 2FA إلى المجموعة {group_id} الآن؟",
            reply_markup=reply_markup
        )
        return WAITING_FOR_MANUAL_SEND
    
    # إذا وصلنا إلى هنا، فهناك خطأ ما
    await query.edit_message_text("حدث خطأ. الرجاء المحاولة مرة أخرى.")
    return ConversationHandler.END

async def add_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة مجموعة جديدة"""
    group_id = update.message.text.strip()
    
    # التحقق من صحة معرف المجموعة
    if not group_id.startswith("-"):
        await update.message.reply_text(
            "معرف المجموعة غير صالح. يجب أن يبدأ بعلامة سالب (-). الرجاء المحاولة مرة أخرى."
        )
        return ADD_GROUP
    
    # إضافة المجموعة
    result = add_group(group_id)
    
    if result:
        await update.message.reply_text(
            f"تمت إضافة المجموعة {group_id} بنجاح.\n"
            f"الآن، الرجاء إدخال TOTP_SECRET للمجموعة:"
        )
        context.user_data["new_group_id"] = group_id
        return ADD_TOTP
    else:
        await update.message.reply_text(
            f"المجموعة {group_id} موجودة بالفعل.\n"
            f"الرجاء إدخال TOTP_SECRET جديد للمجموعة:"
        )
        context.user_data["new_group_id"] = group_id
        return ADD_TOTP

async def add_totp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة TOTP_SECRET للمجموعة"""
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("new_group_id")
    
    # التحقق من صحة TOTP_SECRET
    try:
        # محاولة إنشاء كائن TOTP للتحقق من صحة السر
        totp = pyotp.TOTP(totp_secret)
        code = totp.now()  # هذا سيفشل إذا كان السر غير صالح
    except Exception as e:
        await update.message.reply_text(
            f"TOTP_SECRET غير صالح. الرجاء المحاولة مرة أخرى.\n"
            f"الخطأ: {str(e)}"
        )
        return ADD_TOTP
    
    # تعيين TOTP_SECRET للمجموعة
    set_group_totp(group_id, totp_secret)
    
    # عرض قائمة الفواصل الزمنية
    keyboard = []
    for interval in [1, 5, 10, 15, 30, 60]:
        keyboard.append([InlineKeyboardButton(
            f"{interval} دقيقة",
            callback_data=f"interval_{interval}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"تم تعيين TOTP_SECRET للمجموعة {group_id} بنجاح.\n"
        f"الرجاء اختيار الفاصل الزمني لإرسال الرموز:",
        reply_markup=reply_markup
    )
    
    return SET_INTERVAL

async def set_interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تعيين الفاصل الزمني"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    # استخراج الفاصل الزمني من البيانات
    interval = int(query.data.replace("interval_", ""))
    group_id = context.user_data.get("selected_group") or context.user_data.get("new_group_id")
    
    # تعيين الفاصل الزمني للمجموعة
    set_group_interval(group_id, interval)
    
    # إذا كانت مجموعة جديدة، اسأل عن تفعيلها
    if context.user_data.get("new_group_id"):
        keyboard = [
            [InlineKeyboardButton("نعم، تفعيل الآن", callback_data="activate_now")],
            [InlineKeyboardButton("لا، لاحقاً", callback_data="activate_later")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"تم تعيين الفاصل الزمني للمجموعة {group_id} إلى {interval} دقيقة بنجاح.\n"
            f"هل ترغب في تفعيل إرسال الرموز للمجموعة الآن؟",
            reply_markup=reply_markup
        )
        
        return TOGGLE_GROUP_STATUS
    else:
        await query.edit_message_text(
            f"تم تعيين الفاصل الزمني للمجموعة {group_id} إلى {interval} دقيقة بنجاح."
        )
        
        # العودة إلى قائمة المسؤول بعد ثانيتين
        await asyncio.sleep(2)
        return await admin_command(update, context)

async def toggle_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تفعيل/تعطيل المجموعة"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    group_id = context.user_data.get("selected_group") or context.user_data.get("new_group_id")
    
    if query.data in ["confirm_toggle_group", "activate_now"]:
        # تبديل حالة المجموعة
        new_status = toggle_group_status(group_id)
        status_text = "تفعيل" if new_status else "تعطيل"
        
        await query.edit_message_text(
            f"تم {status_text} المجموعة {group_id} بنجاح.\n\n"
            f"ملاحظة: نظراً لقيود النظام، يجب عليك إرسال الرموز يدوياً من قائمة المسؤول."
        )
    else:  # activate_later
        await query.edit_message_text(
            f"تم الاحتفاظ بالمجموعة {group_id} في حالة غير مفعلة."
        )
    
    # العودة إلى قائمة المسؤول بعد ثانيتين
    await asyncio.sleep(2)
    return await admin_command(update, context)

async def remove_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة حذف المجموعة"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    group_id = context.user_data.get("selected_group")
    
    if query.data == "confirm_remove_group":
        # حذف المجموعة
        result = remove_group(group_id)
        
        if result:
            await query.edit_message_text(
                f"تم حذف المجموعة {group_id} بنجاح."
            )
        else:
            await query.edit_message_text(
                f"فشل في حذف المجموعة {group_id}."
            )
    else:
        await query.edit_message_text(
            "تم إلغاء عملية الحذف."
        )
    
    # العودة إلى قائمة المسؤول بعد ثانيتين
    await asyncio.sleep(2)
    return await admin_command(update, context)

async def set_attempts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تعيين عدد المحاولات"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    # استخراج عدد المحاولات من البيانات
    attempts = int(query.data.replace("attempts_", ""))
    group_id = context.user_data.get("selected_group")
    
    # تعيين عدد المحاولات للمجموعة
    set_group_max_attempts(group_id, attempts)
    
    await query.edit_message_text(
        f"تم تعيين الحد الأقصى للمحاولات اليومية للمجموعة {group_id} إلى {attempts} محاولة بنجاح."
    )
    
    # العودة إلى قائمة المسؤول بعد ثانيتين
    await asyncio.sleep(2)
    return await admin_command(update, context)

async def customize_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تخصيص الرسالة"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    group_id = context.user_data.get("selected_group")
    
    if query.data == "edit_line1":
        await query.edit_message_text(
            f"الرجاء إدخال النص الجديد للسطر الأول:"
        )
        context.user_data["edit_field"] = "line1"
        return CUSTOMIZE_MESSAGE
    elif query.data == "edit_line2":
        await query.edit_message_text(
            f"الرجاء إدخال النص الجديد للسطر الثاني:"
        )
        context.user_data["edit_field"] = "line2"
        return CUSTOMIZE_MESSAGE
    elif query.data == "change_timezone":
        keyboard = [
            [InlineKeyboardButton("التوقيت العالمي (UTC)", callback_data="timezone_UTC")],
            [InlineKeyboardButton("توقيت فلسطين", callback_data="timezone_Palestine")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_customize")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"الرجاء اختيار المنطقة الزمنية:",
            reply_markup=reply_markup
        )
        return SELECT_TIMEZONE
    elif query.data == "change_time_format":
        keyboard = [
            [InlineKeyboardButton("تنسيق 12 ساعة", callback_data="time_format_12")],
            [InlineKeyboardButton("تنسيق 24 ساعة", callback_data="time_format_24")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_customize")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"الرجاء اختيار تنسيق الوقت:",
            reply_markup=reply_markup
        )
        return SELECT_TIME_FORMAT
    elif query.data == "toggle_message_options":
        # عرض خيارات عناصر الرسالة
        group_config = config["groups"][group_id]["message_format"]
        show_current_time = "✅" if group_config["show_current_time"] else "❌"
        show_next_code_in = "✅" if group_config["show_next_code_in"] else "❌"
        show_next_code_at = "✅" if group_config["show_next_code_at"] else "❌"
        
        keyboard = [
            [InlineKeyboardButton(f"{show_current_time} عرض الوقت الحالي", callback_data="toggle_show_current_time")],
            [InlineKeyboardButton(f"{show_next_code_in} عرض المدة المتبقية للرمز التالي", callback_data="toggle_show_next_code_in")],
            [InlineKeyboardButton(f"{show_next_code_at} عرض وقت الرمز التالي", callback_data="toggle_show_next_code_at")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_customize")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"خيارات عرض عناصر الرسالة للمجموعة {group_id}:\n"
            f"الرجاء اختيار العنصر الذي ترغب في تغيير حالته:",
            reply_markup=reply_markup
        )
        return TOGGLE_MESSAGE_OPTIONS
    elif query.data == "back_to_customize":
        # العودة إلى قائمة تخصيص الرسالة
        group_config = config["groups"][group_id]
        timezone = group_config["timezone"]
        time_format = group_config["time_format"]
        line1 = group_config["message_format"]["line1"]
        line2 = group_config["message_format"]["line2"]
        
        keyboard = [
            [InlineKeyboardButton("تعديل السطر الأول", callback_data="edit_line1")],
            [InlineKeyboardButton("تعديل السطر الثاني", callback_data="edit_line2")],
            [InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data="change_timezone")],
            [InlineKeyboardButton("تغيير تنسيق الوقت", callback_data="change_time_format")],
            [InlineKeyboardButton("تغيير خيارات عرض الرسالة", callback_data="toggle_message_options")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"إعدادات الرسالة الحالية للمجموعة {group_id}:\n\n"
            f"السطر الأول: {line1}\n"
            f"السطر الثاني: {line2}\n"
            f"المنطقة الزمنية: {timezone}\n"
            f"تنسيق الوقت: {time_format} ساعة\n\n"
            f"الرجاء اختيار الإعداد الذي ترغب في تغييره:",
            reply_markup=reply_markup
        )
        return CUSTOMIZE_MESSAGE

async def toggle_message_options_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تغيير خيارات عرض عناصر الرسالة"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_customize":
        # العودة إلى قائمة تخصيص الرسالة
        return await customize_message_handler(update, context)
    
    group_id = context.user_data.get("selected_group")
    
    if query.data.startswith("toggle_"):
        option = query.data.replace("toggle_", "")
        new_value = toggle_message_option(group_id, option)
        
        # عرض خيارات عناصر الرسالة مع التحديث
        group_config = config["groups"][group_id]["message_format"]
        show_current_time = "✅" if group_config["show_current_time"] else "❌"
        show_next_code_in = "✅" if group_config["show_next_code_in"] else "❌"
        show_next_code_at = "✅" if group_config["show_next_code_at"] else "❌"
        
        keyboard = [
            [InlineKeyboardButton(f"{show_current_time} عرض الوقت الحالي", callback_data="toggle_show_current_time")],
            [InlineKeyboardButton(f"{show_next_code_in} عرض المدة المتبقية للرمز التالي", callback_data="toggle_show_next_code_in")],
            [InlineKeyboardButton(f"{show_next_code_at} عرض وقت الرمز التالي", callback_data="toggle_show_next_code_at")],
            [InlineKeyboardButton("رجوع", callback_data="back_to_customize")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        option_name = ""
        if option == "show_current_time":
            option_name = "عرض الوقت الحالي"
        elif option == "show_next_code_in":
            option_name = "عرض المدة المتبقية للرمز التالي"
        elif option == "show_next_code_at":
            option_name = "عرض وقت الرمز التالي"
        
        status = "تفعيل" if new_value else "تعطيل"
        
        await query.edit_message_text(
            f"تم {status} {option_name} بنجاح.\n\n"
            f"خيارات عرض عناصر الرسالة للمجموعة {group_id}:\n"
            f"الرجاء اختيار العنصر الذي ترغب في تغيير حالته:",
            reply_markup=reply_markup
        )
        return TOGGLE_MESSAGE_OPTIONS

async def customize_message_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال نص جديد لتخصيص الرسالة"""
    text = update.message.text.strip()
    group_id = context.user_data.get("selected_group")
    field = context.user_data.get("edit_field")
    
    if field in ["line1", "line2"]:
        # تحديث حقل النص في تنسيق الرسالة
        config["groups"][group_id]["message_format"][field] = text
        save_config()
        
        await update.message.reply_text(
            f"تم تحديث {field} بنجاح."
        )
    
    # العودة إلى قائمة تخصيص الرسالة
    group_config = config["groups"][group_id]
    timezone = group_config["timezone"]
    time_format = group_config["time_format"]
    line1 = group_config["message_format"]["line1"]
    line2 = group_config["message_format"]["line2"]
    
    keyboard = [
        [InlineKeyboardButton("تعديل السطر الأول", callback_data="edit_line1")],
        [InlineKeyboardButton("تعديل السطر الثاني", callback_data="edit_line2")],
        [InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data="change_timezone")],
        [InlineKeyboardButton("تغيير تنسيق الوقت", callback_data="change_time_format")],
        [InlineKeyboardButton("تغيير خيارات عرض الرسالة", callback_data="toggle_message_options")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"إعدادات الرسالة الحالية للمجموعة {group_id}:\n\n"
        f"السطر الأول: {line1}\n"
        f"السطر الثاني: {line2}\n"
        f"المنطقة الزمنية: {timezone}\n"
        f"تنسيق الوقت: {time_format} ساعة\n\n"
        f"الرجاء اختيار الإعداد الذي ترغب في تغييره:",
        reply_markup=reply_markup
    )
    
    return CUSTOMIZE_MESSAGE

async def select_timezone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المنطقة الزمنية"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_customize":
        # العودة إلى قائمة تخصيص الرسالة
        return await customize_message_handler(update, context)
    
    # استخراج المنطقة الزمنية من البيانات
    timezone = query.data.replace("timezone_", "")
    group_id = context.user_data.get("selected_group")
    
    # تعيين المنطقة الزمنية للمجموعة
    set_group_timezone(group_id, timezone)
    
    await query.edit_message_text(
        f"تم تعيين المنطقة الزمنية للمجموعة {group_id} إلى {timezone} بنجاح."
    )
    
    # العودة إلى قائمة تخصيص الرسالة بعد ثانيتين
    await asyncio.sleep(2)
    return await customize_message_handler(update, context)

async def select_time_format_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار تنسيق الوقت"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_customize":
        # العودة إلى قائمة تخصيص الرسالة
        return await customize_message_handler(update, context)
    
    # استخراج تنسيق الوقت من البيانات
    time_format = int(query.data.replace("time_format_", ""))
    group_id = context.user_data.get("selected_group")
    
    # تعيين تنسيق الوقت للمجموعة
    set_group_time_format(group_id, time_format)
    
    await query.edit_message_text(
        f"تم تعيين تنسيق الوقت للمجموعة {group_id} إلى {time_format} ساعة بنجاح."
    )
    
    # العودة إلى قائمة تخصيص الرسالة بعد ثانيتين
    await asyncio.sleep(2)
    return await customize_message_handler(update, context)

async def add_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إضافة مسؤول جديد"""
    admin_id = update.message.text.strip()
    
    # التحقق من صحة معرف المسؤول
    if not admin_id.isdigit():
        await update.message.reply_text(
            "معرف المسؤول غير صالح. يجب أن يكون رقماً. الرجاء المحاولة مرة أخرى."
        )
        return ADD_ADMIN
    
    # إضافة المسؤول
    result = add_admin(admin_id)
    
    if result:
        await update.message.reply_text(
            f"تمت إضافة المسؤول {admin_id} بنجاح."
        )
    else:
        await update.message.reply_text(
            f"المسؤول {admin_id} موجود بالفعل."
        )
    
    # العودة إلى قائمة المسؤول بعد ثانيتين
    await asyncio.sleep(2)
    return await admin_command(update, context)

async def remove_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إزالة مسؤول"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_admin":
        # العودة إلى قائمة المسؤول الرئيسية
        return await admin_command(update, context)
    
    # استخراج معرف المسؤول من البيانات
    admin_id = query.data.replace("remove_admin_", "")
    
    # إزالة المسؤول
    result = remove_admin(admin_id)
    
    if result:
        await query.edit_message_text(
            f"تمت إزالة المسؤول {admin_id} بنجاح."
        )
    else:
        await query.edit_message_text(
            f"فشل في إزالة المسؤول {admin_id}. تأكد من وجود مسؤول واحد على الأقل."
        )
    
    # العودة إلى قائمة المسؤول بعد ثانيتين
    await asyncio.sleep(2)
    return await admin_command(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة الحالية"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("تم إلغاء العملية.")
    else:
        await update.message.reply_text("تم إلغاء العملية.")
    
    return ConversationHandler.END

# نقطة البداية للبوت
def main():
    """تشغيل البوت"""
    # تحميل البيانات
    load_data()
    
    # إنشاء تطبيق البوت
    application = Application.builder().token(TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    
    # إضافة معالج المحادثة للأمر /admin
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_handler),
            ],
            ADD_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_handler),
            ],
            ADD_TOTP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_totp_handler),
            ],
            SET_INTERVAL: [
                CallbackQueryHandler(set_interval_handler),
            ],
            CUSTOMIZE_MESSAGE: [
                CallbackQueryHandler(customize_message_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, customize_message_text_handler),
            ],
            TOGGLE_MESSAGE_OPTIONS: [
                CallbackQueryHandler(toggle_message_options_handler),
            ],
            SET_ATTEMPTS: [
                CallbackQueryHandler(set_attempts_handler),
            ],
            SELECT_GROUP: [
                CallbackQueryHandler(select_group_handler),
            ],
            SELECT_TIMEZONE: [
                CallbackQueryHandler(select_timezone_handler),
            ],
            SELECT_TIME_FORMAT: [
                CallbackQueryHandler(select_time_format_handler),
            ],
            ADD_ADMIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_handler),
            ],
            REMOVE_ADMIN: [
                CallbackQueryHandler(remove_admin_handler),
            ],
            REMOVE_GROUP: [
                CallbackQueryHandler(remove_group_handler),
            ],
            TOGGLE_GROUP_STATUS: [
                CallbackQueryHandler(toggle_group_handler),
            ],
            WAITING_FOR_MANUAL_SEND: [
                CallbackQueryHandler(manual_send_code),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(admin_conv_handler)
    
    # إضافة معالج للنقر على زر Copy Code
    application.add_handler(CallbackQueryHandler(copy_code_handler, pattern="^copy_code_"))
    
    # بدء البوت
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# نقطة البداية للسكريبت
if __name__ == "__main__":
    main()

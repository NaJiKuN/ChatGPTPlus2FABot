# -*- coding: utf-8 -*-
"""
ChatGPTPlus2FABot - بوت تليجرام لإرسال رموز مصادقة 2FA

هذا البوت يقوم بإرسال رمز مصادقة 2FA من خلال TOTP_SECRET يضيفه المسؤول
ويرسل الرمز عند الضغط على زر Copy Code برسالة خاصة للمستخدم
"""

import logging
import sqlite3
import os
import pyotp
import datetime
import pytz
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# تمكين التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO,
    filename="bot.log"
)
logger = logging.getLogger(__name__)

# توكن البوت
TOKEN = os.getenv("BOT_TOKEN", "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")

# معرف المسؤول الأولي
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "764559466"))

# مسار ملف قاعدة البيانات
DB_FILE = "bot_data.db"

# حالات المحادثة
(
    WAITING_FOR_GROUP_ACTION,
    WAITING_FOR_GROUP_ID,
    WAITING_FOR_TOTP_SECRET,
    WAITING_FOR_INTERVAL,
    WAITING_FOR_MESSAGE_FORMAT,
    WAITING_FOR_TIMEZONE,
    WAITING_FOR_GROUP_SELECTION,
    WAITING_FOR_USER_SELECTION,
    WAITING_FOR_USER_ACTION,
    WAITING_FOR_ATTEMPTS_NUMBER,
    WAITING_FOR_ADMIN_ID,
) = range(11)

# قاموس لتخزين مهام الإرسال الدوري
scheduled_jobs = {}

# --- وظائف قاعدة البيانات ---
def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول إذا لم تكن موجودة."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # جدول المسؤولين
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
    """)

    # إضافة المسؤول الأولي إذا لم يكن موجوداً
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (INITIAL_ADMIN_ID,))

    # جدول المجموعات
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY,
        totp_secret TEXT,
        interval_minutes INTEGER DEFAULT 10,
        message_format INTEGER DEFAULT 1,
        timezone TEXT DEFAULT 'Asia/Jerusalem',
        time_format TEXT DEFAULT '12h',
        is_active BOOLEAN DEFAULT 1
    )
    """)

    # جدول محاولات المستخدمين
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        remaining_attempts INTEGER DEFAULT 3,
        is_banned BOOLEAN DEFAULT 0,
        last_reset TEXT,
        FOREIGN KEY (group_id) REFERENCES groups (group_id),
        UNIQUE(group_id, user_id)
    )
    """)

    conn.commit()
    conn.close()
    logger.info("تم تهيئة قاعدة البيانات بنجاح.")

def is_admin(user_id: int) -> bool:
    """التحقق مما إذا كان معرف المستخدم ينتمي إلى مسؤول."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    is_admin_flag = cursor.fetchone() is not None
    conn.close()
    return is_admin_flag

def add_admin(user_id: int) -> bool:
    """إضافة مسؤول جديد."""
    if is_admin(user_id):
        return False  # المسؤول موجود بالفعل
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    return True

def remove_admin(user_id: int) -> bool:
    """إزالة مسؤول."""
    if user_id == INITIAL_ADMIN_ID:
        return False  # لا يمكن إزالة المسؤول الأولي
    
    if not is_admin(user_id):
        return False  # المسؤول غير موجود
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

def get_all_admins():
    """الحصول على جميع المسؤولين."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    admins = cursor.fetchall()
    conn.close()
    return [admin[0] for admin in admins]

def get_all_groups():
    """الحصول على جميع المجموعات من قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT group_id, totp_secret, interval_minutes, message_format, timezone, time_format, is_active FROM groups")
    groups = cursor.fetchall()
    conn.close()
    return groups

def get_group(group_id):
    """الحصول على مجموعة محددة من قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
    group = cursor.fetchone()
    conn.close()
    return group

def add_or_update_group(group_id, totp_secret, interval_minutes=10, message_format=1, timezone="Asia/Jerusalem", time_format="12h", is_active=1):
    """إضافة أو تحديث مجموعة في قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # التحقق مما إذا كانت المجموعة موجودة
    cursor.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,))
    exists = cursor.fetchone() is not None
    
    if exists:
        # تحديث المجموعة الموجودة
        cursor.execute(
            "UPDATE groups SET totp_secret = ?, interval_minutes = ?, message_format = ?, timezone = ?, time_format = ?, is_active = ? WHERE group_id = ?",
            (totp_secret, interval_minutes, message_format, timezone, time_format, is_active, group_id)
        )
    else:
        # إدراج مجموعة جديدة
        cursor.execute(
            "INSERT INTO groups (group_id, totp_secret, interval_minutes, message_format, timezone, time_format, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (group_id, totp_secret, interval_minutes, message_format, timezone, time_format, is_active)
        )
    
    conn.commit()
    conn.close()
    return exists

def delete_group(group_id):
    """حذف مجموعة من قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    cursor.execute("DELETE FROM user_attempts WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()

def toggle_group_status(group_id):
    """تبديل حالة نشاط المجموعة."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_active FROM groups WHERE group_id = ?", (group_id,))
    current_status = cursor.fetchone()
    
    if current_status:
        new_status = 0 if current_status[0] else 1
        cursor.execute("UPDATE groups SET is_active = ? WHERE group_id = ?", (new_status, group_id))
        conn.commit()
        conn.close()
        return new_status
    
    conn.close()
    return None

def get_users_in_group(group_id):
    """الحصول على جميع المستخدمين في مجموعة محددة."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, remaining_attempts, is_banned FROM user_attempts WHERE group_id = ?", (group_id,))
    users = cursor.fetchall()
    conn.close()
    return users

def update_user_attempts(group_id, user_id, attempts_change=0, is_banned=None, username=None, first_name=None):
    """تحديث محاولات المستخدم المتبقية."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # التحقق مما إذا كان المستخدم موجوداً في هذه المجموعة
    cursor.execute("SELECT remaining_attempts, is_banned FROM user_attempts WHERE group_id = ? AND user_id = ?", 
                  (group_id, user_id))
    user_data = cursor.fetchone()
    
    if user_data:
        current_attempts, current_banned = user_data
        new_attempts = max(0, current_attempts + attempts_change)
        
        # إذا تم توفير is_banned، استخدمه، وإلا احتفظ بالقيمة الحالية
        new_banned = is_banned if is_banned is not None else current_banned
        
        # تحديث معلومات المستخدم إذا تم توفيرها
        if username or first_name:
            update_query = "UPDATE user_attempts SET remaining_attempts = ?, is_banned = ?"
            params = [new_attempts, new_banned]
            
            if username:
                update_query += ", username = ?"
                params.append(username)
            
            if first_name:
                update_query += ", first_name = ?"
                params.append(first_name)
            
            update_query += " WHERE group_id = ? AND user_id = ?"
            params.extend([group_id, user_id])
            
            cursor.execute(update_query, params)
        else:
            cursor.execute("UPDATE user_attempts SET remaining_attempts = ?, is_banned = ? WHERE group_id = ? AND user_id = ?",
                          (new_attempts, new_banned, group_id, user_id))
    else:
        # مستخدم جديد، تعيين القيم الافتراضية
        new_attempts = max(0, 3 + attempts_change)  # افتراضياً 3 محاولات
        new_banned = is_banned if is_banned is not None else 0
        
        cursor.execute(
            "INSERT INTO user_attempts (group_id, user_id, username, first_name, remaining_attempts, is_banned) VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, user_id, username, first_name, new_attempts, new_banned)
        )
    
    conn.commit()
    conn.close()
    return new_attempts

def set_user_attempts(group_id, user_id, attempts, is_banned=None, username=None, first_name=None):
    """تعيين عدد محدد من محاولات المستخدم."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # التحقق مما إذا كان المستخدم موجوداً في هذه المجموعة
    cursor.execute("SELECT is_banned FROM user_attempts WHERE group_id = ? AND user_id = ?", 
                  (group_id, user_id))
    user_data = cursor.fetchone()
    
    if user_data:
        current_banned = user_data[0]
        new_banned = is_banned if is_banned is not None else current_banned
        
        # تحديث معلومات المستخدم
        update_query = "UPDATE user_attempts SET remaining_attempts = ?, is_banned = ?"
        params = [attempts, new_banned]
        
        if username:
            update_query += ", username = ?"
            params.append(username)
        
        if first_name:
            update_query += ", first_name = ?"
            params.append(first_name)
        
        update_query += " WHERE group_id = ? AND user_id = ?"
        params.extend([group_id, user_id])
        
        cursor.execute(update_query, params)
    else:
        # مستخدم جديد
        new_banned = is_banned if is_banned is not None else 0
        
        cursor.execute(
            "INSERT INTO user_attempts (group_id, user_id, username, first_name, remaining_attempts, is_banned) VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, user_id, username, first_name, attempts, new_banned)
        )
    
    conn.commit()
    conn.close()
    return attempts

def get_user_attempts(group_id, user_id):
    """الحصول على محاولات المستخدم المتبقية."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT remaining_attempts, is_banned FROM user_attempts WHERE group_id = ? AND user_id = ?", 
                  (group_id, user_id))
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        return user_data
    else:
        # القيم الافتراضية للمستخدمين الجدد
        return (3, 0)  # 3 محاولات، غير محظور

def reset_daily_attempts():
    """إعادة تعيين محاولات المستخدمين اليومية بعد منتصف الليل."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE user_attempts SET remaining_attempts = 3, last_reset = datetime('now')")
    conn.commit()
    conn.close()
    logger.info("تم إعادة تعيين محاولات المستخدمين اليومية.")

def get_active_groups():
    """الحصول على جميع المجموعات النشطة من قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT group_id, totp_secret, interval_minutes, message_format, timezone, time_format FROM groups WHERE is_active = 1"
    )
    active_groups = cursor.fetchall()
    conn.close()
    return active_groups

# --- وظائف TOTP ---
def generate_totp(secret):
    """توليد رمز TOTP من سر."""
    totp = pyotp.TOTP(secret)
    return totp.now()

def get_remaining_seconds():
    """الحصول على الثواني المتبقية حتى الرمز التالي."""
    now = datetime.datetime.now()
    seconds_passed = (now.second + now.microsecond / 1000000.0)
    return 30 - (seconds_passed % 30)

def format_next_time(interval_minutes, timezone_str="Asia/Jerusalem", time_format="12h"):
    """تنسيق الوقت التالي للرسالة."""
    tz = pytz.timezone(timezone_str)
    now = datetime.datetime.now(tz)
    next_time = now + datetime.timedelta(minutes=interval_minutes)
    
    if time_format == "12h":
        return next_time.strftime("%I:%M:%S %p")  # تنسيق 12 ساعة مع AM/PM
    else:
        return next_time.strftime("%H:%M:%S")  # تنسيق 24 ساعة

def format_current_time(timezone_str="Asia/Jerusalem", time_format="12h"):
    """تنسيق الوقت الحالي."""
    tz = pytz.timezone(timezone_str)
    now = datetime.datetime.now(tz)
    
    if time_format == "12h":
        return now.strftime("%I:%M:%S %p")  # تنسيق 12 ساعة مع AM/PM
    else:
        return now.strftime("%H:%M:%S")  # تنسيق 24 ساعة

def get_message_format(format_id, interval_minutes, timezone_str="Asia/Jerusalem", time_format="12h"):
    """الحصول على تنسيق الرسالة بناءً على معرف التنسيق."""
    next_time = format_next_time(interval_minutes, timezone_str, time_format)
    current_time = format_current_time(timezone_str, time_format)
    
    if format_id == 1:  # الشكل الأول
        return f"🔐 2FA Verification Code\n\nNext code at: {next_time}"
    elif format_id == 2:  # الشكل الثاني
        return f"🔐 2FA Verification Code\n\nNext code in: {interval_minutes} minutes\n\nNext code at: {next_time}"
    elif format_id == 3:  # الشكل الثالث
        return f"🔐 2FA Verification Code\n\nNext code in: {interval_minutes} minutes\nCurrent Time: {current_time}\nNext Code at: {next_time}"
    else:
        # تنسيق افتراضي
        return f"🔐 2FA Verification Code\n\nNext code at: {next_time}"

# --- وظائف إرسال الرسائل ---
async def send_verification_code_to_group(context, group_id, totp_secret, interval_minutes, message_format, timezone, time_format):
    """إرسال رمز التحقق إلى مجموعة محددة."""
    try:
        # تنسيق الرسالة
        message = get_message_format(message_format, interval_minutes, timezone, time_format)
        
        # إنشاء لوحة مفاتيح مضمنة مع زر Copy Code
        keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f'copy_code_{group_id}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال رسالة إلى المجموعة
        await context.bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)
        logger.info(f"تم إرسال رسالة رمز التحقق إلى المجموعة {group_id}")
    except Exception as e:
        logger.error(f"فشل إرسال رسالة إلى المجموعة {group_id}: {e}")

async def send_verification_codes(context):
    """إرسال رموز التحقق إلى جميع المجموعات النشطة."""
    try:
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
            
            await send_verification_code_to_group(context, group_id, totp_secret, interval, message_format, timezone, time_format)
    
    except Exception as e:
        logger.error(f"خطأ في send_verification_codes: {e}")

async def send_private_code_message(update, context, group_id, user_id):
    """إرسال رسالة خاصة برمز التحقق إلى المستخدم."""
    try:
        # الحصول على معلومات المجموعة
        group = get_group(group_id)
        if not group:
            await update.callback_query.answer("المجموعة غير موجودة.")
            return
        
        # الحصول على محاولات المستخدم المتبقية
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        # التحقق مما إذا كان المستخدم محظوراً
        if is_banned:
            await update.callback_query.answer("أنت محظور من نسخ الرموز. يرجى التواصل مع المسؤول.")
            return
        
        # التحقق مما إذا كان المستخدم لديه محاولات متبقية
        if remaining_attempts <= 0:
            await update.callback_query.answer("لقد استنفدت جميع محاولاتك اليومية. حاول مرة أخرى بعد منتصف الليل.")
            return
        
        # تحديث محاولات المستخدم
        new_attempts = update_user_attempts(
            group_id, 
            user_id, 
            -1,  # تقليل المحاولات بمقدار 1
            username=update.callback_query.from_user.username,
            first_name=update.callback_query.from_user.first_name
        )
        
        # توليد رمز TOTP
        totp_secret = group[1]
        code = generate_totp(totp_secret)
        
        # تنسيق الرسالة الخاصة
        message = f"🔐 رمز المصادقة 2FA\n\n{code}\n\n⚠️ صالح لمدة 30 ثانية فقط!\nعدد المحاولات المتبقية: {new_attempts}"
        
        # إرسال الرسالة الخاصة
        await context.bot.send_message(chat_id=user_id, text=message)
        
        # إخطار المستخدم بأن الرمز تم إرساله
        await update.callback_query.answer("تم إرسال الرمز في رسالة خاصة.")
        
    except Exception as e:
        logger.error(f"خطأ في send_private_code_message: {e}")
        await update.callback_query.answer("حدث خطأ أثناء إرسال الرمز. يرجى المحاولة مرة أخرى.")

# --- معالجات الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال رسالة ترحيب عند إصدار أمر /start."""
    await update.message.reply_text('مرحباً! أنا بوت ChatGPTPlus2FABot لإرسال رموز 2FA. استخدم /admin للوصول إلى لوحة التحكم إذا كنت مسؤولاً.')

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة أمر /admin، وإظهار لوحة المسؤول إذا كان المستخدم مسؤولاً."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الأمر مخصص للمسؤولين فقط.')
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
        [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
        [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
        [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data='admin_manage_admins')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('لوحة تحكم المسؤول:', reply_markup=reply_markup)
    return WAITING_FOR_GROUP_ACTION

# --- معالجات استعلامات الأزرار ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة استجابات الأزرار وتوجيهها إلى المعالجات المناسبة."""
    query = update.callback_query
    await query.answer()  # الرد على استعلام الزر

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text(text='عذراً، الإجراءات الإدارية مخصصة للمسؤولين فقط.')
        return ConversationHandler.END

    # خيارات قائمة المسؤول الرئيسية
    if query.data == 'admin_manage_groups':
        keyboard = [
            [InlineKeyboardButton("إضافة/تعديل مجموعة", callback_data='add_edit_group')],
            [InlineKeyboardButton("حذف مجموعة", callback_data='delete_group')],
            [InlineKeyboardButton("عرض المجموعات", callback_data='list_groups')],
            [InlineKeyboardButton("تفعيل/تعطيل مجموعة", callback_data='toggle_group')],
            [InlineKeyboardButton("العودة", callback_data='back_to_admin')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="إدارة المجموعات و TOTP:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
        
    elif query.data == 'admin_set_interval':
        groups = get_all_groups()
        if not groups:
            await query.edit_message_text(text="لا توجد مجموعات مضافة بعد. الرجاء إضافة مجموعة أولاً.")
            return ConversationHandler.END
            
        keyboard = []
        for group in groups:
            group_id, _, interval, message_format, timezone, time_format, is_active = group
            status = "✅" if is_active else "❌"
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} | التكرار: {interval}د {status}", 
                                                 callback_data=f'interval_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لتعديل مدة التكرار:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
        
    elif query.data == 'admin_set_format':
        groups = get_all_groups()
        if not groups:
            await query.edit_message_text(text="لا توجد مجموعات مضافة بعد. الرجاء إضافة مجموعة أولاً.")
            return ConversationHandler.END
            
        keyboard = []
        for group in groups:
            group_id = group[0]
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", 
                                                 callback_data=f'format_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لتخصيص شكل الرسالة:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
        
    elif query.data == 'admin_manage_attempts':
        groups = get_all_groups()
        if not groups:
            await query.edit_message_text(text="لا توجد مجموعات مضافة بعد. الرجاء إضافة مجموعة أولاً.")
            return ConversationHandler.END
            
        keyboard = []
        for group in groups:
            group_id = group[0]
            users = get_users_in_group(group_id)
            if users:
                keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} ({len(users)} مستخدم)", 
                                                     callback_data=f'attempts_{group_id}')])
            else:
                keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} (لا يوجد مستخدمين)", 
                                                     callback_data=f'attempts_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لإدارة محاولات النسخ:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
    
    elif query.data == 'admin_manage_admins':
        admins = get_all_admins()
        
        keyboard = [
            [InlineKeyboardButton("إضافة مسؤول جديد", callback_data='add_admin')],
        ]
        
        if len(admins) > 1:  # إذا كان هناك أكثر من مسؤول واحد
            keyboard.append([InlineKeyboardButton("حذف مسؤول", callback_data='remove_admin')])
        
        keyboard.append([InlineKeyboardButton("عرض المسؤولين", callback_data='list_admins')])
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="إدارة المسؤولين:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
        
    elif query.data == 'back_to_admin':
        # العودة إلى قائمة المسؤول الرئيسية
        keyboard = [
            [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
            [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
            [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
            [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
            [InlineKeyboardButton("إدارة المسؤولين", callback_data='admin_manage_admins')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text='لوحة تحكم المسؤول:', reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # خيارات إدارة المجموعة
    elif query.data == 'add_edit_group':
        await query.edit_message_text(text="الرجاء إدخال معرف المجموعة (مثال: -1002329495586):")
        return WAITING_FOR_GROUP_ID
        
    elif query.data == 'delete_group':
        groups = get_all_groups()
        if not groups:
            await query.edit_message_text(text="لا توجد مجموعات مضافة بعد.")
            return ConversationHandler.END
            
        keyboard = []
        for group in groups:
            group_id = group[0]
            keyboard.append([InlineKeyboardButton(f"حذف المجموعة: {group_id}", 
                                                 callback_data=f'delete_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_groups')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة للحذف:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    elif query.data == 'toggle_group':
        groups = get_all_groups()
        if not groups:
            await query.edit_message_text(text="لا توجد مجموعات مضافة بعد.")
            return ConversationHandler.END
            
        keyboard = []
        for group in groups:
            group_id, _, _, _, _, _, is_active = group
            status = "✅" if is_active else "❌"
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} {status}", 
                                                 callback_data=f'toggle_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_groups')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لتفعيل/تعطيل:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
        
    elif query.data == 'list_groups':
        groups = get_all_groups()
        if not groups:
            message = "لا توجد مجموعات مضافة بعد."
        else:
            message = "المجموعات المضافة:\n\n"
            for i, group in enumerate(groups, 1):
                group_id, secret, interval, message_format, timezone, time_format, is_active = group
                status = "نشط ✅" if is_active else "غير نشط ❌"
                # إخفاء سر TOTP للأمان
                masked_secret = f"{secret[:4]}...{secret[-4:]}" if secret else "غير محدد"
                message += f"{i}. المجموعة: {group_id}\n   السر: {masked_secret}\n   التكرار: {interval} دقيقة\n   تنسيق الرسالة: {message_format}\n   المنطقة الزمنية: {timezone}\n   تنسيق الوقت: {time_format}\n   الحالة: {status}\n\n"
        
        keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_manage_groups')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message, reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # خيارات إدارة المسؤولين
    elif query.data == 'add_admin':
        await query.edit_message_text(text="الرجاء إدخال معرف المسؤول الجديد (مثال: 764559466):")
        return WAITING_FOR_ADMIN_ID
    
    elif query.data == 'remove_admin':
        admins = get_all_admins()
        if len(admins) <= 1:
            await query.edit_message_text(text="لا يمكن حذف المسؤول الوحيد.")
            return ConversationHandler.END
            
        keyboard = []
        for admin_id in admins:
            if admin_id != INITIAL_ADMIN_ID:  # لا يمكن حذف المسؤول الأولي
                keyboard.append([InlineKeyboardButton(f"حذف المسؤول: {admin_id}", 
                                                     callback_data=f'remove_admin_{admin_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_admins')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المسؤول للحذف:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    elif query.data == 'list_admins':
        admins = get_all_admins()
        message = "المسؤولون الحاليون:\n\n"
        for i, admin_id in enumerate(admins, 1):
            if admin_id == INITIAL_ADMIN_ID:
                message += f"{i}. {admin_id} (المسؤول الأولي)\n"
            else:
                message += f"{i}. {admin_id}\n"
        
        keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_manage_admins')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message, reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة حذف المسؤول
    elif query.data.startswith('remove_admin_'):
        admin_id = int(query.data.split('_')[-1])
        if remove_admin(admin_id):
            await query.edit_message_text(text=f"تم حذف المسؤول {admin_id} بنجاح.")
        else:
            await query.edit_message_text(text=f"فشل حذف المسؤول {admin_id}. قد يكون هذا هو المسؤول الأولي الذي لا يمكن حذفه.")
        
        # العودة إلى قائمة إدارة المسؤولين بعد ثانيتين
        await asyncio.sleep(2)
        keyboard = [
            [InlineKeyboardButton("إضافة مسؤول جديد", callback_data='add_admin')],
            [InlineKeyboardButton("حذف مسؤول", callback_data='remove_admin')],
            [InlineKeyboardButton("عرض المسؤولين", callback_data='list_admins')],
            [InlineKeyboardButton("العودة", callback_data='back_to_admin')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="إدارة المسؤولين:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة حذف المجموعة
    elif query.data.startswith('delete_'):
        group_id = int(query.data.split('_')[-1])
        delete_group(group_id)
        await query.edit_message_text(text=f"تم حذف المجموعة {group_id} بنجاح.")
        
        # العودة إلى قائمة إدارة المجموعات بعد ثانيتين
        await asyncio.sleep(2)
        keyboard = [
            [InlineKeyboardButton("إضافة/تعديل مجموعة", callback_data='add_edit_group')],
            [InlineKeyboardButton("حذف مجموعة", callback_data='delete_group')],
            [InlineKeyboardButton("عرض المجموعات", callback_data='list_groups')],
            [InlineKeyboardButton("تفعيل/تعطيل مجموعة", callback_data='toggle_group')],
            [InlineKeyboardButton("العودة", callback_data='back_to_admin')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="إدارة المجموعات و TOTP:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة تفعيل/تعطيل المجموعة
    elif query.data.startswith('toggle_'):
        group_id = int(query.data.split('_')[-1])
        new_status = toggle_group_status(group_id)
        
        if new_status is not None:
            status_text = "تفعيل" if new_status else "تعطيل"
            await query.edit_message_text(text=f"تم {status_text} المجموعة {group_id} بنجاح.")
        else:
            await query.edit_message_text(text=f"فشل تغيير حالة المجموعة {group_id}.")
        
        # العودة إلى قائمة تفعيل/تعطيل المجموعات بعد ثانيتين
        await asyncio.sleep(2)
        groups = get_all_groups()
        keyboard = []
        for group in groups:
            group_id, _, _, _, _, _, is_active = group
            status = "✅" if is_active else "❌"
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} {status}", 
                                                 callback_data=f'toggle_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_groups')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لتفعيل/تعطيل:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة تحديد مدة التكرار
    elif query.data.startswith('interval_'):
        group_id = int(query.data.split('_')[-1])
        context.user_data['selected_group'] = group_id
        await query.edit_message_text(text=f"الرجاء إدخال مدة التكرار بالدقائق للمجموعة {group_id}:")
        return WAITING_FOR_INTERVAL
    
    # معالجة تخصيص شكل الرسالة
    elif query.data.startswith('format_'):
        group_id = int(query.data.split('_')[-1])
        context.user_data['selected_group'] = group_id
        
        keyboard = [
            [InlineKeyboardButton("الشكل الأول", callback_data='set_format_1')],
            [InlineKeyboardButton("الشكل الثاني", callback_data='set_format_2')],
            [InlineKeyboardButton("الشكل الثالث", callback_data='set_format_3')],
            [InlineKeyboardButton("العودة", callback_data='admin_set_format')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"اختر شكل الرسالة للمجموعة {group_id}:\n\n"
        message += "الشكل الأول:\n🔐 2FA Verification Code\n\nNext code at: 07:05:34 PM\n\n"
        message += "الشكل الثاني:\n🔐 2FA Verification Code\n\nNext code in: 10 minutes\n\nNext code at: 07:05:34 PM\n\n"
        message += "الشكل الثالث:\n🔐 2FA Verification Code\n\nNext code in: 10 minutes\nCurrent Time: 06:55:34 PM\nNext Code at: 07:05:34 PM"
        
        await query.edit_message_text(text=message, reply_markup=reply_markup)
        return WAITING_FOR_MESSAGE_FORMAT
    
    # معالجة تعيين شكل الرسالة
    elif query.data.startswith('set_format_'):
        format_id = int(query.data.split('_')[-1])
        group_id = context.user_data.get('selected_group')
        
        if not group_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة.")
            return ConversationHandler.END
        
        # الحصول على معلومات المجموعة الحالية
        group = get_group(group_id)
        if not group:
            await query.edit_message_text(text="المجموعة غير موجودة.")
            return ConversationHandler.END
        
        # تحديث تنسيق الرسالة
        add_or_update_group(
            group_id,
            group[1],  # totp_secret
            group[2],  # interval_minutes
            format_id,
            group[4],  # timezone
            group[5],  # time_format
            group[6]   # is_active
        )
        
        await query.edit_message_text(text=f"تم تعيين شكل الرسالة للمجموعة {group_id} بنجاح.")
        
        # العودة إلى قائمة تخصيص شكل الرسالة بعد ثانيتين
        await asyncio.sleep(2)
        groups = get_all_groups()
        keyboard = []
        for group in groups:
            group_id = group[0]
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", 
                                                 callback_data=f'format_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="اختر المجموعة لتخصيص شكل الرسالة:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
    
    # معالجة إدارة محاولات النسخ
    elif query.data.startswith('attempts_'):
        group_id = int(query.data.split('_')[-1])
        context.user_data['selected_group'] = group_id
        
        users = get_users_in_group(group_id)
        if not users:
            await query.edit_message_text(text=f"لا يوجد مستخدمين في المجموعة {group_id} بعد.")
            
            # العودة إلى قائمة إدارة المحاولات بعد ثانيتين
            await asyncio.sleep(2)
            groups = get_all_groups()
            keyboard = []
            for group in groups:
                group_id = group[0]
                users = get_users_in_group(group_id)
                if users:
                    keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} ({len(users)} مستخدم)", 
                                                         callback_data=f'attempts_{group_id}')])
                else:
                    keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} (لا يوجد مستخدمين)", 
                                                         callback_data=f'attempts_{group_id}')])
            
            keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="اختر المجموعة لإدارة محاولات النسخ:", reply_markup=reply_markup)
            return WAITING_FOR_GROUP_SELECTION
        
        keyboard = []
        for user in users:
            user_id, username, first_name, remaining_attempts, is_banned = user
            status = "🚫" if is_banned else "✅"
            display_name = username if username else first_name if first_name else user_id
            keyboard.append([InlineKeyboardButton(f"{display_name} | المحاولات: {remaining_attempts} {status}", 
                                                 callback_data=f'user_{group_id}_{user_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_attempts')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"اختر المستخدم لإدارة محاولات النسخ في المجموعة {group_id}:", reply_markup=reply_markup)
        return WAITING_FOR_USER_SELECTION
    
    # معالجة اختيار المستخدم لإدارة المحاولات
    elif query.data.startswith('user_'):
        parts = query.data.split('_')
        group_id = int(parts[1])
        user_id = int(parts[2])
        
        context.user_data['selected_group'] = group_id
        context.user_data['selected_user'] = user_id
        
        # الحصول على معلومات المستخدم
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        keyboard = [
            [InlineKeyboardButton("زيادة المحاولات", callback_data='increase_attempts')],
            [InlineKeyboardButton("تقليل المحاولات", callback_data='decrease_attempts')],
            [InlineKeyboardButton("تعيين عدد محدد من المحاولات", callback_data='set_attempts')],
            [InlineKeyboardButton(f"{'إلغاء الحظر' if is_banned else 'حظر المستخدم'}", 
                                 callback_data=f"{'unban' if is_banned else 'ban'}_user")],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status = "محظور 🚫" if is_banned else "نشط ✅"
        await query.edit_message_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\n\n"
                 f"المحاولات المتبقية: {remaining_attempts}\n"
                 f"الحالة: {status}\n\n"
                 f"اختر الإجراء:",
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    
    # معالجة زيادة المحاولات
    elif query.data == 'increase_attempts':
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        
        if not group_id or not user_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
            return ConversationHandler.END
        
        # زيادة المحاولات بمقدار 1
        new_attempts = update_user_attempts(group_id, user_id, 1)
        
        await query.edit_message_text(text=f"تم زيادة محاولات المستخدم {user_id} بنجاح. المحاولات المتبقية: {new_attempts}")
        
        # العودة إلى قائمة إدارة المستخدم بعد ثانيتين
        await asyncio.sleep(2)
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        keyboard = [
            [InlineKeyboardButton("زيادة المحاولات", callback_data='increase_attempts')],
            [InlineKeyboardButton("تقليل المحاولات", callback_data='decrease_attempts')],
            [InlineKeyboardButton("تعيين عدد محدد من المحاولات", callback_data='set_attempts')],
            [InlineKeyboardButton(f"{'إلغاء الحظر' if is_banned else 'حظر المستخدم'}", 
                                 callback_data=f"{'unban' if is_banned else 'ban'}_user")],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status = "محظور 🚫" if is_banned else "نشط ✅"
        await query.edit_message_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\n\n"
                 f"المحاولات المتبقية: {remaining_attempts}\n"
                 f"الحالة: {status}\n\n"
                 f"اختر الإجراء:",
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    
    # معالجة تقليل المحاولات
    elif query.data == 'decrease_attempts':
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        
        if not group_id or not user_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
            return ConversationHandler.END
        
        # تقليل المحاولات بمقدار 1
        new_attempts = update_user_attempts(group_id, user_id, -1)
        
        await query.edit_message_text(text=f"تم تقليل محاولات المستخدم {user_id} بنجاح. المحاولات المتبقية: {new_attempts}")
        
        # العودة إلى قائمة إدارة المستخدم بعد ثانيتين
        await asyncio.sleep(2)
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        keyboard = [
            [InlineKeyboardButton("زيادة المحاولات", callback_data='increase_attempts')],
            [InlineKeyboardButton("تقليل المحاولات", callback_data='decrease_attempts')],
            [InlineKeyboardButton("تعيين عدد محدد من المحاولات", callback_data='set_attempts')],
            [InlineKeyboardButton(f"{'إلغاء الحظر' if is_banned else 'حظر المستخدم'}", 
                                 callback_data=f"{'unban' if is_banned else 'ban'}_user")],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status = "محظور 🚫" if is_banned else "نشط ✅"
        await query.edit_message_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\n\n"
                 f"المحاولات المتبقية: {remaining_attempts}\n"
                 f"الحالة: {status}\n\n"
                 f"اختر الإجراء:",
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    
    # معالجة تعيين عدد محدد من المحاولات
    elif query.data == 'set_attempts':
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        
        if not group_id or not user_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
            return ConversationHandler.END
        
        await query.edit_message_text(text=f"الرجاء إدخال عدد المحاولات للمستخدم {user_id}:")
        return WAITING_FOR_ATTEMPTS_NUMBER
    
    # معالجة حظر/إلغاء حظر المستخدم
    elif query.data in ['ban_user', 'unban_user']:
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        
        if not group_id or not user_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
            return ConversationHandler.END
        
        # تعيين حالة الحظر
        is_banned = 1 if query.data == 'ban_user' else 0
        update_user_attempts(group_id, user_id, 0, is_banned)
        
        action = "حظر" if is_banned else "إلغاء حظر"
        await query.edit_message_text(text=f"تم {action} المستخدم {user_id} بنجاح.")
        
        # العودة إلى قائمة إدارة المستخدم بعد ثانيتين
        await asyncio.sleep(2)
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        keyboard = [
            [InlineKeyboardButton("زيادة المحاولات", callback_data='increase_attempts')],
            [InlineKeyboardButton("تقليل المحاولات", callback_data='decrease_attempts')],
            [InlineKeyboardButton("تعيين عدد محدد من المحاولات", callback_data='set_attempts')],
            [InlineKeyboardButton(f"{'إلغاء الحظر' if is_banned else 'حظر المستخدم'}", 
                                 callback_data=f"{'unban' if is_banned else 'ban'}_user")],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status = "محظور 🚫" if is_banned else "نشط ✅"
        await query.edit_message_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\n\n"
                 f"المحاولات المتبقية: {remaining_attempts}\n"
                 f"الحالة: {status}\n\n"
                 f"اختر الإجراء:",
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    
    # معالجة زر Copy Code
    elif query.data.startswith('copy_code_'):
        group_id = int(query.data.split('_')[-1])
        user_id = query.from_user.id
        
        await send_private_code_message(update, context, group_id, user_id)
        return ConversationHandler.END
    
    return ConversationHandler.END

# --- معالجات الرسائل ---
async def group_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال معرف المجموعة."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الإجراء مخصص للمسؤولين فقط.')
        return ConversationHandler.END
    
    try:
        group_id = int(update.message.text.strip())
        context.user_data['group_id'] = group_id
        
        # التحقق مما إذا كانت المجموعة موجودة بالفعل
        group = get_group(group_id)
        if group:
            await update.message.reply_text(
                f"المجموعة {group_id} موجودة بالفعل.\n"
                f"الرجاء إدخال سر TOTP الجديد أو اكتب 'skip' للاحتفاظ بالسر الحالي:"
            )
        else:
            await update.message.reply_text(f"الرجاء إدخال سر TOTP للمجموعة {group_id}:")
        
        return WAITING_FOR_TOTP_SECRET
    except ValueError:
        await update.message.reply_text("الرجاء إدخال معرف مجموعة صالح (رقم صحيح).")
        return WAITING_FOR_GROUP_ID

async def totp_secret_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال سر TOTP."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الإجراء مخصص للمسؤولين فقط.')
        return ConversationHandler.END
    
    group_id = context.user_data.get('group_id')
    if not group_id:
        await update.message.reply_text("حدث خطأ: لم يتم تحديد المجموعة.")
        return ConversationHandler.END
    
    totp_secret = update.message.text.strip()
    
    # التحقق مما إذا كان المستخدم يريد تخطي تحديث السر
    if totp_secret.lower() == 'skip':
        group = get_group(group_id)
        if group:
            totp_secret = group[1]  # الاحتفاظ بالسر الحالي
        else:
            await update.message.reply_text("لا يمكن تخطي إدخال السر لمجموعة جديدة. الرجاء إدخال سر TOTP:")
            return WAITING_FOR_TOTP_SECRET
    
    # التحقق من صحة سر TOTP
    try:
        pyotp.TOTP(totp_secret).now()
        context.user_data['totp_secret'] = totp_secret
        
        # إضافة أو تحديث المجموعة
        exists = add_or_update_group(group_id, totp_secret)
        
        action = "تحديث" if exists else "إضافة"
        await update.message.reply_text(f"تم {action} المجموعة {group_id} بنجاح.")
        
        # إعادة تشغيل المهمة الدورية إذا كانت موجودة
        if group_id in scheduled_jobs:
            scheduled_jobs[group_id].remove()
            del scheduled_jobs[group_id]
        
        # العودة إلى قائمة المسؤول
        keyboard = [
            [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
            [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
            [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
            [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
            [InlineKeyboardButton("إدارة المسؤولين", callback_data='admin_manage_admins')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('لوحة تحكم المسؤول:', reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    except Exception as e:
        await update.message.reply_text(f"سر TOTP غير صالح. الرجاء إدخال سر صالح:\n{str(e)}")
        return WAITING_FOR_TOTP_SECRET

async def interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال مدة التكرار."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الإجراء مخصص للمسؤولين فقط.')
        return ConversationHandler.END
    
    group_id = context.user_data.get('selected_group')
    if not group_id:
        await update.message.reply_text("حدث خطأ: لم يتم تحديد المجموعة.")
        return ConversationHandler.END
    
    try:
        interval = int(update.message.text.strip())
        if interval <= 0:
            await update.message.reply_text("الرجاء إدخال عدد دقائق أكبر من صفر.")
            return WAITING_FOR_INTERVAL
        
        # الحصول على معلومات المجموعة الحالية
        group = get_group(group_id)
        if not group:
            await update.message.reply_text("المجموعة غير موجودة.")
            return ConversationHandler.END
        
        # تحديث مدة التكرار
        add_or_update_group(
            group_id,
            group[1],  # totp_secret
            interval,
            group[3],  # message_format
            group[4],  # timezone
            group[5],  # time_format
            group[6]   # is_active
        )
        
        await update.message.reply_text(f"تم تحديث مدة التكرار للمجموعة {group_id} إلى {interval} دقيقة بنجاح.")
        
        # إعادة تشغيل المهمة الدورية إذا كانت موجودة
        if group_id in scheduled_jobs:
            scheduled_jobs[group_id].remove()
            del scheduled_jobs[group_id]
        
        # العودة إلى قائمة تحديد مدة التكرار
        groups = get_all_groups()
        keyboard = []
        for group in groups:
            group_id, _, interval, _, _, _, is_active = group
            status = "✅" if is_active else "❌"
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id} | التكرار: {interval}د {status}", 
                                                 callback_data=f'interval_{group_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='back_to_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text="اختر المجموعة لتعديل مدة التكرار:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
    except ValueError:
        await update.message.reply_text("الرجاء إدخال عدد دقائق صالح (رقم صحيح).")
        return WAITING_FOR_INTERVAL

async def attempts_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال عدد المحاولات."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الإجراء مخصص للمسؤولين فقط.')
        return ConversationHandler.END
    
    group_id = context.user_data.get('selected_group')
    user_id = context.user_data.get('selected_user')
    
    if not group_id or not user_id:
        await update.message.reply_text("حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
        return ConversationHandler.END
    
    try:
        attempts = int(update.message.text.strip())
        if attempts < 0:
            await update.message.reply_text("الرجاء إدخال عدد محاولات غير سالب.")
            return WAITING_FOR_ATTEMPTS_NUMBER
        
        # تعيين عدد المحاولات
        set_user_attempts(group_id, user_id, attempts)
        
        await update.message.reply_text(f"تم تعيين عدد محاولات المستخدم {user_id} إلى {attempts} بنجاح.")
        
        # العودة إلى قائمة إدارة المستخدم
        remaining_attempts, is_banned = get_user_attempts(group_id, user_id)
        
        keyboard = [
            [InlineKeyboardButton("زيادة المحاولات", callback_data='increase_attempts')],
            [InlineKeyboardButton("تقليل المحاولات", callback_data='decrease_attempts')],
            [InlineKeyboardButton("تعيين عدد محدد من المحاولات", callback_data='set_attempts')],
            [InlineKeyboardButton(f"{'إلغاء الحظر' if is_banned else 'حظر المستخدم'}", 
                                 callback_data=f"{'unban' if is_banned else 'ban'}_user")],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        status = "محظور 🚫" if is_banned else "نشط ✅"
        await update.message.reply_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\n\n"
                 f"المحاولات المتبقية: {remaining_attempts}\n"
                 f"الحالة: {status}\n\n"
                 f"اختر الإجراء:",
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    except ValueError:
        await update.message.reply_text("الرجاء إدخال عدد محاولات صالح (رقم صحيح).")
        return WAITING_FOR_ATTEMPTS_NUMBER

async def admin_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال معرف المسؤول."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الإجراء مخصص للمسؤولين فقط.')
        return ConversationHandler.END
    
    try:
        admin_id = int(update.message.text.strip())
        
        # إضافة المسؤول
        if add_admin(admin_id):
            await update.message.reply_text(f"تم إضافة المسؤول {admin_id} بنجاح.")
        else:
            await update.message.reply_text(f"المسؤول {admin_id} موجود بالفعل.")
        
        # العودة إلى قائمة إدارة المسؤولين
        keyboard = [
            [InlineKeyboardButton("إضافة مسؤول جديد", callback_data='add_admin')],
            [InlineKeyboardButton("حذف مسؤول", callback_data='remove_admin')],
            [InlineKeyboardButton("عرض المسؤولين", callback_data='list_admins')],
            [InlineKeyboardButton("العودة", callback_data='back_to_admin')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text="إدارة المسؤولين:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    except ValueError:
        await update.message.reply_text("الرجاء إدخال معرف مسؤول صالح (رقم صحيح).")
        return WAITING_FOR_ADMIN_ID

# --- وظيفة إعادة تعيين المحاولات اليومية ---
async def reset_daily_attempts_job(context):
    """وظيفة إعادة تعيين محاولات المستخدمين اليومية بعد منتصف الليل."""
    reset_daily_attempts()
    logger.info("تم إعادة تعيين محاولات المستخدمين اليومية.")

# --- الوظيفة الرئيسية ---
async def main():
    """الوظيفة الرئيسية للبوت."""
    # تهيئة قاعدة البيانات
    init_db()
    
    # إنشاء التطبيق
    application = Application.builder().token(TOKEN).build()
    
    # إنشاء جدولة المهام
    scheduler = AsyncIOScheduler()
    
    # إضافة مهمة إعادة تعيين المحاولات اليومية
    scheduler.add_job(
        reset_daily_attempts_job,
        trigger='cron',
        hour=0,
        minute=0,
        second=0,
        args=[application]
    )
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    
    # إضافة معالج المحادثة
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            WAITING_FOR_GROUP_ACTION: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_GROUP_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, group_id_handler),
            ],
            WAITING_FOR_TOTP_SECRET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, totp_secret_handler),
            ],
            WAITING_FOR_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, interval_handler),
            ],
            WAITING_FOR_MESSAGE_FORMAT: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_TIMEZONE: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_GROUP_SELECTION: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_USER_SELECTION: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_USER_ACTION: [
                CallbackQueryHandler(button_handler),
            ],
            WAITING_FOR_ATTEMPTS_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, attempts_number_handler),
            ],
            WAITING_FOR_ADMIN_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_id_handler),
            ],
        },
        fallbacks=[CommandHandler("admin", admin_command)],
    )
    
    application.add_handler(conv_handler)
    
    # إضافة معالج استعلامات الأزرار العامة
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # بدء جدولة المهام
    scheduler.start()
    
    # بدء البوت
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("تم بدء تشغيل البوت بنجاح.")
    
    # الانتظار حتى إيقاف البوت
    await application.updater.stop()
    await application.stop()
    await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

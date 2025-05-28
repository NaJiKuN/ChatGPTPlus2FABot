# -*- coding: utf-8 -*- M2.0
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler, JobQueue

# تمكين التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# توكن البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"

# معرف المسؤول الأولي
INITIAL_ADMIN_ID = 764559466

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
) = range(10)

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
        message_format TEXT DEFAULT '🔐 2FA Verification Code\n\nNext code at: {next_time}',
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
        remaining_attempts INTEGER DEFAULT 3,
        is_banned BOOLEAN DEFAULT 0,
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

def get_all_groups():
    """الحصول على جميع المجموعات من قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT group_id, totp_secret, interval_minutes, is_active FROM groups")
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

def add_or_update_group(group_id, totp_secret, interval_minutes=10, message_format=None, timezone=None, time_format=None, is_active=1):
    """إضافة أو تحديث مجموعة في قاعدة البيانات."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # التحقق مما إذا كانت المجموعة موجودة
    cursor.execute("SELECT 1 FROM groups WHERE group_id = ?", (group_id,))
    exists = cursor.fetchone() is not None
    
    if exists:
        # تحديث المجموعة الموجودة
        update_query = "UPDATE groups SET"
        params = []
        
        if totp_secret:
            update_query += " totp_secret = ?,"
            params.append(totp_secret)
        
        if interval_minutes:
            update_query += " interval_minutes = ?,"
            params.append(interval_minutes)
        
        if message_format:
            update_query += " message_format = ?,"
            params.append(message_format)
        
        if timezone:
            update_query += " timezone = ?,"
            params.append(timezone)
            
        if time_format:
            update_query += " time_format = ?,"
            params.append(time_format)
        
        update_query += " is_active = ?"
        params.append(is_active)
        
        update_query += " WHERE group_id = ?"
        params.append(group_id)
        
        cursor.execute(update_query, params)
    else:
        # إدراج مجموعة جديدة
        cursor.execute(
            "INSERT INTO groups (group_id, totp_secret, interval_minutes, is_active) VALUES (?, ?, ?, ?)",
            (group_id, totp_secret, interval_minutes, is_active)
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

def get_users_in_group(group_id):
    """الحصول على جميع المستخدمين في مجموعة محددة."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, remaining_attempts, is_banned FROM user_attempts WHERE group_id = ?", (group_id,))
    users = cursor.fetchall()
    conn.close()
    return users

def update_user_attempts(group_id, user_id, attempts_change, is_banned=None):
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
        
        cursor.execute("UPDATE user_attempts SET remaining_attempts = ?, is_banned = ? WHERE group_id = ? AND user_id = ?",
                      (new_attempts, new_banned, group_id, user_id))
    else:
        # مستخدم جديد، تعيين القيم الافتراضية
        new_attempts = max(0, 3 + attempts_change)  # افتراضياً 3 محاولات
        new_banned = is_banned if is_banned is not None else 0
        
        cursor.execute("INSERT INTO user_attempts (group_id, user_id, remaining_attempts, is_banned) VALUES (?, ?, ?, ?)",
                      (group_id, user_id, new_attempts, new_banned))
    
    conn.commit()
    conn.close()
    return new_attempts

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

# --- وظائف TOTP ---
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

# --- معالجات الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال رسالة ترحيب عند إصدار أمر /start."""
    await update.message.reply_text('مرحباً! أنا بوت ChatGPTPlus2FABot لإرسال رموز 2FA. استخدم /admin للوصول إلى لوحة التحكم إذا كنت مسؤولاً.')

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أمر /admin، وإظهار لوحة المسؤول إذا كان المستخدم مسؤولاً."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text('عذراً، هذا الأمر مخصص للمسؤولين فقط.')
        return

    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
        [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
        [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
        [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('لوحة تحكم المسؤول:', reply_markup=reply_markup)

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
            group_id, _, interval, is_active = group
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
        
    elif query.data == 'back_to_admin':
        # العودة إلى قائمة المسؤول الرئيسية
        keyboard = [
            [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
            [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
            [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
            [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text='لوحة تحكم المسؤول:', reply_markup=reply_markup)
        return ConversationHandler.END
    
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
        
    elif query.data == 'list_groups':
        groups = get_all_groups()
        if not groups:
            message = "لا توجد مجموعات مضافة بعد."
        else:
            message = "المجموعات المضافة:\n\n"
            for i, group in enumerate(groups, 1):
                group_id, secret, interval, is_active = group
                status = "نشط ✅" if is_active else "غير نشط ❌"
                # إخفاء سر TOTP للأمان
                masked_secret = f"{secret[:3]}...{secret[-3:]}" if secret else "غير محدد"
                message += f"{i}. المجموعة: {group_id}\n   السر: {masked_secret}\n   التكرار: كل {interval} دقائق\n   الحالة: {status}\n\n"
        
        keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_manage_groups')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=message, reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة تأكيد حذف المجموعة
    elif query.data.startswith('delete_'):
        group_id = query.data.split('_')[1]
        delete_group(group_id)
        await query.edit_message_text(text=f"تم حذف المجموعة {group_id} بنجاح.")
        
        # العودة إلى قائمة إدارة المجموعة
        keyboard = [
            [InlineKeyboardButton("إضافة/تعديل مجموعة", callback_data='add_edit_group')],
            [InlineKeyboardButton("حذف مجموعة", callback_data='delete_group')],
            [InlineKeyboardButton("عرض المجموعات", callback_data='list_groups')],
            [InlineKeyboardButton("العودة", callback_data='back_to_admin')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="إدارة المجموعات و TOTP:", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_ACTION
    
    # معالجة اختيار الفاصل الزمني لمجموعة
    elif query.data.startswith('interval_'):
        group_id = query.data.split('_')[1]
        context.user_data['selected_group'] = group_id
        
        keyboard = [
            [InlineKeyboardButton("1 دقيقة", callback_data='set_interval_1')],
            [InlineKeyboardButton("5 دقائق", callback_data='set_interval_5')],
            [InlineKeyboardButton("10 دقائق", callback_data='set_interval_10')],
            [InlineKeyboardButton("15 دقيقة", callback_data='set_interval_15')],
            [InlineKeyboardButton("30 دقيقة", callback_data='set_interval_30')],
            [InlineKeyboardButton("60 دقيقة", callback_data='set_interval_60')],
            [InlineKeyboardButton("إيقاف التكرار", callback_data='set_interval_stop')],
            [InlineKeyboardButton("العودة", callback_data='admin_set_interval')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"اختر مدة التكرار للمجموعة {group_id}:", reply_markup=reply_markup)
        return WAITING_FOR_INTERVAL
    
    # معالجة تعيين الفاصل الزمني
    elif query.data.startswith('set_interval_'):
        group_id = context.user_data.get('selected_group')
        if not group_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة.")
            return ConversationHandler.END
        
        if query.data == 'set_interval_stop':
            # تعطيل المجموعة
            add_or_update_group(group_id, None, None, None, None, None, 0)
            await query.edit_message_text(text=f"تم إيقاف التكرار للمجموعة {group_id} بنجاح.")
        else:
            interval = int(query.data.split('_')[-1])
            add_or_update_group(group_id, None, interval, None, None, None, 1)
            await query.edit_message_text(text=f"تم تعيين مدة التكرار للمجموعة {group_id} إلى {interval} دقيقة بنجاح.")
        
        # العودة إلى قائمة اختيار الفاصل الزمني
        keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_set_interval')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="تم تحديث مدة التكرار بنجاح.", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
    
    # معالجة اختيار تنسيق الرسالة لمجموعة
    elif query.data.startswith('format_'):
        group_id = query.data.split('_')[1]
        context.user_data['selected_group'] = group_id
        
        keyboard = [
            [InlineKeyboardButton("توقيت فلسطين (12 ساعة)", callback_data='set_format_jerusalem_12h')],
            [InlineKeyboardButton("توقيت فلسطين (24 ساعة)", callback_data='set_format_jerusalem_24h')],
            [InlineKeyboardButton("التوقيت العالمي (12 ساعة)", callback_data='set_format_utc_12h')],
            [InlineKeyboardButton("التوقيت العالمي (24 ساعة)", callback_data='set_format_utc_24h')],
            [InlineKeyboardButton("العودة", callback_data='admin_set_format')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"اختر تنسيق الوقت للمجموعة {group_id}:", reply_markup=reply_markup)
        return WAITING_FOR_MESSAGE_FORMAT
    
    # معالجة تعيين تنسيق الرسالة
    elif query.data.startswith('set_format_'):
        group_id = context.user_data.get('selected_group')
        if not group_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة.")
            return ConversationHandler.END
        
        format_parts = query.data.split('_')
        timezone = "Asia/Jerusalem" if format_parts[2] == "jerusalem" else "UTC"
        time_format = format_parts[3]
        
        add_or_update_group(group_id, None, None, None, timezone, time_format)
        
        await query.edit_message_text(
            text=f"تم تعيين تنسيق الوقت للمجموعة {group_id} إلى {timezone} ({time_format}) بنجاح."
        )
        
        # العودة إلى قائمة اختيار التنسيق
        keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_set_format')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="تم تحديث تنسيق الوقت بنجاح.", reply_markup=reply_markup)
        return WAITING_FOR_GROUP_SELECTION
    
    # معالجة إدارة المحاولات لمجموعة
    elif query.data.startswith('attempts_'):
        group_id = query.data.split('_')[1]
        context.user_data['selected_group'] = group_id
        
        users = get_users_in_group(group_id)
        if not users:
            await query.edit_message_text(text=f"لا يوجد مستخدمين في المجموعة {group_id} بعد.")
            keyboard = [[InlineKeyboardButton("العودة", callback_data='admin_manage_attempts')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="لا يوجد مستخدمين لإدارة محاولاتهم.", reply_markup=reply_markup)
            return WAITING_FOR_GROUP_SELECTION
        
        keyboard = []
        for user in users:
            user_id, attempts, banned = user
            status = "🚫 محظور" if banned else f"✅ {attempts} محاولات"
            keyboard.append([InlineKeyboardButton(f"المستخدم: {user_id} | {status}", 
                                                 callback_data=f'user_{user_id}')])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data='admin_manage_attempts')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"اختر المستخدم لإدارة محاولاته في المجموعة {group_id}:", 
                                     reply_markup=reply_markup)
        return WAITING_FOR_USER_SELECTION
    
    # معالجة اختيار المستخدم لإدارة المحاولات
    elif query.data.startswith('user_'):
        user_id = query.data.split('_')[1]
        group_id = context.user_data.get('selected_group')
        if not group_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة.")
            return ConversationHandler.END
        
        context.user_data['selected_user'] = user_id
        attempts, banned = get_user_attempts(group_id, user_id)
        
        keyboard = []
        if banned:
            keyboard.append([InlineKeyboardButton("إلغاء الحظر", callback_data='unban_user')])
        else:
            keyboard.append([InlineKeyboardButton("حظر المستخدم", callback_data='ban_user')])
        
        keyboard.extend([
            [InlineKeyboardButton("إضافة محاولات", callback_data='add_attempts')],
            [InlineKeyboardButton("حذف محاولات", callback_data='remove_attempts')],
            [InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')],
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        status = "محظور 🚫" if banned else f"متبقي {attempts} محاولات ✅"
        await query.edit_message_text(
            text=f"إدارة المستخدم {user_id} في المجموعة {group_id}:\nالحالة: {status}", 
            reply_markup=reply_markup
        )
        return WAITING_FOR_USER_ACTION
    
    # معالجة إجراءات المستخدم لإدارة المحاولات
    elif query.data in ['ban_user', 'unban_user', 'add_attempts', 'remove_attempts']:
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        if not group_id or not user_id:
            await query.edit_message_text(text="حدث خطأ: لم يتم تحديد المجموعة أو المستخدم.")
            return ConversationHandler.END
        
        if query.data == 'ban_user':
            update_user_attempts(group_id, user_id, 0, 1)  # حظر المستخدم
            await query.edit_message_text(text=f"تم حظر المستخدم {user_id} في المجموعة {group_id} بنجاح.")
            
            # العودة إلى اختيار المستخدم
            keyboard = [[InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="تم تحديث حالة المستخدم بنجاح.", reply_markup=reply_markup)
            return WAITING_FOR_USER_SELECTION
            
        elif query.data == 'unban_user':
            update_user_attempts(group_id, user_id, 0, 0)  # إلغاء حظر المستخدم
            await query.edit_message_text(text=f"تم إلغاء حظر المستخدم {user_id} في المجموعة {group_id} بنجاح.")
            
            # العودة إلى اختيار المستخدم
            keyboard = [[InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text="تم تحديث حالة المستخدم بنجاح.", reply_markup=reply_markup)
            return WAITING_FOR_USER_SELECTION
            
        elif query.data == 'add_attempts':
            context.user_data['attempts_action'] = 'add'
            await query.edit_message_text(text="الرجاء إدخال عدد المحاولات المراد إضافتها:")
            return WAITING_FOR_ATTEMPTS_NUMBER
            
        elif query.data == 'remove_attempts':
            context.user_data['attempts_action'] = 'remove'
            await query.edit_message_text(text="الرجاء إدخال عدد المحاولات المراد حذفها:")
            return WAITING_FOR_ATTEMPTS_NUMBER
    
    return ConversationHandler.END

# --- معالجات الرسائل ---
async def handle_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال معرف المجموعة."""
    group_id = update.message.text.strip()
    
    try:
        group_id = int(group_id)
        context.user_data['group_id'] = group_id
        
        # التحقق مما إذا كانت المجموعة موجودة
        group = get_group(group_id)
        if group:
            await update.message.reply_text(
                f"المجموعة {group_id} موجودة بالفعل. الرجاء إدخال TOTP_SECRET الجديد أو اكتب 'نفسه' للإبقاء على القيمة الحالية:"
            )
        else:
            await update.message.reply_text("الرجاء إدخال TOTP_SECRET للمجموعة الجديدة:")
        
        return WAITING_FOR_TOTP_SECRET
    except ValueError:
        await update.message.reply_text("خطأ: الرجاء إدخال معرف مجموعة صالح (رقم صحيح).")
        return WAITING_FOR_GROUP_ID

async def handle_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال سر TOTP."""
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get('group_id')
    
    if not group_id:
        await update.message.reply_text("حدث خطأ: لم يتم تحديد المجموعة.")
        return ConversationHandler.END
    
    # التحقق مما إذا كانت المجموعة موجودة
    group = get_group(group_id)
    
    if totp_secret.lower() == 'نفسه' and group:
        # الاحتفاظ بالسر الحالي
        totp_secret = group[1]  # بافتراض أن totp_secret في الفهرس 1
    
    # التحقق من صحة سر TOTP (تحقق أساسي)
    if len(totp_secret) < 16:
        await update.message.reply_text("خطأ: TOTP_SECRET يجب أن يكون 16 حرفاً على الأقل.")
        return WAITING_FOR_TOTP_SECRET
    
    # الحفظ في user_data
    context.user_data['totp_secret'] = totp_secret
    
    # إضافة أو تحديث المجموعة
    is_update = add_or_update_group(group_id, totp_secret)
    
    if is_update:
        await update.message.reply_text(f"تم تحديث المجموعة {group_id} بنجاح مع TOTP_SECRET الجديد.")
    else:
        await update.message.reply_text(f"تم إضافة المجموعة {group_id} بنجاح مع TOTP_SECRET.")
    
    # العودة إلى قائمة المسؤول
    keyboard = [
        [InlineKeyboardButton("إدارة المجموعات و TOTP", callback_data='admin_manage_groups')],
        [InlineKeyboardButton("تحديد مدة التكرار", callback_data='admin_set_interval')],
        [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data='admin_set_format')],
        [InlineKeyboardButton("إدارة محاولات النسخ", callback_data='admin_manage_attempts')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('لوحة تحكم المسؤول:', reply_markup=reply_markup)
    
    return ConversationHandler.END

async def handle_attempts_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة إدخال عدد المحاولات."""
    try:
        attempts = int(update.message.text.strip())
        if attempts < 0:
            await update.message.reply_text("خطأ: الرجاء إدخال رقم موجب.")
            return WAITING_FOR_ATTEMPTS_NUMBER
        
        group_id = context.user_data.get('selected_group')
        user_id = context.user_data.get('selected_user')
        action = context.user_data.get('attempts_action')
        
        if not group_id or not user_id or not action:
            await update.message.reply_text("حدث خطأ: بيانات غير مكتملة.")
            return ConversationHandler.END
        
        if action == 'add':
            new_attempts = update_user_attempts(group_id, user_id, attempts)
            await update.message.reply_text(
                f"تم إضافة {attempts} محاولات للمستخدم {user_id}. العدد الجديد: {new_attempts}"
            )
        else:  # remove
            new_attempts = update_user_attempts(group_id, user_id, -attempts)
            await update.message.reply_text(
                f"تم حذف {attempts} محاولات من المستخدم {user_id}. العدد الجديد: {new_attempts}"
            )
        
        # العودة إلى اختيار المستخدم
        keyboard = [[InlineKeyboardButton("العودة", callback_data=f'attempts_{group_id}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("تم تحديث عدد المحاولات بنجاح.", reply_markup=reply_markup)
        
        return WAITING_FOR_USER_SELECTION
        
    except ValueError:
        await update.message.reply_text("خطأ: الرجاء إدخال رقم صحيح.")
        return WAITING_FOR_ATTEMPTS_NUMBER

# --- توليد رمز TOTP وإرساله ---
async def send_verification_code(context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال رموز التحقق إلى المجموعات النشطة."""
    try:
        # الحصول على جميع المجموعات النشطة
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT group_id, totp_secret, interval_minutes, message_format, timezone, time_format FROM groups WHERE is_active = 1"
        )
        active_groups = cursor.fetchall()
        conn.close()
        
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
            keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f'copy_code_{group_id}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                # إرسال رسالة إلى المجموعة
                await context.bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)
                logger.info(f"تم إرسال رسالة رمز التحقق إلى المجموعة {group_id}")
            except Exception as e:
                logger.error(f"فشل إرسال رسالة إلى المجموعة {group_id}: {e}")
    
    except Exception as e:
        logger.error(f"خطأ في send_verification_code: {e}")

async def handle_copy_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة النقر على زر Copy Code."""
    query = update.callback_query
    await query.answer()
    
    # استخراج group_id من بيانات الاستدعاء
    parts = query.data.split('_')
    if len(parts) != 3 or parts[0] != 'copy' or parts[1] != 'code':
        return
    
    group_id = parts[2]
    user_id = query.from_user.id
    
    # التحقق مما إذا كان المستخدم محظوراً
    attempts, is_banned = get_user_attempts(group_id, user_id)
    
    if is_banned:
        await query.answer("أنت محظور من استخدام هذه الميزة.", show_alert=True)
        return
    
    if attempts <= 0:
        await query.answer("لا توجد محاولات متبقية. الرجاء التواصل مع المسؤول.", show_alert=True)
        return
    
    # الحصول على سر TOTP لهذه المجموعة
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT totp_secret FROM groups WHERE group_id = ?", (group_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result or not result[0]:
        await query.answer("لم يتم تكوين سر TOTP لهذه المجموعة.", show_alert=True)
        return
    
    totp_secret = result[0]
    
    # توليد رمز TOTP
    code = generate_totp(totp_secret)
    
    # تحديث محاولات المستخدم
    new_attempts = update_user_attempts(group_id, user_id, -1)
    
    # إرسال الرمز كرسالة خاصة
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🔐 رمز المصادقة: `{code}`\n\n"
                 f"⚠️ هذا الرمز صالح لمدة 30 ثانية فقط.\n"
                 f"📊 المحاولات المتبقية: {new_attempts}",
            parse_mode='Markdown'
        )
        await query.answer("تم إرسال الرمز في رسالة خاصة.", show_alert=True)
    except Exception as e:
        logger.error(f"فشل إرسال رسالة خاصة إلى المستخدم {user_id}: {e}")
        await query.answer("فشل إرسال الرمز. الرجاء بدء محادثة مع البوت أولاً.", show_alert=True)

# --- الوظيفة الرئيسية ---
def main() -> None:
    """بدء تشغيل البوت."""
    # تهيئة قاعدة البيانات
    init_db()

    # إنشاء التطبيق وتمرير توكن البوت الخاص بك.
    application = Application.builder().token(TOKEN).job_queue(JobQueue(timezone=pytz.timezone("Asia/Jerusalem"))).build()

    # إضافة معالج المحادثة للوحة المسؤول
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            WAITING_FOR_GROUP_ACTION: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_id)],
            WAITING_FOR_TOTP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_totp_secret)],
            WAITING_FOR_GROUP_SELECTION: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_INTERVAL: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_MESSAGE_FORMAT: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_USER_SELECTION: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_USER_ACTION: [CallbackQueryHandler(button_handler)],
            WAITING_FOR_ATTEMPTS_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_attempts_number)],
        },
        fallbacks=[CommandHandler("admin", admin_command)],
    )
    
    application.add_handler(conv_handler)

    # إضافة معالجات أخرى
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_copy_code, pattern='^copy_code_'))

    # إضافة وظيفة لإرسال رموز التحقق
    job_queue = application.job_queue
    
    # ملاحظة: في بيئة الإنتاج، ستستخدم نهجاً أكثر تطوراً
    # لجدولة المهام. هذا تنفيذ مبسط للتوضيح.
    job_queue.run_repeating(send_verification_code, interval=600, first=10)  # التحقق كل 10 دقائق

    # تشغيل البوت حتى يضغط المستخدم على Ctrl-C
    logger.info("بدء تشغيل ChatGPTPlus2FABot...")
    application.run_polling()

if __name__ == "__main__":
    main()

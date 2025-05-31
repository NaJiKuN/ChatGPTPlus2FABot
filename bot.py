import sqlite3
import pyotp
import schedule
import threading
import time
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler
)

# إعدادات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = "764559466"  # المسؤول الافتراضي
DB_PATH = "/home/ec2-user/projects/ChatGPTPlus2FABot/bot.db"

# حالات المحادثة
ADD_GROUP, EDIT_GROUP, DEL_GROUP, SET_PERIOD, SET_MESSAGE_FORMAT, SET_TIMEZONE, SET_ATTEMPTS, SELECT_GROUP, SELECT_USER, ADD_ATTEMPTS, DEL_ATTEMPTS, BAN_USER, ADD_ADMIN, DEL_ADMIN = range(13)

# إعداد قاعدة البيانات
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        group_id TEXT PRIMARY KEY, totp_secret TEXT, period INTEGER, message_format INTEGER, timezone TEXT, running INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (admin_id TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_attempts (
        user_id TEXT, group_id TEXT, attempts INTEGER, last_reset TEXT, PRIMARY KEY (user_id, group_id))''')
    c.execute('INSERT OR IGNORE INTO admins (admin_id) VALUES (?)', (ADMIN_ID,))
    conn.commit()
    conn.close()

# دالة لتوليد رمز TOTP
def generate_2fa_code(totp_secret):
    totp = pyotp.TOTP(totp_secret, interval=30)
    return totp.now()

# دالة للحصول على الوقت الحالي والتالي
def get_times(timezone_str):
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    current_time = now.strftime("%I:%M:%S %p")
    next_time = (now + timedelta(minutes=10)).strftime("%I:%M:%S %p")
    return current_time, next_time

# دالة لإرسال الرسائل الدورية
def send_periodic_message(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id, message_format, timezone, period FROM groups WHERE running = 1")
    groups = c.fetchall()
    for group_id, message_format, timezone, period in groups:
        current_time, next_time = get_times(timezone)
        if message_format == 1:
            message = "🔐 2FA Verification Code\n\nNext code at: " + next_time
        elif message_format == 2:
            message = f"🔐 2FA Verification Code\n\nNext code in: {period} minutes\nNext code at: {next_time}"
        else:
            message = f"🔐 2FA Verification Code\nNext code in: {period} minutes\nCorrect Time: {current_time}\nNext Code at: {next_time}"
        keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)
    conn.close()

# جدولة الرسائل الدورية
def schedule_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id, period FROM groups WHERE running = 1")
    groups = c.fetchall()
    conn.close()
    schedule.clear()
    for group_id, period in groups:
        schedule.every(period).minutes.do(send_periodic_message, context=app.context_types.context)
    while True:
        schedule.run_pending()
        time.sleep(1)

# التحقق من المسؤول
def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return result is not None

# التحقق من المحاولات
def check_attempts(user_id, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT attempts, last_reset FROM user_attempts WHERE user_id = ? AND group_id = ?", (str(user_id), group_id))
    result = c.fetchone()
    if result:
        attempts, last_reset = result
        if last_reset != today:
            c.execute("UPDATE user_attempts SET attempts = 3, last_reset = ? WHERE user_id = ? AND group_id = ?", (today, str(user_id), group_id))
            conn.commit()
            attempts = 3
        conn.close()
        return attempts
    else:
        c.execute("INSERT INTO user_attempts (user_id, group_id, attempts, last_reset) VALUES (?, ?, 3, ?)", (str(user_id), group_id, today))
        conn.commit()
        conn.close()
        return 3

# أمر /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("عذرًا، هذا الأمر مخصص للمسؤولين فقط!")
        return
    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_period")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مرحبًا بك في لوحة إدارة ChatGPTPlus2FABot! اختر خيارًا:", reply_markup=reply_markup)

# إدارة المجموعات
async def manage_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("إضافة مجموعة", callback_data="add_group")],
        [InlineKeyboardButton("تعديل مجموعة", callback_data="edit_group")],
        [InlineKeyboardButton("حذف مجموعة", callback_data="del_group")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر إجراءً لإدارة المجموعات:", reply_markup=reply_markup)
    return ADD_GROUP

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("أدخل معرف المجموعة (مثال: -100XXXXXXXXXX):")
    return ADD_GROUP

async def add_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.message.text
    if not group_id.startswith("-100"):
        await update.message.reply_text("معرف المجموعة غير صحيح! يجب أن يبدأ بـ -100")
        return ADD_GROUP
    context.user_data["group_id"] = group_id
    await update.message.reply_text("أدخل TOTP_SECRET للمجموعة:")
    return ADD_GROUP

async def add_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    totp_secret = update.message.text
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (group_id, totp_secret, period, message_format, timezone, running) VALUES (?, ?, 10, 1, 'UTC', 1)", (group_id, totp_secret))
        conn.commit()
        await update.message.reply_text(f"تم إضافة المجموعة {group_id} بنجاح!")
    except:
        await update.message.reply_text("فشل في إضافة المجموعة! تأكد من المعرف أو TOTP_SECRET.")
    conn.close()
    return ConversationHandler.END

async def edit_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM groups")
    groups = c.fetchall()
    conn.close()
    if not groups:
        await query.message.reply_text("لا توجد مجموعات مضافة!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(group[0], callback_data=f"edit_group_{group[0]}")] for group in groups]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المجموعة لتعديلها:", reply_markup=reply_markup)
    return EDIT_GROUP

async def edit_group_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    context.user_data["group_id"] = group_id
    await query.message.reply_text(f"أدخل TOTP_SECRET الجديد للمجموعة {group_id}:")
    return EDIT_GROUP

async def edit_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    totp_secret = update.message.text
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE groups SET totp_secret = ? WHERE group_id = ?", (totp_secret, group_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم تعديل TOTP_SECRET للمجموعة {group_id} بنجاح!")
    return ConversationHandler.END

async def del_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM groups")
    groups = c.fetchall()
    conn.close()
    if not groups:
        await query.message.reply_text("لا توجد مجموعات مضافة!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(group[0], callback_data=f"del_group_{group[0]}")] for group in groups]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المجموعة لحذفها:", reply_markup=reply_markup)
    return DEL_GROUP

async def del_group_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM user_attempts WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()
    await query.message.reply_text(f"تم حذف المجموعة {group_id} بنجاح!")
    return ConversationHandler.END

# إدارة فترة التكرار
async def manage_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM groups")
    groups = c.fetchall()
    conn.close()
    if not groups:
        await query.message.reply_text("لا توجد مجموعات مضافة!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(group[0], callback_data=f"set_period_{group[0]}")] for group in groups]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المجموعة لإدارة فترة التكرار:", reply_markup=reply_markup)
    return SET_PERIOD

async def set_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    context.user_data["group_id"] = group_id
    keyboard = [
        [InlineKeyboardButton("1 دقيقة", callback_data="period_1"), InlineKeyboardButton("5 دقائق", callback_data="period_5")],
        [InlineKeyboardButton("10 دقائق", callback_data="period_10"), InlineKeyboardButton("15 دقيقة", callback_data="period_15")],
        [InlineKeyboardButton("30 دقيقة", callback_data="period_30"), InlineKeyboardButton("ساعة", callback_data="period_60")],
        [InlineKeyboardButton("3 ساعات", callback_data="period_180"), InlineKeyboardButton("12 ساعة", callback_data="period_720")],
        [InlineKeyboardButton("24 ساعة", callback_data="period_1440")],
        [InlineKeyboardButton("إيقاف التكرار", callback_data="stop_period"), InlineKeyboardButton("بدء التكرار", callback_data="start_period")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"اختر فترة التكرار للمجموعة {group_id}:", reply_markup=reply_markup)
    return SET_PERIOD

async def set_period_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    action = query.data
    if action.startswith("period_"):
        period = int(action.split("_")[-1])
        c.execute("UPDATE groups SET period = ?, running = 1 WHERE group_id = ?", (period, group_id))
        conn.commit()
        await query.message.reply_text(f"تم تعيين فترة التكرار للمجموعة {group_id} إلى {period} دقيقة!")
    elif action == "stop_period":
        c.execute("UPDATE groups SET running = 0 WHERE group_id = ?", (group_id,))
        conn.commit()
        await query.message.reply_text(f"تم إيقاف التكرار للمجموعة {group_id}!")
    elif action == "start_period":
        c.execute("UPDATE groups SET running = 1 WHERE group_id = ?", (group_id,))
        conn.commit()
        await query.message.reply_text(f"تم بدء التكرار للمجموعة {group_id}!")
    conn.close()
    return ConversationHandler.END

# إدارة شكل/توقيت الرسالة
async def manage_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id FROM groups")
    groups = c.fetchall()
    conn.close()
    if not groups:
        await query.message.reply_text("لا توجد مجموعات مضافة!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(group[0], callback_data=f"set_message_{group[0]}")] for group in groups]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المجموعة لإدارة شكل/توقيت الرسالة:", reply_markup=reply_markup)
    return SET_MESSAGE_FORMAT

async def set_message_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    context.user_data["group_id"] = group_id
    keyboard = [
        [InlineKeyboardButton("الشكل 1", callback_data="format_1")],
        [InlineKeyboardButton("الشكل 2", callback_data="format_2")],
        [InlineKeyboardButton("الشكل 3", callback_data="format_3")],
        [InlineKeyboardButton("توقيت غرينتش", callback_data="tz_UTC")],
        [InlineKeyboardButton("توقيت غزة", callback_data="tz_Asia/Gaza")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"اختر شكل الرسالة أو التوقيت للمجموعة {group_id}:", reply_markup=reply_markup)
    return SET_MESSAGE_FORMAT

async def set_message_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    action = query.data
    if action.startswith("format_"):
        format_id = int(action.split("_")[-1])
        c.execute("UPDATE groups SET message_format = ? WHERE group_id = ?", (format_id, group_id))
        conn.commit()
        await query.message.reply_text(f"تم تعيين شكل الرسالة {format_id} للمجموعة {group_id}!")
    elif action.startswith("tz_"):
        timezone = action.split("_")[-1]
        c.execute("UPDATE groups SET timezone = ? WHERE group_id = ?", (timezone, group_id))
        conn.commit()
        await query.message.reply_text(f"تم تعيين التوقيت إلى {timezone} للمجموعة {group_id}!")
    conn.close()
    return ConversationHandler.END

# إدارة محاولات المستخدمين
async def manage_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT group_id FROM user_attempts")
    groups = c.fetchall()
    conn.close()
    if not groups:
        await query.message.reply_text("لا توجد مجموعات تحتوي على مستخدمين!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(group[0], callback_data=f"select_group_{group[0]}")] for group in groups]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المجموعة لإدارة محاولات المستخدمين:", reply_markup=reply_markup)
    return SELECT_GROUP

async def select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    context.user_data["group_id"] = group_id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, attempts FROM user_attempts WHERE group_id = ?", (group_id,))
    users = c.fetchall()
    conn.close()
    if not users:
        await query.message.reply_text(f"لا يوجد مستخدمين في المجموعة {group_id}!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"User ID: {u[0]} | محاولات: {u[1]}", callback_data=f"select_user_{u[0]}")] for u in users]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"اختر المستخدم في المجموعة {group_id}:", reply_markup=reply_markup)
    return SELECT_USER

async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.data.split("_")[-1]
    context.user_data["user_id"] = user_id
    keyboard = [
        [InlineKeyboardButton("حظر المستخدم", callback_data="ban_user")],
        [InlineKeyboardButton("إضافة محاولات", callback_data="add_attempts")],
        [InlineKeyboardButton("حذف محاولات", callback_data="del_attempts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(f"اختر إجراء للمستخدم {user_id}:", reply_markup=reply_markup)
    return SELECT_USER

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = context.user_data["user_id"]
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE user_attempts SET attempts = 0 WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    conn.commit()
    conn.close()
    await query.message.reply_text(f"تم حظر المستخدم {user_id} في المجموعة {group_id}!")
    return ConversationHandler.END

async def add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("أدخل عدد المحاولات لإضافتها:")
    return ADD_ATTEMPTS

async def add_attempts_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attempts = update.message.text
    if not attempts.isdigit():
        await update.message.reply_text("يرجى إدخال رقم صحيح!")
        return ADD_ATTEMPTS
    user_id = context.user_data["user_id"]
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE user_attempts SET attempts = attempts + ? WHERE user_id = ? AND group_id = ?", (int(attempts), user_id, group_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم إضافة {attempts} محاولات للمستخدم {user_id} في المجموعة {group_id}!")
    return ConversationHandler.END

async def del_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("أدخل عدد المحاولات للحذف:")
    return DEL_ATTEMPTS

async def del_attempts_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attempts = update.message.text
    if not attempts.isdigit():
        await update.message.reply_text("يرجى إدخال رقم صحيح!")
        return DEL_ATTEMPTS
    user_id = context.user_data["user_id"]
    group_id = context.user_data["group_id"]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE user_attempts SET attempts = attempts - ? WHERE user_id = ? AND group_id = ?", (int(attempts), user_id, group_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم حذف {attempts} محاولات من المستخدم {user_id} في المجموعة {group_id}!")
    return ConversationHandler.END

# إدارة المسؤولين
async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin")],
        [InlineKeyboardButton("إزالة مسؤول", callback_data="del_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر إجراءً لإدارة المسؤولين:", reply_markup=reply_markup)
    return ADD_ADMIN

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("أدخل User ID للمسؤول الجديد:")
    return ADD_ADMIN

async def add_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.message.text
    if not admin_id.isdigit():
        await update.message.reply_text("يرجى إدخال User ID صحيح!")
        return ADD_ADMIN
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (admin_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"تم إضافة المسؤول {admin_id} بنجاح!")
    return ConversationHandler.END

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT admin_id FROM admins")
    admins = c.fetchall()
    conn.close()
    if not admins:
        await query.message.reply_text("لا يوجد مسؤولين مضافين!")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(admin[0], callback_data=f"del_admin_{admin[0]}")] for admin in admins]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر المسؤول لإزالته:", reply_markup=reply_markup)
    return DEL_ADMIN

async def del_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.data.split("_")[-1]
    if admin_id == ADMIN_ID:
        await query.message.reply_text("لا يمكن حذف المسؤول الافتراضي!")
        return ConversationHandler.END
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE admin_id = ?", (admin_id,))
    conn.commit()
    conn.close()
    await query.message.reply_text(f"تم إزالة المسؤول {admin_id} بنجاح!")
    return ConversationHandler.END

# زر Copy Code
async def copy_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    group_id = query.data.split("_")[-1]
    user_id = str(query.from_user.id)
    attempts = check_attempts(user_id, group_id)
    if attempts <= 0:
        await query.message.reply_text("لقد نفدت محاولاتك! انتظر حتى منتصف الليل لتحديث المحاولات.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT totp_secret FROM groups WHERE group_id = ?", (group_id,))
    result = c.fetchone()
    if not result:
        await query.message.reply_text("المجموعة غير موجودة!")
        return
    totp_secret = result[0]
    code = generate_2fa_code(totp_secret)
    c.execute("UPDATE user_attempts SET attempts = attempts - 1 WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    conn.commit()
    conn.close()
    message = f"🔐 رمز المصادقة الثنائية: `{code}`\n\n" \
              f"عدد المحاولات المتبقية: {attempts - 1}\n" \
              f"⚠️ تحذير: الرمز صالح لمدة 30 ثانية فقط!\n" \
              f"⏳ صلاحية الرمز المتبقية: 30 ثانية"
    await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")
    await query.message.reply_text("تم إرسال رمز المصادقة إلى دردشتك الخاصة!")

# تشغيل البوت
if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TOKEN).build()

    # محادثة إدارة المجموعات
    group_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_groups, pattern="manage_groups")],
        states={
            ADD_GROUP: [
                CallbackQueryHandler(add_group, pattern="add_group"),
                CommandHandler("admin", admin_command),
                MessageHandler(None, add_group_id),
                MessageHandler(None, add_totp_secret)
            ],
            EDIT_GROUP: [
                CallbackQueryHandler(edit_group, pattern="edit_group"),
                CallbackQueryHandler(edit_group_select, pattern="edit_group_"),
                MessageHandler(None, edit_totp_secret)
            ],
            DEL_GROUP: [
                CallbackQueryHandler(del_group, pattern="del_group"),
                CallbackQueryHandler(del_group_select, pattern="del_group_")
            ]
        },
        fallbacks=[]
    )

    # محادثة إدارة الفترة
    period_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_period, pattern="manage_period")],
        states={
            SET_PERIOD: [
                CallbackQueryHandler(set_period, pattern="set_period_"),
                CallbackQueryHandler(set_period_value, pattern="period_|stop_period|start_period")
            ]
        },
        fallbacks=[]
    )

    # محادثة إدارة شكل/توقيت الرسالة
    message_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_message, pattern="manage_message")],
        states={
            SET_MESSAGE_FORMAT: [
                CallbackQueryHandler(set_message_format, pattern="set_message_"),
                CallbackQueryHandler(set_message_value, pattern="format_|tz_")
            ]
        },
        fallbacks=[]
    )

    # محادثة إدارة المحاولات
    attempts_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_attempts, pattern="manage_attempts")],
        states={
            SELECT_GROUP: [CallbackQueryHandler(select_group, pattern="select_group_")],
            SELECT_USER: [
                CallbackQueryHandler(select_user, pattern="select_user_"),
                CallbackQueryHandler(ban_user, pattern="ban_user"),
                CallbackQueryHandler(add_attempts, pattern="add_attempts"),
                CallbackQueryHandler(del_attempts, pattern="del_attempts")
            ],
            ADD_ATTEMPTS: [MessageHandler(None, add_attempts_value)],
            DEL_ATTEMPTS: [MessageHandler(None, del_attempts_value)]
        },
        fallbacks=[]
    )

    # محادثة إدارة المسؤولين
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_admins, pattern="manage_admins")],
        states={
            ADD_ADMIN: [
                CallbackQueryHandler(add_admin, pattern="add_admin"),
                MessageHandler(None, add_admin_id)
            ],
            DEL_ADMIN: [
                CallbackQueryHandler(del_admin, pattern="del_admin"),
                CallbackQueryHandler(del_admin_id, pattern="del_admin_")
            ]
        },
        fallbacks=[]
    )

    # إضافة المعالجات
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(group_conv)
    app.add_handler(period_conv)
    app.add_handler(message_conv)
    app.add_handler(attempts_conv)
    app.add_handler(admin_conv)
    app.add_handler(CallbackQueryHandler(copy_code, pattern="copy_code_"))

    # تشغيل الجدولة في خيط منفصل
    threading.Thread(target=schedule_messages, daemon=True).start()

    # تشغيل البوت
    app.run_polling()

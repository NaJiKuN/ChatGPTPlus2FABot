#xx1.0
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import pyotp
import pytz

# إعداد السجل لتتبع الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# إعدادات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
DB_PATH = "/home/ec2-user/projects/ChatGPTPlus2FABot/bot.db"

# إعداد قاعدة البيانات
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# إنشاء الجداول إذا لم تكن موجودة
cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    totp_secret TEXT,
                    update_interval INTEGER,
                    message_format TEXT,
                    max_clicks INTEGER,
                    is_active INTEGER DEFAULT 1
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
                    admin_id TEXT PRIMARY KEY
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_clicks (
                    group_id TEXT,
                    user_id TEXT,
                    clicks_used INTEGER,
                    PRIMARY KEY (group_id, user_id)
                )''')
conn.commit()

# إضافة المسؤول الافتراضي
cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", ("764559466",))
conn.commit()

# دالة للتحقق مما إذا كان المستخدم مسؤولاً
def is_admin(user_id):
    cursor.execute("SELECT * FROM admins WHERE admin_id = ?", (str(user_id),))
    return cursor.fetchone() is not None

# دالة للحصول على الوقت الحالي بناءً على التنسيق
def get_current_time(format_type):
    if format_type == "UTC":
        tz = pytz.utc
    elif format_type == "Palestine":
        tz = pytz.timezone("Asia/Gaza")
    else:
        tz = pytz.utc
    return datetime.now(tz).strftime("%I:%M:%S %p")

# دالة لتوليد رمز TOTP
def generate_totp(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()

# دالة لإرسال الرمز إلى المجموعة
def send_code_to_group(application, group_id, secret, format_type):
    code = generate_totp(secret)
    next_time = (datetime.now() + timedelta(minutes=10)).strftime("%I:%M:%S %p")
    message = f"🔐 2FA Verification Code\n\nNext code at: {next_time}"
    keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}_{code}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    application.bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)

# دالة لجدولة إرسال الرموز
def schedule_code_sending(application, group_id, secret, interval, format_type):
    while True:
        cursor.execute("SELECT is_active FROM groups WHERE group_id = ?", (group_id,))
        is_active = cursor.fetchone()[0]
        if is_active:
            send_code_to_group(application, group_id, secret, format_type)
        time.sleep(interval * 60)

# معالج الأمر /admin
async def admin_command(update: Update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("ليس لديك صلاحية لاستخدام هذا الأمر.")
        return
    keyboard = [
        [InlineKeyboardButton("إضافة مجموعة", callback_data="add_group")],
        [InlineKeyboardButton("تحديد فترة التحديث", callback_data="set_interval")],
        [InlineKeyboardButton("تخصيص شكل الرسالة", callback_data="set_format")],
        [InlineKeyboardButton("تشغيل/إيقاف البوت", callback_data="toggle_bot")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر الخيار:", reply_markup=reply_markup)

# معالج الضغط على الأزرار
async def button_handler(update: Update, context):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "add_group":
        await query.message.reply_text("أدخل معرف المجموعة:")
        context.user_data["step"] = "enter_group_id"
    elif data == "set_interval":
        cursor.execute("SELECT group_id FROM groups")
        groups = cursor.fetchall()
        if not groups:
            await query.message.reply_text("لا توجد مجموعات مضافة.")
            return
        keyboard = [[InlineKeyboardButton(group[0], callback_data=f"select_group_interval_{group[0]}")] for group in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اختر المجموعة:", reply_markup=reply_markup)
    elif data.startswith("select_group_interval_"):
        group_id = data.split("_")[-1]
        context.user_data["selected_group"] = group_id
        await query.message.reply_text("أدخل فترة التحديث بالدقائق:")
        context.user_data["step"] = "enter_interval"
    elif data == "set_format":
        cursor.execute("SELECT group_id FROM groups")
        groups = cursor.fetchall()
        if not groups:
            await query.message.reply_text("لا توجد مجموعات مضافة.")
            return
        keyboard = [[InlineKeyboardButton(group[0], callback_data=f"select_group_format_{group[0]}")] for group in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اختر المجموعة:", reply_markup=reply_markup)
    elif data.startswith("select_group_format_"):
        group_id = data.split("_")[-1]
        context.user_data["selected_group"] = group_id
        keyboard = [
            [InlineKeyboardButton("UTC", callback_data="format_UTC")],
            [InlineKeyboardButton("Palestine", callback_data="format_Palestine")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اختر التنسيق:", reply_markup=reply_markup)
    elif data.startswith("format_"):
        format_type = data.split("_")[1]
        group_id = context.user_data["selected_group"]
        cursor.execute("UPDATE groups SET message_format = ? WHERE group_id = ?", (format_type, group_id))
        conn.commit()
        await query.message.reply_text(f"تم تعيين التنسيق إلى {format_type} للمجموعة {group_id}")
    elif data == "toggle_bot":
        cursor.execute("SELECT group_id FROM groups")
        groups = cursor.fetchall()
        if not groups:
            await query.message.reply_text("لا توجد مجموعات مضافة.")
            return
        keyboard = [[InlineKeyboardButton(group[0], callback_data=f"toggle_group_{group[0]}")] for group in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("اختر المجموعة لتشغيل/إيقاف البوت:", reply_markup=reply_markup)
    elif data.startswith("toggle_group_"):
        group_id = data.split("_")[-1]
        cursor.execute("SELECT is_active FROM groups WHERE group_id = ?", (group_id,))
        is_active = cursor.fetchone()[0]
        new_state = 0 if is_active else 1
        cursor.execute("UPDATE groups SET is_active = ? WHERE group_id = ?", (new_state, group_id))
        conn.commit()
        state_text = "مشغل" if new_state else "موقف"
        await query.message.reply_text(f"تم تعيين حالة البوت للمجموعة {group_id} إلى: {state_text}")
    elif data.startswith("copy_code_"):
        parts = data.split("_")
        group_id = parts[2]
        code = parts[3]
        user_id = query.from_user.id
        cursor.execute("SELECT max_clicks FROM groups WHERE group_id = ?", (group_id,))
        max_clicks = cursor.fetchone()[0]
        cursor.execute("SELECT clicks_used FROM user_clicks WHERE group_id = ? AND user_id = ?", (group_id, str(user_id)))
        user_clicks = cursor.fetchone()
        clicks_used = user_clicks[0] if user_clicks else 0
        remaining = max_clicks - clicks_used
        if clicks_used < max_clicks:
            await query.answer(code, show_alert=True)
            clicks_used += 1
            cursor.execute("INSERT OR REPLACE INTO user_clicks (group_id, user_id, clicks_used) VALUES (?, ?, ?)", 
                           (group_id, str(user_id), clicks_used))
            conn.commit()
            await query.message.reply_text(f"تم نسخ الرمز. المحاولات المتبقية: {remaining - 1}")
        else:
            await query.answer(f"لقد استنفدت عدد المحاولات المسموح بها ({max_clicks}).", show_alert=True)
            await query.message.reply_text(f"المحاولات المتبقية: 0")

# معالج الرسائل
async def message_handler(update: Update, context):
    if "step" not in context.user_data:
        return
    step = context.user_data["step"]
    if step == "enter_group_id":
        group_id = update.message.text
        context.user_data["group_id"] = group_id
        await update.message.reply_text("أدخل TOTP_SECRET:")
        context.user_data["step"] = "enter_totp_secret"
    elif step == "enter_totp_secret":
        totp_secret = update.message.text
        group_id = context.user_data["group_id"]
        cursor.execute("INSERT OR REPLACE INTO groups (group_id, totp_secret, update_interval, message_format, max_clicks, is_active) VALUES (?, ?, ?, ?, ?, ?)", 
                       (group_id, totp_secret, 10, "UTC", 5, 1))  # افتراضي: 10 دقائق، UTC، 5 ضغطات، نشط
        conn.commit()
        await update.message.reply_text(f"تم إضافة المجموعة {group_id} بنجاح.")
        threading.Thread(target=schedule_code_sending, args=(context.application, group_id, totp_secret, 10, "UTC")).start()
        del context.user_data["step"]
    elif step == "enter_interval":
        interval = int(update.message.text)
        group_id = context.user_data["selected_group"]
        cursor.execute("UPDATE groups SET update_interval = ? WHERE group_id = ?", (interval, group_id))
        conn.commit()
        await update.message.reply_text(f"تم تعيين فترة التحديث إلى {interval} دقيقة للمجموعة {group_id}")
        del context.user_data["step"]

# الدالة الرئيسية
def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # بدء جدولة الإرسال للمجموعات الموجودة مسبقًا
    cursor.execute("SELECT group_id, totp_secret, update_interval, message_format FROM groups WHERE is_active = 1")
    groups = cursor.fetchall()
    for group in groups:
        threading.Thread(target=schedule_code_sending, args=(application, group[0], group[1], group[2], group[3])).start()
    
    application.run_polling()

if __name__ == "__main__":
    main()

import os
import time
import pytz
from datetime import datetime, timedelta
import json
import hashlib
import base64
import hmac
import struct
from threading import Thread
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    MessageHandler,
    Filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Load configuration
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466  # Replace with your admin ID

# File paths
DATA_FILE = "data.json"
LOG_FILE = "bot.log"

# Initialize data structure
DEFAULT_DATA = {
    "groups": {},
    "admins": [ADMIN_ID],
    "user_attempts": {},
    "message_styles": {},
    "update_intervals": {},
    "message_templates": {
        "style1": "🔐 2FA Verification Code\n\nNext code at: {next_time}",
        "style2": "🔐 2FA Verification Code\n\nNext code in: {minutes_left} minutes\nNext code at: {next_time}",
        "style3": "🔐 2FA Verification Code\nNext code in: {minutes_left} minutes\nCorrect Time: {current_time}\nNext Code at: {next_time}",
    },
    "default_style": "style1",
    "default_interval": 600,  # 10 minutes in seconds
    "default_attempts": 5,
    "timezone": "Asia/Gaza",
}

# Load or initialize data
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_DATA.copy()

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# TOTP functions
def generate_totp(secret, interval=30):
    try:
        key = base64.b32decode(secret, casefold=True)
        msg = struct.pack(">Q", int(time.time()) // interval)
        h = hmac.new(key, msg, hashlib.sha1).digest()
        o = h[19] & 15
        h = (struct.unpack(">I", h[o:o+4])[0] & 0x7fffffff) % 1000000
        return f"{h:06d}"
    except:
        return "000000"

# Helper functions
def get_current_time(tz="Asia/Gaza"):
    tz = pytz.timezone(tz)
    return datetime.now(tz)

def format_time(dt, time_format="%I:%M:%S %p"):
    return dt.strftime(time_format)

def log_message(message):
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now()}: {message}\n")

# Bot handlers
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        update.message.reply_text("مرحباً بك في نظام إدارة 2FA. استخدم الأمر /admin للوصول إلى لوحة التحكم.")
    else:
        update.message.reply_text("مرحباً! يمكنك الحصول على رمز التحقق من المجموعة.")

def admin_panel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    data = load_data()
    
    if user_id not in data["admins"]:
        update.message.reply_text("⚠️ ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return
    
    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_intervals")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message_style")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_user_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("لوحة تحكم المسؤول:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = load_data()
    user_id = query.from_user.id
    
    if user_id not in data["admins"]:
        query.edit_message_text(text="⚠️ ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return
    
    action = query.data
    
    if action == "manage_groups":
        manage_groups(query)
    elif action == "manage_intervals":
        manage_intervals(query)
    elif action == "manage_message_style":
        manage_message_style(query)
    elif action == "manage_user_attempts":
        manage_user_attempts(query)
    elif action == "manage_admins":
        manage_admins(query)
    elif action.startswith("group_"):
        handle_group_action(query, action)
    elif action.startswith("interval_"):
        handle_interval_action(query, action)
    elif action.startswith("style_"):
        handle_style_action(query, action)
    elif action.startswith("attempts_"):
        handle_attempts_action(query, action)
    elif action.startswith("admin_"):
        handle_admin_action(query, action)
    elif action == "copy_code":
        handle_copy_code(query)

def manage_groups(query):
    data = load_data()
    keyboard = [
        [InlineKeyboardButton("إضافة مجموعة", callback_data="group_add")],
        [InlineKeyboardButton("حذف مجموعة", callback_data="group_remove")],
        [InlineKeyboardButton("تعديل مجموعة", callback_data="group_edit")],
        [InlineKeyboardButton("عرض المجموعات", callback_data="group_list")],
        [InlineKeyboardButton("العودة", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="إدارة المجموعات ورموز TOTP:", reply_markup=reply_markup)

def manage_intervals(query):
    data = load_data()
    keyboard = [
        [InlineKeyboardButton("1 دقيقة", callback_data="interval_60")],
        [InlineKeyboardButton("5 دقائق", callback_data="interval_300")],
        [InlineKeyboardButton("10 دقائق", callback_data="interval_600")],
        [InlineKeyboardButton("15 دقيقة", callback_data="interval_900")],
        [InlineKeyboardButton("30 دقيقة", callback_data="interval_1800")],
        [InlineKeyboardButton("ساعة", callback_data="interval_3600")],
        [InlineKeyboardButton("3 ساعات", callback_data="interval_10800")],
        [InlineKeyboardButton("12 ساعة", callback_data="interval_43200")],
        [InlineKeyboardButton("24 ساعة", callback_data="interval_86400")],
        [InlineKeyboardButton("إيقاف التكرار", callback_data="interval_0")],
        [InlineKeyboardButton("العودة", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="اختر مدة تكرار رمز المصادقة:", reply_markup=reply_markup)

def manage_message_style(query):
    data = load_data()
    keyboard = [
        [InlineKeyboardButton("الشكل الأول", callback_data="style_1")],
        [InlineKeyboardButton("الشكل الثاني", callback_data="style_2")],
        [InlineKeyboardButton("الشكل الثالث", callback_data="style_3")],
        [InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data="style_timezone")],
        [InlineKeyboardButton("العودة", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="اختر شكل الرسالة:", reply_markup=reply_markup)

def manage_user_attempts(query):
    data = load_data()
    keyboard = [
        [InlineKeyboardButton("حدد عدد مرات النسخ", callback_data="attempts_set")],
        [InlineKeyboardButton("عرض محاولات المستخدمين", callback_data="attempts_list")],
        [InlineKeyboardButton("إعادة تعيين المحاولات", callback_data="attempts_reset")],
        [InlineKeyboardButton("العودة", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="إدارة محاولات المستخدمين:", reply_markup=reply_markup)

def manage_admins(query):
    data = load_data()
    keyboard = [
        [InlineKeyboardButton("إضافة مسؤول", callback_data="admin_add")],
        [InlineKeyboardButton("حذف مسؤول", callback_data="admin_remove")],
        [InlineKeyboardButton("عرض المسؤولين", callback_data="admin_list")],
        [InlineKeyboardButton("العودة", callback_data="back_to_admin")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="إدارة المسؤولين:", reply_markup=reply_markup)

def handle_group_action(query, action):
    data = load_data()
    
    if action == "group_add":
        query.edit_message_text(text="أرسل معرف المجموعة بالشكل التالي:\n/addgroup GROUP_ID TOTP_SECRET")
    elif action == "group_remove":
        if not data["groups"]:
            query.edit_message_text(text="لا توجد مجموعات مسجلة.")
            return
        
        keyboard = []
        for group_id in data["groups"]:
            keyboard.append([InlineKeyboardButton(f"Group {group_id}", callback_data=f"group_remove_{group_id}")])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_groups")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="اختر مجموعة للحذف:", reply_markup=reply_markup)
    elif action == "group_edit":
        if not data["groups"]:
            query.edit_message_text(text="لا توجد مجموعات مسجلة.")
            return
        
        keyboard = []
        for group_id in data["groups"]:
            keyboard.append([InlineKeyboardButton(f"Group {group_id}", callback_data=f"group_edit_{group_id}")])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_groups")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="اختر مجموعة للتعديل:", reply_markup=reply_markup)
    elif action == "group_list":
        if not data["groups"]:
            query.edit_message_text(text="لا توجد مجموعات مسجلة.")
            return
        
        groups_info = "المجموعات المسجلة:\n\n"
        for group_id, group_data in data["groups"].items():
            groups_info += f"Group ID: {group_id}\nTOTP: {group_data['totp_secret'][:4]}...\nInterval: {group_data.get('interval', data['default_interval'])} seconds\n\n"
        
        query.edit_message_text(text=groups_info)
    elif action.startswith("group_remove_"):
        group_id = action.split("_")[-1]
        if group_id in data["groups"]:
            del data["groups"][group_id]
            save_data(data)
            query.edit_message_text(text=f"تم حذف المجموعة {group_id} بنجاح.")
        else:
            query.edit_message_text(text="المجموعة غير موجودة.")
    elif action.startswith("group_edit_"):
        group_id = action.split("_")[-1]
        if group_id in data["groups"]:
            context.user_data["editing_group"] = group_id
            query.edit_message_text(text=f"أرسل TOTP_SECRET الجديد للمجموعة {group_id}:")
        else:
            query.edit_message_text(text="المجموعة غير موجودة.")

def handle_interval_action(query, action):
    data = load_data()
    
    if action == "back_to_admin":
        admin_panel(query)
        return
    
    if action.startswith("interval_"):
        interval = int(action.split("_")[1])
        context.user_data["selected_interval"] = interval
        
        if "selected_group" in context.user_data:
            group_id = context.user_data["selected_group"]
            if group_id in data["groups"]:
                data["groups"][group_id]["interval"] = interval
                save_data(data)
                query.edit_message_text(text=f"تم تعيين فترة التكرار لـ {group_id} إلى {interval} ثانية.")
            else:
                query.edit_message_text(text="المجموعة غير موجودة.")
        else:
            data["default_interval"] = interval
            save_data(data)
            query.edit_message_text(text=f"تم تعيين فترة التكرار الافتراضية إلى {interval} ثانية.")

def handle_style_action(query, action):
    data = load_data()
    
    if action == "style_1":
        data["default_style"] = "style1"
        save_data(data)
        query.edit_message_text(text="تم تعيين شكل الرسالة إلى النمط الأول.")
    elif action == "style_2":
        data["default_style"] = "style2"
        save_data(data)
        query.edit_message_text(text="تم تعيين شكل الرسالة إلى النمط الثاني.")
    elif action == "style_3":
        data["default_style"] = "style3"
        save_data(data)
        query.edit_message_text(text="تم تعيين شكل الرسالة إلى النمط الثالث.")
    elif action == "style_timezone":
        keyboard = [
            [InlineKeyboardButton("توقيت غرينتش (GMT)", callback_data="timezone_UTC")],
            [InlineKeyboardButton("توقيت غزة (GMT+3)", callback_data="timezone_Asia/Gaza")],
            [InlineKeyboardButton("العودة", callback_data="manage_message_style")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="اختر المنطقة الزمنية:", reply_markup=reply_markup)
    elif action.startswith("timezone_"):
        timezone = action.split("_")[1]
        data["timezone"] = timezone
        save_data(data)
        query.edit_message_text(text=f"تم تعيين المنطقة الزمنية إلى {timezone}.")

def handle_attempts_action(query, action):
    data = load_data()
    
    if action == "attempts_set":
        data["default_attempts"] = context.user_data.get("attempts_count", 5)
        save_data(data)
        query.edit_message_text(text=f"تم تعيين عدد المحاولات الافتراضي إلى {data['default_attempts']}.")
    elif action == "attempts_list":
        if not data["user_attempts"]:
            query.edit_message_text(text="لا توجد بيانات محاولات للمستخدمين.")
            return
        
        attempts_info = "محاولات المستخدمين:\n\n"
        for user_id, attempts in data["user_attempts"].items():
            attempts_info += f"User ID: {user_id}\nالمحاولات المتبقية: {attempts['remaining']}\nآخر محاولة: {attempts.get('last_attempt', 'غير معروف')}\n\n"
        
        query.edit_message_text(text=attempts_info)
    elif action == "attempts_reset":
        data["user_attempts"] = {}
        save_data(data)
        query.edit_message_text(text="تم إعادة تعيين جميع محاولات المستخدمين.")

def handle_admin_action(query, action):
    data = load_data()
    
    if action == "admin_add":
        query.edit_message_text(text="أرسل معرف المستخدم الذي تريد إضافته كمسؤول:")
    elif action == "admin_remove":
        if len(data["admins"]) <= 1:
            query.edit_message_text(text="لا يمكن حذف جميع المسؤولين.")
            return
        
        keyboard = []
        for admin_id in data["admins"]:
            if admin_id != query.from_user.id:  # Can't remove self
                keyboard.append([InlineKeyboardButton(f"Admin {admin_id}", callback_data=f"admin_remove_{admin_id}")])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data="manage_admins")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="اختر مسؤول للحذف:", reply_markup=reply_markup)
    elif action == "admin_list":
        admins_info = "المسؤولون:\n\n"
        for admin_id in data["admins"]:
            admins_info += f"Admin ID: {admin_id}\n"
        
        query.edit_message_text(text=admins_info)
    elif action.startswith("admin_remove_"):
        admin_id = int(action.split("_")[-1])
        if admin_id in data["admins"] and admin_id != query.from_user.id:
            data["admins"].remove(admin_id)
            save_data(data)
            query.edit_message_text(text=f"تم حذف المسؤول {admin_id} بنجاح.")
        else:
            query.edit_message_text(text="لا يمكن حذف هذا المسؤول.")

def handle_copy_code(query):
    user_id = query.from_user.id
    data = load_data()
    
    # Check user attempts
    if str(user_id) not in data["user_attempts"]:
        data["user_attempts"][str(user_id)] = {
            "remaining": data["default_attempts"],
            "last_attempt": datetime.now().isoformat()
        }
    
    if data["user_attempts"][str(user_id)]["remaining"] <= 0:
        query.answer("⚠️ لقد استنفدت جميع محاولاتك اليوم. يرجى المحاولة مرة أخرى بعد منتصف الليل.", show_alert=True)
        return
    
    # Decrement attempts
    data["user_attempts"][str(user_id)]["remaining"] -= 1
    data["user_attempts"][str(user_id)]["last_attempt"] = datetime.now().isoformat()
    save_data(data)
    
    # Find the group this message belongs to
    group_id = str(query.message.chat.id)
    if group_id not in data["groups"]:
        query.answer("⚠️ هذه المجموعة غير مسجلة في النظام.", show_alert=True)
        return
    
    # Generate TOTP code
    totp_secret = data["groups"][group_id]["totp_secret"]
    code = generate_totp(totp_secret)
    
    # Send private message with the code
    remaining_attempts = data["user_attempts"][str(user_id)]["remaining"]
    message = f"""
🔐 رمز التحقق الخاص بك:
📋 <code>{code}</code>

⏱️ صالح لمدة 30 ثانية فقط!
🔄 المحاولات المتبقية: {remaining_attempts}

⚠️ لا تشارك هذا الرمز مع أي شخص.
"""
    
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode=ParseMode.HTML
        )
        query.answer("✅ تم إرسال رمز التحقق إليك في الرسائل الخاصة.", show_alert=True)
    except Exception as e:
        query.answer("⚠️ لا يمكن إرسال الرسالة الخاصة. يرجى التأكد من أنك بدأت محادثة مع البوت.", show_alert=True)
        log_message(f"Failed to send private message to {user_id}: {str(e)}")

# Scheduled job to send codes to groups
def send_scheduled_codes(context: CallbackContext):
    data = load_data()
    current_time = get_current_time(data.get("timezone", "Asia/Gaza"))
    
    for group_id, group_data in data["groups"].items():
        try:
            interval = group_data.get("interval", data["default_interval"])
            if interval <= 0:
                continue  # Skip if interval is disabled
            
            # Generate TOTP code
            totp_secret = group_data["totp_secret"]
            code = generate_totp(totp_secret)
            
            # Calculate next code time
            next_time = current_time + timedelta(seconds=interval)
            minutes_left = interval // 60
            
            # Prepare message based on selected style
            message_style = group_data.get("message_style", data["default_style"])
            message_template = data["message_templates"][message_style]
            
            message = message_template.format(
                next_time=format_time(next_time, "%I:%M:%S %p"),
                minutes_left=minutes_left,
                current_time=format_time(current_time, "%I:%M:%S %p")
            )
            
            # Add copy button
            keyboard = [[InlineKeyboardButton("Copy Code", callback_data="copy_code")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send message to group
            context.bot.send_message(
                chat_id=group_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            log_message(f"Error sending code to group {group_id}: {str(e)}")

# Message handler for admin commands
def message_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    data = load_data()
    
    if user_id not in data["admins"]:
        return
    
    text = update.message.text
    
    if text.startswith("/addgroup"):
        parts = text.split()
        if len(parts) != 3:
            update.message.reply_text("صيغة غير صحيحة. استخدم:\n/addgroup GROUP_ID TOTP_SECRET")
            return
        
        group_id = parts[1]
        totp_secret = parts[2]
        
        if group_id in data["groups"]:
            update.message.reply_text("هذه المجموعة مسجلة بالفعل.")
            return
        
        data["groups"][group_id] = {
            "totp_secret": totp_secret,
            "interval": data["default_interval"],
            "message_style": data["default_style"]
        }
        save_data(data)
        update.message.reply_text(f"تمت إضافة المجموعة {group_id} بنجاح.")
    
    elif text.startswith("/setattempts"):
        parts = text.split()
        if len(parts) != 2:
            update.message.reply_text("صيغة غير صحيحة. استخدم:\n/setattempts NUMBER")
            return
        
        try:
            attempts = int(parts[1])
            data["default_attempts"] = attempts
            save_data(data)
            update.message.reply_text(f"تم تعيين عدد المحاولات الافتراضي إلى {attempts}.")
        except ValueError:
            update.message.reply_text("الرجاء إدخال رقم صحيح.")

    elif text.isdigit() and "editing_group" in context.user_data:
        group_id = context.user_data["editing_group"]
        if group_id in data["groups"]:
            data["groups"][group_id]["totp_secret"] = text
            save_data(data)
            update.message.reply_text(f"تم تحديث TOTP_SECRET للمجموعة {group_id}.")
            del context.user_data["editing_group"]
        else:
            update.message.reply_text("المجموعة غير موجودة.")

    elif text.isdigit() and "manage_admins" in context.user_data:
        try:
            new_admin = int(text)
            if new_admin not in data["admins"]:
                data["admins"].append(new_admin)
                save_data(data)
                update.message.reply_text(f"تمت إضافة المسؤول {new_admin} بنجاح.")
            else:
                update.message.reply_text("هذا المستخدم مسؤول بالفعل.")
        except ValueError:
            update.message.reply_text("الرجاء إدخال معرف مستخدم صحيح.")

# Reset attempts at midnight
def reset_attempts():
    data = load_data()
    for user_id in data["user_attempts"]:
        data["user_attempts"][user_id]["remaining"] = data["default_attempts"]
    save_data(data)
    log_message("تم إعادة تعيين محاولات جميع المستخدمين.")

# Main function
def main():
    # Initialize data file if not exists
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
    
    # Create updater and dispatcher
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Add handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", admin_panel))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, message_handler))
    
    # Initialize scheduler for code generation
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_scheduled_codes,
        trigger=IntervalTrigger(seconds=30),  # Check every 30 seconds
        args=[updater],
        max_instances=1
    )
    
    # Schedule daily reset at midnight
    scheduler.add_job(
        reset_attempts,
        trigger='cron',
        hour=0,
        minute=0
    )
    
    scheduler.start()
    
    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

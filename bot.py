import os
import json
import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pyotp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    Bot,
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

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466
DEFAULT_INTERVAL = 10  # 10 دقائق افتراضياً

# مسارات الملفات
BASE_DIR = "/home/ec2-user/projects/ChatGPTPlus2FABot"
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
GROUPS_FILE = os.path.join(BASE_DIR, "groups.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# تهيئة الملفات إذا لم تكن موجودة
for file_path in [CONFIG_FILE, GROUPS_FILE, USERS_FILE]:
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            if file_path == CONFIG_FILE:
                json.dump({"admin_ids": [ADMIN_ID]}, f)
            elif file_path == GROUPS_FILE:
                json.dump({}, f)
            else:
                json.dump({}, f)

# وظائف مساعدة لقراءة/كتابة الملفات
def read_json(file_path: str) -> Dict:
    with open(file_path, "r") as f:
        return json.load(f)

def write_json(data: Dict, file_path: str) -> None:
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

# وظائف التوقيت
def get_current_time(timezone: str = "Gaza") -> datetime:
    tz = pytz.timezone("Asia/Gaza") if timezone == "Gaza" else pytz.utc
    return datetime.now(tz)

def format_time(dt: datetime, show_seconds: bool = True) -> str:
    time_format = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
    return dt.strftime(time_format).lstrip("0")

def calculate_next_run(interval: int, timezone: str = "Gaza") -> datetime:
    now = get_current_time(timezone)
    next_run = now + timedelta(minutes=interval)
    return next_run

# وظائف إدارة المجموعات والمستخدمين
def get_group_data(group_id: str) -> Optional[Dict]:
    groups = read_json(GROUPS_FILE)
    return groups.get(group_id)

def update_group_data(group_id: str, data: Dict) -> None:
    groups = read_json(GROUPS_FILE)
    groups[group_id] = data
    write_json(groups, GROUPS_FILE)

def get_user_data(group_id: str, user_id: int) -> Dict:
    users = read_json(USERS_FILE)
    group_users = users.get(group_id, {})
    return group_users.get(str(user_id), {"attempts": 3})  # 3 محاولات افتراضية

def update_user_data(group_id: str, user_id: int, data: Dict) -> None:
    users = read_json(USERS_FILE)
    if group_id not in users:
        users[group_id] = {}
    users[group_id][str(user_id)] = data
    write_json(users, USERS_FILE)

# وظائف توليد وإدارة TOTP
def generate_totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()

def format_message(group_id: str) -> str:
    group = get_group_data(group_id)
    if not group:
        return ""
    
    secret = group.get("secret", "")
    interval = group.get("interval", DEFAULT_INTERVAL)
    message_format = group.get("message_format", 1)
    timezone = group.get("timezone", "Gaza")
    
    current_time = get_current_time(timezone)
    next_run = calculate_next_run(interval, timezone)
    time_left = next_run - current_time
    
    minutes_left = int(time_left.total_seconds() // 60)
    seconds_left = int(time_left.total_seconds() % 60)
    
    if message_format == 1:
        message = (
            "🔐 2FA Verification Code\n\n"
            f"Next code at: {format_time(next_run)}"
        )
    elif message_format == 2:
        message = (
            "🔐 2FA Verification Code\n\n"
            f"Next code in: {minutes_left} minutes\n"
            f"Next code at: {format_time(next_run)}"
        )
    else:  # message_format == 3
        message = (
            "🔐 2FA Verification Code\n\n"
            f"Next code in: {minutes_left} minutes {seconds_left} seconds\n"
            f"Current Time: {format_time(current_time)}\n"
            f"Next Code at: {format_time(next_run)}"
        )
    
    return message

# وظائف الجدولة
scheduler = BackgroundScheduler()
scheduler.start()

def schedule_group_message(group_id: str, interval: int) -> None:
    group = get_group_data(group_id)
    if not group:
        return
    
    # إلغاء أي جدولة موجودة مسبقاً
    job_id = f"group_{group_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # جدولة جديدة
    trigger = IntervalTrigger(minutes=interval)
    scheduler.add_job(
        send_scheduled_message,
        trigger,
        args=[group_id],
        id=job_id,
        replace_existing=True
    )

def send_scheduled_message(group_id: str) -> None:
    group = get_group_data(group_id)
    if not group:
        return
    
    chat_id = group_id
    message = format_message(group_id)
    keyboard = [
        [InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Error sending message to group {group_id}: {e}")

# معالجات الأوامر
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("مرحباً! أنا بوت إدارة رموز 2FA. استخدم /admin للوصول إلى لوحة التحكم.")

def admin_panel(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    admins = read_json(CONFIG_FILE).get("admin_ids", [])
    
    if user_id not in admins:
        update.message.reply_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return
    
    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_interval")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_users")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "لوحة تحكم المسؤول:",
        reply_markup=reply_markup
    )

# معالجات الاستعلامات
def handle_callback_query(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data
    
    if data.startswith("copy_code_"):
        handle_copy_code(query)
    elif data == "manage_groups":
        manage_groups(query)
    elif data == "manage_interval":
        manage_interval(query)
    elif data == "manage_message":
        manage_message(query)
    elif data == "manage_users":
        manage_users(query)
    elif data == "manage_admins":
        manage_admins(query)
    elif data.startswith("group_"):
        handle_group_selection(query)
    elif data.startswith("interval_"):
        handle_interval_selection(query)
    elif data.startswith("format_"):
        handle_format_selection(query)
    elif data.startswith("timezone_"):
        handle_timezone_selection(query)
    elif data.startswith("user_action_"):
        handle_user_action(query)
    elif data.startswith("admin_action_"):
        handle_admin_action(query)
    
    query.answer()

def handle_copy_code(query) -> None:
    user_id = query.from_user.id
    group_id = query.data.replace("copy_code_", "")
    
    group = get_group_data(group_id)
    if not group:
        query.answer("خطأ: المجموعة غير موجودة.", show_alert=True)
        return
    
    user_data = get_user_data(group_id, user_id)
    
    if user_data.get("banned", False):
        query.answer("أنت محظور من استخدام هذه الخدمة.", show_alert=True)
        return
    
    if user_data["attempts"] <= 0:
        query.answer("لقد استنفدت جميع محاولاتك.", show_alert=True)
        return
    
    # توليد الرمز
    secret = group.get("secret", "")
    if not secret:
        query.answer("خطأ: لم يتم تعيين سر TOTP.", show_alert=True)
        return
    
    code = generate_totp(secret)
    
    # تحديث محاولات المستخدم
    user_data["attempts"] -= 1
    update_user_data(group_id, user_id, user_data)
    
    # إرسال الرمز للمستخدم
    remaining_attempts = user_data["attempts"]
    message = (
        f"🔐 رمز التحقق: `{code}`\n\n"
        f"المحاولات المتبقية: {remaining_attempts}\n"
        "⚠️ هذا الرمز صالح لمدة 30 ثانية فقط"
    )
    
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        query.answer("تم إرسال الرمز إليك في الرسائل الخاصة.", show_alert=True)
    except Exception as e:
        query.answer("فشل إرسال الرمز. تأكد من أنك بدأت محادثة مع البوت.", show_alert=True)

def manage_groups(query) -> None:
    groups = read_json(GROUPS_FILE)
    keyboard = []
    
    # زر إضافة مجموعة جديدة
    keyboard.append([InlineKeyboardButton("➕ إضافة مجموعة", callback_data="add_group")])
    
    # أزرار المجموعات الموجودة
    for group_id in groups:
        keyboard.append([
            InlineKeyboardButton(f"✏️ تعديل {group_id}", callback_data=f"edit_group_{group_id}"),
            InlineKeyboardButton(f"🗑️ حذف {group_id}", callback_data=f"delete_group_{group_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text="إدارة المجموعات و TOTP_SECRET:",
        reply_markup=reply_markup
    )

def manage_interval(query) -> None:
    groups = read_json(GROUPS_FILE)
    if not groups:
        query.answer("لا توجد مجموعات مسجلة.", show_alert=True)
        return
    
    keyboard = []
    
    for group_id in groups:
        interval = groups[group_id].get("interval", DEFAULT_INTERVAL)
        keyboard.append([
            InlineKeyboardButton(f"🕒 {group_id} (كل {interval} دقائق)", callback_data=f"group_{group_id}_interval")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text="اختر مجموعة لتعديل فترة التكرار:",
        reply_markup=reply_markup
    )

def manage_message(query) -> None:
    groups = read_json(GROUPS_FILE)
    if not groups:
        query.answer("لا توجد مجموعات مسجلة.", show_alert=True)
        return
    
    keyboard = []
    
    for group_id in groups:
        keyboard.append([
            InlineKeyboardButton(f"✉️ {group_id}", callback_data=f"group_{group_id}_message")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text="اختر مجموعة لتعديل شكل الرسالة:",
        reply_markup=reply_markup
    )

def manage_users(query) -> None:
    groups = read_json(GROUPS_FILE)
    users = read_json(USERS_FILE)
    
    active_groups = []
    for group_id in groups:
        if group_id in users and users[group_id]:
            active_groups.append(group_id)
    
    if not active_groups:
        query.answer("لا توجد مجموعات بها مستخدمين.", show_alert=True)
        return
    
    keyboard = []
    
    for group_id in active_groups:
        keyboard.append([
            InlineKeyboardButton(f"👥 {group_id}", callback_data=f"group_{group_id}_users")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text="اختر مجموعة لإدارة مستخدميها:",
        reply_markup=reply_markup
    )

def manage_admins(query) -> None:
    admins = read_json(CONFIG_FILE).get("admin_ids", [])
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول", callback_data="add_admin")],
        [InlineKeyboardButton("➖ إزالة مسؤول", callback_data="remove_admin")]
    ]
    
    if admins:
        for admin_id in admins:
            keyboard.append([
                InlineKeyboardButton(f"👤 {admin_id}", callback_data=f"admin_info_{admin_id}")
            ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_admin")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text="إدارة المسؤولين:",
        reply_markup=reply_markup
    )

def handle_group_selection(query) -> None:
    data = query.data
    group_id = data.split("_")[1]
    action = data.split("_")[-1]
    
    if action == "interval":
        show_interval_options(query, group_id)
    elif action == "message":
        show_message_options(query, group_id)
    elif action == "users":
        show_group_users(query, group_id)

def show_interval_options(query, group_id: str) -> None:
    intervals = [1, 5, 10, 15, 30, 60, 180, 720, 1440]  # بالدقائق
    current_interval = get_group_data(group_id).get("interval", DEFAULT_INTERVAL)
    
    keyboard = []
    row = []
    
    for interval in intervals:
        text = f"{interval} دقائق"
        if interval == current_interval:
            text = f"✅ {text}"
        
        row.append(InlineKeyboardButton(text, callback_data=f"interval_{group_id}_{interval}"))
        
        if len(row) == 3:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    # زر إيقاف/بدء التكرار
    group = get_group_data(group_id)
    is_active = group.get("active", True)
    toggle_text = "⏸️ إيقاف التكرار" if is_active else "▶️ بدء التكرار"
    keyboard.append([InlineKeyboardButton(toggle_text, callback_data=f"toggle_interval_{group_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="manage_interval")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text=f"اختر فترة التكرار للمجموعة {group_id}:",
        reply_markup=reply_markup
    )

def show_message_options(query, group_id: str) -> None:
    group = get_group_data(group_id)
    current_format = group.get("message_format", 1)
    current_timezone = group.get("timezone", "Gaza")
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✅ ' if current_format == 1 else ''}الشكل 1",
                callback_data=f"format_{group_id}_1"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅ ' if current_format == 2 else ''}الشكل 2",
                callback_data=f"format_{group_id}_2"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅ ' if current_format == 3 else ''}الشكل 3",
                callback_data=f"format_{group_id}_3"
            )
        ],
        [
            InlineKeyboardButton(
                f"التوقيت: {'✅ ' if current_timezone == 'Gaza' else ''}غزة",
                callback_data=f"timezone_{group_id}_Gaza"
            ),
            InlineKeyboardButton(
                f"التوقيت: {'✅ ' if current_timezone == 'GMT' else ''}غرينتش",
                callback_data=f"timezone_{group_id}_GMT"
            )
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="manage_message")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text=f"اختر شكل الرسالة للمجموعة {group_id}:",
        reply_markup=reply_markup
    )

def show_group_users(query, group_id: str) -> None:
    users = read_json(USERS_FILE).get(group_id, {})
    if not users:
        query.answer("لا يوجد مستخدمين في هذه المجموعة.", show_alert=True)
        return
    
    keyboard = []
    
    for user_id, user_data in users.items():
        attempts = user_data.get("attempts", 0)
        banned = user_data.get("banned", False)
        status = "🚫 محظور" if banned else f"🔄 {attempts} محاولات"
        
        keyboard.append([
            InlineKeyboardButton(
                f"👤 {user_id} ({status})",
                callback_data=f"user_{group_id}_{user_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="manage_users")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    query.edit_message_text(
        text=f"اختر مستخدم للمجموعة {group_id}:",
        reply_markup=reply_markup
    )

def handle_interval_selection(query) -> None:
    data = query.data.split("_")
    group_id = data[1]
    interval = int(data[2])
    
    group = get_group_data(group_id)
    group["interval"] = interval
    update_group_data(group_id, group)
    
    schedule_group_message(group_id, interval)
    query.answer(f"تم تعيين التكرار لكل {interval} دقائق للمجموعة {group_id}.")
    show_interval_options(query, group_id)

def handle_format_selection(query) -> None:
    data = query.data.split("_")
    group_id = data[1]
    message_format = int(data[2])
    
    group = get_group_data(group_id)
    group["message_format"] = message_format
    update_group_data(group_id, group)
    
    query.answer(f"تم تعيين الشكل {message_format} للمجموعة {group_id}.")
    show_message_options(query, group_id)

def handle_timezone_selection(query) -> None:
    data = query.data.split("_")
    group_id = data[1]
    timezone = data[2]
    
    group = get_group_data(group_id)
    group["timezone"] = timezone
    update_group_data(group_id, group)
    
    query.answer(f"تم تعيين التوقيت إلى {timezone} للمجموعة {group_id}.")
    show_message_options(query, group_id)

def handle_user_action(query) -> None:
    data = query.data.split("_")
    group_id = data[1]
    user_id = int(data[2])
    action = data[3]
    
    if action == "ban":
        user_data = get_user_data(group_id, user_id)
        user_data["banned"] = True
        update_user_data(group_id, user_id, user_data)
        query.answer(f"تم حظر المستخدم {user_id}.")
    elif action == "unban":
        user_data = get_user_data(group_id, user_id)
        user_data["banned"] = False
        update_user_data(group_id, user_id, user_data)
        query.answer(f"تم إلغاء حظر المستخدم {user_id}.")
    elif action == "add":
        query.message.reply_text(
            f"أدخل عدد المحاولات التي تريد إضافتها للمستخدم {user_id}:"
        )
        context.user_data["pending_action"] = {
            "type": "add_attempts",
            "group_id": group_id,
            "user_id": user_id
        }
        return
    elif action == "remove":
        query.message.reply_text(
            f"أدخل عدد المحاولات التي تريد حذفها من المستخدم {user_id}:"
        )
        context.user_data["pending_action"] = {
            "type": "remove_attempts",
            "group_id": group_id,
            "user_id": user_id
        }
        return
    
    show_group_users(query, group_id)

def handle_admin_action(query) -> None:
    data = query.data
    if data == "add_admin":
        query.message.reply_text("أدخل معرف المستخدم الذي تريد إضافته كمسؤول:")
        context.user_data["pending_action"] = {"type": "add_admin"}
        return
    elif data == "remove_admin":
        query.message.reply_text("أدخل معرف المستخدم الذي تريد إزالته من المسؤولين:")
        context.user_data["pending_action"] = {"type": "remove_admin"}
        return
    
    manage_admins(query)

def handle_text(update: Update, context: CallbackContext) -> None:
    if "pending_action" not in context.user_data:
        return
    
    action = context.user_data["pending_action"]
    text = update.message.text
    
    if action["type"] == "add_admin":
        try:
            admin_id = int(text)
            config = read_json(CONFIG_FILE)
            if admin_id not in config["admin_ids"]:
                config["admin_ids"].append(admin_id)
                write_json(config, CONFIG_FILE)
                update.message.reply_text(f"تمت إضافة {admin_id} كمسؤول بنجاح.")
            else:
                update.message.reply_text("هذا المستخدم مسؤول بالفعل.")
        except ValueError:
            update.message.reply_text("معرف المستخدم يجب أن يكون رقماً.")
    
    elif action["type"] == "remove_admin":
        try:
            admin_id = int(text)
            config = read_json(CONFIG_FILE)
            if admin_id in config["admin_ids"]:
                config["admin_ids"].remove(admin_id)
                write_json(config, CONFIG_FILE)
                update.message.reply_text(f"تمت إزالة {admin_id} من المسؤولين بنجاح.")
            else:
                update.message.reply_text("هذا المستخدم ليس مسؤولاً.")
        except ValueError:
            update.message.reply_text("معرف المستخدم يجب أن يكون رقماً.")
    
    elif action["type"] == "add_attempts":
        try:
            attempts = int(text)
            group_id = action["group_id"]
            user_id = action["user_id"]
            
            user_data = get_user_data(group_id, user_id)
            user_data["attempts"] = user_data.get("attempts", 0) + attempts
            update_user_data(group_id, user_id, user_data)
            
            update.message.reply_text(
                f"تمت إضافة {attempts} محاولة للمستخدم {user_id} في المجموعة {group_id}."
            )
        except ValueError:
            update.message.reply_text("عدد المحاولات يجب أن يكون رقماً.")
    
    elif action["type"] == "remove_attempts":
        try:
            attempts = int(text)
            group_id = action["group_id"]
            user_id = action["user_id"]
            
            user_data = get_user_data(group_id, user_id)
            current_attempts = user_data.get("attempts", 0)
            new_attempts = max(0, current_attempts - attempts)
            user_data["attempts"] = new_attempts
            update_user_data(group_id, user_id, user_data)
            
            update.message.reply_text(
                f"تمت إزالة {attempts} محاولة من المستخدم {user_id} في المجموعة {group_id}."
            )
        except ValueError:
            update.message.reply_text("عدد المحاولات يجب أن يكون رقماً.")
    
    del context.user_data["pending_action"]

def error_handler(update: Update, context: CallbackContext) -> None:
    print(f"حدث خطأ: {context.error}")
    if update.callback_query:
        update.callback_query.answer("حدث خطأ أثناء معالجة طلبك.", show_alert=True)

def main() -> None:
    # تهيئة البوت
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    # تسجيل المعالجات
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("admin", admin_panel))
    dispatcher.add_handler(CallbackQueryHandler(handle_callback_query))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    dispatcher.add_error_handler(error_handler)
    
    # بدء البوت
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

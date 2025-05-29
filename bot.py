import json
import os
import pytz
import pyotp
import asyncio
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import re

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("ChatGPTPlus2FABot")

# مسارات الملفات
BASE_PATH = "/home/ec2-user/projects/ChatGPTPlus2FABot"
CONFIG_FILE = os.path.join(BASE_PATH, "config.json")
GROUPS_FILE = os.path.join(BASE_PATH, "groups.json")
USERS_FILE = os.path.join(BASE_PATH, "users.json")

# الإعدادات الأساسية
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_IDS = ["764559466"]  # سيتم تحديثه من config.json
DEFAULT_ATTEMPTS = 3  # عدد المحاولات الافتراضية لكل مستخدم
TIMEZONES = {"GMT": "UTC", "Gaza": "Asia/Gaza"}
FORMATS = {
    1: "🔐 2FA Verification Code\n\nNext code at: {next_time}",
    2: "🔐 2FA Verification Code\n\nNext code in: {interval}\nNext code at: {next_time}",
    3: "🔐 2FA Verification Code\n\nNext code in: {interval}\nCorrect Time: {current_time}\nNext Code at: {next_time}"
}
INTERVALS = {
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "3h": 10800,
    "12h": 43200,
    "24h": 86400
}

# حالات المحادثة
(
    ADD_GROUP_ID, ADD_GROUP_SECRET, MODIFY_GROUP_ID, MODIFY_GROUP_SECRET,
    DELETE_GROUP, SET_INTERVAL, SET_FORMAT, SET_TIMEZONE, MANAGE_ATTEMPTS_GROUP,
    MANAGE_ATTEMPTS_USER, MANAGE_ATTEMPTS_ACTION, ADD_ATTEMPTS, DELETE_ATTEMPTS,
    ADD_ADMIN, DELETE_ADMIN
) = range(15)

# وظائف مساعدة للتعامل مع JSON
def load_json(file_path, default=None):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return default or {}
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        return default or {}

def save_json(file_path, data):
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving {file_path}: {e}")

# تهيئة البيانات
def initialize_data():
    os.makedirs(BASE_PATH, exist_ok=True)
    config = load_json(CONFIG_FILE, {"admin_ids": ADMIN_IDS})
    groups = load_json(GROUPS_FILE, {})
    users = load_json(USERS_FILE, {})
    return config, groups, users

# تنسيق الوقت
def format_time(dt, timezone_str, time_format=12):
    tz = pytz.timezone(TIMEZONES.get(timezone_str, "UTC"))
    dt = dt.astimezone(tz)
    if time_format == 12:
        return dt.strftime("%I:%M:%S %p")
    return dt.strftime("%H:%M:%S")

# التحقق من معرف المجموعة
def is_valid_group_id(group_id):
    try:
        return group_id.startswith("-100") and group_id[4:].isdigit()
    except:
        return False

# التحقق من TOTP Secret
def is_valid_totp_secret(secret):
    return bool(re.match(r'^[A-Z2-7]{16,}$', secret))

# إنشاء مهمة مجدولة
def schedule_task(application, group_id, interval, scheduler):
    groups = load_json(GROUPS_FILE)
    if group_id not in groups or not groups[group_id].get("active", True):
        return

    async def send_scheduled_message():
        try:
            group = groups.get(group_id, {})
            secret = group.get("totp_secret")
            timezone = group.get("timezone", "GMT")
            format_id = group.get("format", 1)
            interval_seconds = INTERVALS.get(group.get("interval", "10m"), 600)
            tz = pytz.timezone(TIMEZONES.get(timezone, "UTC"))
            current_time = datetime.now(tz)
            next_time = current_time + timedelta(seconds=interval_seconds)
            interval_text = group.get("interval", "10m")
            if interval_text in ["1m", "5m", "10m", "15m", "30m"]:
                interval_display = f"{interval_text[:-1]} minutes"
            elif interval_text == "1h":
                interval_display = "1 hour"
            else:
                interval_display = f"{interval_text[:-1]} hours"

            message_text = FORMATS[format_id].format(
                interval=interval_display,
                current_time=format_time(current_time, timezone),
                next_time=format_time(next_time, timezone)
            )
            keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await application.bot.send_message(
                chat_id=group_id,
                text=message_text,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending scheduled message to {group_id}: {e}")

    job_id = f"send_message_{group_id}"
    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None
    scheduler.add_job(
        send_scheduled_message,
        trigger=IntervalTrigger(seconds=interval),
        id=job_id,
        replace_existing=True
    )

# معالجة زر Copy Code
async def handle_copy_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    group_id = query.data.split("_")[-1]
    users = load_json(USERS_FILE)
    groups = load_json(GROUPS_FILE)

    if group_id not in groups:
        await query.message.reply_text("المجموعة غير موجودة.")
        return

    user_data = users.get(group_id, {}).get(user_id, {"attempts": DEFAULT_ATTEMPTS, "banned": False})
    if user_data["banned"]:
        await query.message.reply_text("أنت محظور من استخدام هذا البوت.")
        return
    if user_data["attempts"] <= 0:
        await query.message.reply_text("لقد استنفدت محاولاتك.")
        return

    # توليد رمز TOTP
    secret = groups[group_id]["totp_secret"]
    totp = pyotp.TOTP(secret)
    code = totp.now()

    # تحديث المحاولات
    user_data["attempts"] -= 1
    if group_id not in users:
        users[group_id] = {}
    users[group_id][user_id] = user_data
    save_json(USERS_FILE, users)

    # إرسال الرمز
    message = (
        f"🔐 رمز المصادقة: `{code}`\n"
        f"المحاولات المتبقية: {user_data['attempts']}\n"
        f"⚠️ الرمز صالح لمدة 30 ثانية فقط!"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.answer(
            text=message.replace("`", ""),
            show_alert=True
        )

# الأمر /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    config = load_json(CONFIG_FILE)
    if user_id not in config.get("admin_ids", ADMIN_IDS):
        await update.message.reply_text("غير مصرح لك باستخدام هذا الأمر.")
        return

    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_interval")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_format")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("💻 لوحة تحكم ChatGPTPlus2FABot", reply_markup=reply_markup)

# معالجة الأزرار
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    config = load_json(CONFIG_FILE)
    if user_id not in config.get("admin_ids", ADMIN_IDS):
        await query.message.reply_text("غير مصرح لك.")
        return

    data = query.data
    if data == "manage_groups":
        keyboard = [
            [InlineKeyboardButton("إضافة مجموعة", callback_data="add_group")],
            [InlineKeyboardButton("تعديل مجموعة", callback_data="modify_group")],
            [InlineKeyboardButton("حذف مجموعة", callback_data="delete_group")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("إدارة المجموعات", reply_markup=reply_markup)

    elif data == "add_group":
        await query.message.edit_text("أدخل معرف المجموعة (مثل -100XXXXXXXXXX):")
        return ADD_GROUP_ID

    elif data == "modify_group":
        groups = load_json(GROUPS_FILE)
        if not groups:
            await query.message.edit_text("لا توجد مجموعات للتعديل.")
            return
        keyboard = [[InlineKeyboardButton(f"Group {gid}", callback_data=f"mod_group_{gid}")] for gid in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المجموعة للتعديل:", reply_markup=reply_markup)

    elif data.startswith("mod_group_"):
        group_id = data.split("_")[-1]
        context.user_data["modify_group_id"] = group_id
        await query.message.edit_text(f"أدخل معرف المجموعة الجديد لـ {group_id} (أو اتركه كما هو):")
        return MODIFY_GROUP_ID

    elif data == "delete_group":
        groups = load_json(GROUPS_FILE)
        if not groups:
            await query.message.edit_text("لا توجد مجموعات لحذفها.")
            return
        keyboard = [[InlineKeyboardButton(f"Group {gid}", callback_data=f"del_group_{gid}")] for gid in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المجموعة لحذفها:", reply_markup=reply_markup)

    elif data.startswith("del_group_"):
        group_id = data.split("_")[-1]
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            del groups[group_id]
            save_json(GROUPS_FILE, groups)
            context.job_queue.scheduler.remove_job(f"send_message_{group_id}")
            await query.message.edit_text(f"تم حذف المجموعة {group_id} بنجاح.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data == "manage_interval":
        groups = load_json(GROUPS_FILE)
        if not groups:
            await query.message.edit_text("لا توجد مجموعات لإدارة التكرار.")
            return
        keyboard = [[InlineKeyboardButton(f"Group {gid}", callback_data=f"set_interval_{gid}")] for gid in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المجموعة لإدارة التكرار:", reply_markup=reply_markup)

    elif data.startswith("set_interval_"):
        group_id = data.split("_")[-1]
        context.user_data["interval_group_id"] = group_id
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"interval_{group_id}_{key}")]
            for key, name in [
                ("1m", "1 دقيقة"), ("5m", "5 دقائق"), ("10m", "10 دقائق"),
                ("15m", "15 دقيقة"), ("30m", "30 دقيقة"), ("1h", "1 ساعة"),
                ("3h", "3 ساعات"), ("12h", "12 ساعة"), ("24h", "24 ساعة")
            ]
        ]
        keyboard.append([InlineKeyboardButton("إيقاف التكرار", callback_data=f"stop_interval_{group_id}")])
        keyboard.append([InlineKeyboardButton("بدء التكرار", callback_data=f"start_interval_{group_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر فترة التكرار:", reply_markup=reply_markup)

    elif data.startswith("interval_"):
        _, group_id, interval = data.split("_")
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            groups[group_id]["interval"] = interval
            groups[group_id]["active"] = True
            save_json(GROUPS_FILE, groups)
            schedule_task(context, group_id, INTERVALS[interval], context.job_queue.scheduler)
            await query.message.edit_text(f"تم تحديث التكرار للمجموعة {group_id} إلى {interval}.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data.startswith("stop_interval_"):
        group_id = data.split("_")[-1]
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            groups[group_id]["active"] = False
            save_json(GROUPS_FILE, groups)
            context.job_queue.scheduler.remove_job(f"send_message_{group_id}")
            await query.message.edit_text(f"تم إيقاف التكرار للمجموعة {group_id}.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data.startswith("start_interval_"):
        group_id = data.split("_")[-1]
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            groups[group_id]["active"] = True
            save_json(GROUPS_FILE, groups)
            interval = INTERVALS.get(groups[group_id]["interval"], 600)
            schedule_task(context, group_id, interval, context.job_queue.scheduler)
            await query.message.edit_text(f"تم بدء التكرار للمجموعة {group_id}.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data == "manage_format":
        groups = load_json(GROUPS_FILE)
        if not groups:
            await query.message.edit_text("لا توجد مجموعات لإدارة الشكل/التوقيت.")
            return
        keyboard = [[InlineKeyboardButton(f"Group {gid}", callback_data=f"set_format_{gid}")] for gid in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المجموعة لإدارة الشكل/التوقيت:", reply_markup=reply_markup)

    elif data.startswith("set_format_"):
        group_id = data.split("_")[-1]
        context.user_data["format_group_id"] = group_id
        keyboard = [
            [InlineKeyboardButton(f"شكل {i}", callback_data=f"format_{group_id}_{i}")] for i in [1, 2, 3]
        ]
        keyboard.append([InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data=f"timezone_{group_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر شكل الرسالة:", reply_markup=reply_markup)

    elif data.startswith("format_"):
        _, group_id, format_id = data.split("_")
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            groups[group_id]["format"] = int(format_id)
            save_json(GROUPS_FILE, groups)
            await query.message.edit_text(f"تم تحديث شكل الرسالة للمجموعة {group_id} إلى الشكل {format_id}.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data.startswith("timezone_"):
        group_id = data.split("_")[-1]
        context.user_data["timezone_group_id"] = group_id
        keyboard = [
            [InlineKeyboardButton(tz, callback_data=f"tz_{group_id}_{tz}")] for tz in TIMEZONES
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المنطقة الزمنية:", reply_markup=reply_markup)

    elif data.startswith("tz_"):
        _, group_id, timezone = data.split("_")
        groups = load_json(GROUPS_FILE)
        if group_id in groups:
            groups[group_id]["timezone"] = timezone
            save_json(GROUPS_FILE, groups)
            await query.message.edit_text(f"تم تحديث المنطقة الزمنية للمجموعة {group_id} إلى {timezone}.")
        else:
            await query.message.edit_text("المجموعة غير موجودة.")

    elif data == "manage_attempts":
        groups = load_json(GROUPS_FILE)
        if not groups:
            await query.message.edit_text("لا توجد مجموعات لإدارة المحاولات.")
            return
        keyboard = [[InlineKeyboardButton(f"Group {gid}", callback_data=f"attempts_group_{gid}")] for gid in groups]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المجموعة لإدارة المحاولات:", reply_markup=reply_markup)

    elif data.startswith("attempts_group_"):
        group_id = data.split("_")[-1]
        context.user_data["attempts_group_id"] = group_id
        users = load_json(USERS_FILE)
        group_users = users.get(group_id, {})
        if not group_users:
            await query.message.edit_text("لا يوجد مستخدمين في هذه المجموعة.")
            return
        keyboard = []
        for uid, udata in group_users.items():
            username = udata.get("username", f"User {uid}")
            attempts = udata.get("attempts", DEFAULT_ATTEMPTS)
            keyboard.append([InlineKeyboardButton(f"{username} ({attempts} محاولات)", callback_data=f"attempts_user_{group_id}_{uid}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المستخدم:", reply_markup=reply_markup)

    elif data.startswith("attempts_user_"):
        _, group_id, user_id = data.split("_")
        context.user_data["attempts_user_id"] = user_id
        context.user_data["attempts_group_id"] = group_id
        keyboard = [
            [InlineKeyboardButton("حظر المستخدم", callback_data=f"ban_user_{group_id}_{user_id}")],
            [InlineKeyboardButton("إضافة محاولات", callback_data=f"add_attempts_{group_id}_{user_id}")],
            [InlineKeyboardButton("حذف محاولات", callback_data=f"del_attempts_{group_id}_{user_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر الإجراء:", reply_markup=reply_markup)

    elif data.startswith("ban_user_"):
        _, group_id, user_id = data.split("_")
        users = load_json(USERS_FILE)
        if group_id in users and user_id in users[group_id]:
            users[group_id][user_id]["banned"] = True
            save_json(USERS_FILE, users)
            await query.message.edit_text(f"تم حظر المستخدم {user_id} في المجموعة {group_id}.")
        else:
            await query.message.edit_text("المستخدم أو المجموعة غير موجود.")

    elif data.startswith("add_attempts_"):
        _, group_id, user_id = data.split("_")
        context.user_data["attempts_group_id"] = group_id
        context.user_data["attempts_user_id"] = user_id
        await query.message.edit_text("أدخل عدد المحاولات لإضافتها:")
        return ADD_ATTEMPTS

    elif data.startswith("del_attempts_"):
        _, group_id, user_id = data.split("_")
        context.user_data["attempts_group_id"] = group_id
        context.user_data["attempts_user_id"] = user_id
        await query.message.edit_text("أدخل عدد المحاولات للحذف:")
        return DELETE_ATTEMPTS

    elif data == "manage_admins":
        keyboard = [
            [InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin")],
            [InlineKeyboardButton("إزالة مسؤول", callback_data="delete_admin")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("إدارة المسؤولين:", reply_markup=reply_markup)

    elif data == "add_admin":
        await query.message.edit_text("أدخل معرف المسؤول لإضافته:")
        return ADD_ADMIN

    elif data == "delete_admin":
        config = load_json(CONFIG_FILE)
        admins = config.get("admin_ids", ADMIN_IDS)
        if len(admins) <= 1:
            await query.message.edit_text("لا يمكن إزالة المسؤول الوحيد.")
            return
        keyboard = [[InlineKeyboardButton(f"Admin {aid}", callback_data=f"del_admin_{aid}")] for aid in admins]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("اختر المسؤول لإزالته:", reply_markup=reply_markup)

    elif data.startswith("del_admin_"):
        admin_id = data.split("_")[-1]
        config = load_json(CONFIG_FILE)
        admins = config.get("admin_ids", ADMIN_IDS)
        if admin_id in admins:
            admins.remove(admin_id)
            config["admin_ids"] = admins
            save_json(CONFIG_FILE, config)
            await query.message.edit_text(f"تم إزالة المسؤول {admin_id}.")
        else:
            await query.message.edit_text("المسؤول غير موجود.")

# معالجات المحادثة
async def add_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.message.text.strip()
    if not is_valid_group_id(group_id):
        await update.message.reply_text("معرف المجموعة غير صالح. يجب أن يبدأ بـ -100 ويتبعه أرقام.")
        return ADD_GROUP_ID
    context.user_data["new_group_id"] = group_id
    await update.message.reply_text("أدخل TOTP Secret:")
    return ADD_GROUP_SECRET

async def add_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secret = update.message.text.strip()
    if not is_valid_totp_secret(secret):
        await update.message.reply_text("TOTP Secret غير صالح. يجب أن يحتوي على أحرف كبيرة وأرقام (2-7) فقط.")
        return ADD_GROUP_SECRET
    group_id = context.user_data.get("new_group_id")
    groups = load_json(GROUPS_FILE)
    if group_id in groups:
        await update.message.reply_text("المجموعة موجودة بالفعل.")
        return ConversationHandler.END
    groups[group_id] = {
        "totp_secret": secret,
        "interval": "10m",
        "format": 1,
        "timezone": "GMT",
        "active": True
    }
    save_json(GROUPS_FILE, groups)
    schedule_task(context, group_id, 600, context.job_queue.scheduler)
    await update.message.reply_text(f"تم إضافة المجموعة {group_id} بنجاح.")
    return ConversationHandler.END

async def modify_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.message.text.strip()
    if not is_valid_group_id(group_id):
        await update.message.reply_text("معرف المجموعة غير صالح. يجب أن يبدأ بـ -100 ويتبعه أرقام.")
        return MODIFY_GROUP_ID
    context.user_data["new_group_id"] = group_id
    await update.message.reply_text("أدخل TOTP Secret الجديد:")
    return MODIFY_GROUP_SECRET

async def modify_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secret = update.message.text.strip()
    if not is_valid_totp_secret(secret):
        await update.message.reply_text("TOTP Secret غير صالح. يجب أن يحتوي على أحرف كبيرة وأرقام (2-7) فقط.")
        return MODIFY_GROUP_SECRET
    old_group_id = context.user_data.get("modify_group_id")
    new_group_id = context.user_data.get("new_group_id")
    groups = load_json(GROUPS_FILE)
    if old_group_id in groups:
        group_data = groups.pop(old_group_id)
        group_data["totp_secret"] = secret
        groups[new_group_id] = group_data
        save_json(GROUPS_FILE, groups)
        context.job_queue.scheduler.remove_job(f"send_message_{old_group_id}")
        schedule_task(context, new_group_id, INTERVALS.get(group_data["interval"], 600), context.job_queue.scheduler)
        await update.message.edit_text(f"تم تعديل المجموعة إلى {new_group_id} بنجاح.")
    else:
        await update.message.edit_text("المجموعة غير موجودة.")
    return ConversationHandler.END

async def add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        attempts = int(update.message.text.strip())
        if attempts < 0:
            raise ValueError
        group_id = context.user_data.get("attempts_group_id")
        user_id = context.user_data.get("attempts_user_id")
        users = load_json(USERS_FILE)
        if group_id in users and user_id in users[group_id]:
            users[group_id][user_id]["attempts"] += attempts
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"تم إضافة {attempts} محاولات للمستخدم {user_id}.")
        else:
            await update.message.reply_text("المستخدم أو المجموعة غير موجود.")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("أدخل رقمًا صحيحًا.")
        return ADD_ATTEMPTS

async def delete_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        attempts = int(update.message.text.strip())
        if attempts < 0:
            raise ValueError
        group_id = context.user_data.get("attempts_group_id")
        user_id = context.user_data.get("attempts_user_id")
        users = load_json(USERS_FILE)
        if group_id in users and user_id in users[group_id]:
            users[group_id][user_id]["attempts"] = max(0, users[group_id][user_id]["attempts"] - attempts)
            save_json(USERS_FILE, users)
            await update.message.reply_text(f"تم حذف {attempts} محاولات من المستخدم {user_id}.")
        else:
            await update.message.reply_text("المستخدم أو المجموعة غير موجود.")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("أدخل رقمًا صحيحًا.")
        return DELETE_ATTEMPTS

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.message.text.strip()
    if not admin_id.isdigit():
        await update.message.reply_text("معرف المسؤول يجب أن يكون رقمًا.")
        return ADD_ADMIN
    config = load_json(CONFIG_FILE)
    admins = config.get("admin_ids", ADMIN_IDS)
    if admin_id in admins:
        await update.message.reply_text("المسؤول موجود بالفعل.")
        return ConversationHandler.END
    admins.append(admin_id)
    config["admin_ids"] = admins
    save_json(CONFIG_FILE, config)
    await update.message.reply_text(f"تم إضافة المسؤول {admin_id} بنجاح.")
    return ConversationHandler.END

# إلغاء المحادثة
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

async def main():
    # تهيئة البوت
    application = Application.builder().token(TOKEN).build()
    scheduler = AsyncIOScheduler()
    config, groups, users = initialize_data()

    # تهيئة المهام المجدولة
    for group_id, group in groups.items():
        if group.get("active", True):
            interval = INTERVALS.get(group.get("interval", "10m"), 600)
            schedule_task(application, group_id, interval, scheduler)

    # إعداد معالجات المحادثة
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^(manage_groups|add_group|modify_group|delete_group|manage_interval|set_interval_|interval_|stop_interval_|start_interval_|manage_format|set_format_|format_|timezone_|tz_|manage_attempts|attempts_group_|attempts_user_|ban_user_|add_attempts_|del_attempts_|manage_admins|add_admin|delete_admin|del_admin_)$"),
            CommandHandler("admin", admin_command)
        ],
        states={
            ADD_GROUP_ID: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_id)],
            ADD_GROUP_SECRET: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_secret)],
            MODIFY_GROUP_ID: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, modify_group_id)],
            MODIFY_GROUP_SECRET: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, modify_group_secret)],
            ADD_ATTEMPTS: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, add_attempts)],
            DELETE_ATTEMPTS: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, delete_attempts)],
            ADD_ADMIN: [CommandHandler("cancel", cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=True  # إصلاح تحذير PTBUserWarning
    )

    # إضافة معالجات
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_copy_code, pattern="^copy_code_"))

    # بدء المجدول
    scheduler.start()

    # تشغيل البوت
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # الإبقاء على الحلقة مفتوحة
    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

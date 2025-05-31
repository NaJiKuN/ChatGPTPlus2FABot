# -*- coding: utf-8 -*-
"""
ChatGPTPlus2FABot

بوت تليجرام لإدارة ومشاركة رموز المصادقة الثنائية (2FA) المستندة إلى TOTP.

ملاحظة هامة: بسبب القيود التقنية الحالية، لا يمكن لهذا البوت إرسال
الرسائل بشكل دوري وتلقائي إلى المجموعات. يتم إرسال الرمز فقط عند
طلب المستخدم عبر الضغط على زر "Copy Code". المعلومات المتعلقة بـ "الوقت التالي"
في الرسائل هي للعرض فقط ولا تعكس إرسالاً تلقائياً مجدولاً.
"""

import logging
import json
import os
import pyotp
import pytz
import base64
import binascii # Needed for TOTP error handling
from datetime import datetime, date, time, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, MessageHandler,
     CallbackContext, ConversationHandler, PicklePersistence
)
from telegram.ext.filters import Filters
from unittest.mock import MagicMock # Import MagicMock for dummy updates

# --- إعدادات أساسية --- #
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM" # استبدل بالتوكن الخاص بك
ADMIN_ID = 764559466 # استبدل بمعرف المستخدم المسؤول الأولي

# --- مسارات الملفات --- #
DATA_DIR = "/home/ubuntu/projects/ChatGPTPlus2FABot/data"
ADMINS_FILE = os.path.join(DATA_DIR, "admins.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
ATTEMPTS_FILE = os.path.join(DATA_DIR, "attempts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PERSISTENCE_FILE = os.path.join(DATA_DIR, "bot_persistence.pickle")

# --- إعداد تسجيل الدخول --- #
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- حالات المحادثة --- #
# إدارة المجموعات
(SELECTING_GROUP_ACTION, ASKING_GROUP_ID, ASKING_TOTP_SECRET,
 SELECTING_GROUP_TO_EDIT, SELECTING_EDIT_ACTION, ASKING_NEW_TOTP,
 CONFIRMING_DELETE) = range(7)
# إدارة المحاولات
(SELECTING_ATTEMPTS_ACTION, SELECTING_USER_FOR_ATTEMPTS,
 ASKING_ATTEMPTS_NUMBER_ADD, ASKING_ATTEMPTS_NUMBER_REMOVE) = range(7, 11)
# إدارة الفاصل الزمني (للعرض)
(SELECTING_GROUP_FOR_INTERVAL, SELECTING_INTERVAL_ACTION) = range(11, 13)
# إدارة التنسيق/الوقت
(SELECTING_GROUP_FOR_FORMAT, SELECTING_FORMAT_ACTION) = range(13, 15)
# إدارة المسؤولين
(SELECTING_ADMIN_ACTION, ASKING_ADMIN_ID_TO_ADD, ASKING_ADMIN_ID_TO_REMOVE) = range(15, 18)

# حالة العودة للقائمة الرئيسية للإدارة
ADMIN_MAIN_MENU = ConversationHandler.END

# --- خيارات الإعدادات --- #
AVAILABLE_INTERVALS = {
    "1 دقيقة": 60,
    "5 دقائق": 300,
    "10 دقائق": 600,
    "30 دقيقة": 1800,
    "1 ساعة": 3600,
    "6 ساعات": 21600,
    "12 ساعة": 43200,
    "24 ساعة": 86400
}
AVAILABLE_TIME_FORMATS = {"12 ساعة": "12", "24 ساعة": "24"}
AVAILABLE_TIMEZONES = {"Asia/Gaza": "Asia/Gaza", "UTC": "UTC"}
# يمكن إضافة المزيد من المناطق الزمنية إذا لزم الأمر

# --- دوال تحميل وحفظ البيانات --- #
def load_json(file_path, default_data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        save_json(file_path, default_data)
        return default_data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            if not content:
                save_json(file_path, default_data)
                return default_data
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"خطأ في قراءة أو تحليل الملف {file_path}: {e}. سيتم استخدام البيانات الافتراضية.")
        save_json(file_path, default_data)
        return default_data

def save_json(file_path, data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        logger.error(f"خطأ في كتابة الملف {file_path}: {e}")

# تحميل البيانات عند بدء التشغيل
admins = load_json(ADMINS_FILE, [ADMIN_ID])
groups_data = load_json(GROUPS_FILE, {}) # {group_id_str: { "totp_secret": "...", "message_id": null, "settings": {...} }}
user_attempts = load_json(ATTEMPTS_FILE, {}) # {user_id_str: { "attempts_left": N, "last_reset": "YYYY-MM-DD", "banned": false, "first_name": "..." }}
global_settings = load_json(SETTINGS_FILE, {
    "default_attempts": 5,
    "notify_admin_on_copy": False,
    "default_interval": 600, # 10 minutes in seconds
    "default_message_format": 1, # حالياً لا يوجد تنسيقات متعددة، لكن نتركه للمستقبل
    "default_time_format": "12",
    "default_timezone": "Asia/Gaza"
})

# --- دوال مساعدة --- #
def is_admin(user_id):
    return user_id in admins

def get_current_time(timezone_str="Asia/Gaza"):
    try:
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"المنطقة الزمنية غير معروفة: {timezone_str}. استخدام UTC كبديل.")
        return datetime.now(pytz.utc)

def format_time(dt_object, hour_format="12"):
    if hour_format == "12":
        return dt_object.strftime("%I:%M:%S %p")
    else:
        return dt_object.strftime("%H:%M:%S")

def generate_totp(secret):
    if not secret:
        return None, "Secret not configured"
    try:
        secret = secret.strip().upper()
        padding = len(secret) % 8
        if padding != 0:
            secret += "=" * (8 - padding)
        totp = pyotp.TOTP(secret)
        return totp.now(), None
    except (binascii.Error, Exception) as e:
        error_msg = f"خطأ في توليد TOTP: {e}"
        logger.error(error_msg)
        return None, error_msg

def is_valid_totp_secret(secret):
    if not secret or not isinstance(secret, str):
        return False
    try:
        secret = secret.strip().upper()
        padding = len(secret) % 8
        if padding != 0:
            secret += "=" * (8 - padding)
        base64.b32decode(secret, casefold=True)
        pyotp.TOTP(secret).now()
        return True
    except Exception:
        return False

def is_valid_group_id(group_id_str):
    if not group_id_str or not isinstance(group_id_str, str):
        return False
    if not group_id_str.startswith("-"):
        return False
    try:
        int(group_id_str) # Check if the rest is numeric after removing the first char
        return True
    except ValueError:
        return False

def get_user_attempts_data(user_id, user_first_name=None):
    user_id_str = str(user_id)
    today_str = date.today().isoformat()
    default_attempts = global_settings.get("default_attempts", 5)

    if user_id_str not in user_attempts:
        user_attempts[user_id_str] = {
            "attempts_left": default_attempts,
            "last_reset": today_str,
            "banned": False,
            "first_name": user_first_name or f"User_{user_id_str}"
        }
        save_json(ATTEMPTS_FILE, user_attempts)
        return user_attempts[user_id_str]

    user_data = user_attempts[user_id_str]

    if user_first_name and user_data.get("first_name", "").startswith("User_"):
        user_data["first_name"] = user_first_name
        # No need to save immediately, will be saved on reset or modification

    if user_data.get("last_reset") != today_str:
        logger.info(f"Resetting attempts for user {user_id_str} ({user_data.get('first_name')}) for new day {today_str}")
        user_data["attempts_left"] = default_attempts
        user_data["last_reset"] = today_str
        save_json(ATTEMPTS_FILE, user_attempts)

    return user_data

def get_group_title(context: CallbackContext, group_id_str: str) -> str:
    """Helper to get group title, falling back to ID."""
    try:
        chat = context.bot.get_chat(chat_id=group_id_str)
        return chat.title if chat.title else group_id_str
    except Exception as e:
        logger.warning(f"Could not get title for group {group_id_str}: {e}")
        return group_id_str

# --- دالة إرسال/تحديث رسالة المجموعة --- #
def send_or_update_group_message(context: CallbackContext, group_id_str: str):
    """Sends or edits the main message in the group with the Copy Code button."""
    if group_id_str not in groups_data:
        logger.warning(f"Attempted to send message to non-existent group {group_id_str}")
        return

    group_info = groups_data[group_id_str]
    settings = group_info.get("settings", {})
    is_enabled = settings.get("enabled", False)
    interval_seconds = settings.get("interval", global_settings["default_interval"])
    time_format = settings.get("time_format", global_settings["default_time_format"])
    timezone_str = settings.get("timezone", global_settings["default_timezone"])
    message_id = group_info.get("message_id")

    if not is_enabled:
        # If disabled, try to delete the existing message
        if message_id:
            try:
                context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
                logger.info(f"Deleted message {message_id} in group {group_id_str} as it was disabled.")
                groups_data[group_id_str]["message_id"] = None
                save_json(GROUPS_FILE, groups_data)
            except Exception as e:
                logger.error(f"Failed to delete message {message_id} in group {group_id_str}: {e}")
        return # Do not send a new message if disabled

    # Construct the message text
    now = get_current_time(timezone_str)
    next_update_time = now + timedelta(seconds=interval_seconds)
    time_str = format_time(next_update_time, time_format)
    interval_desc = next((k for k, v in AVAILABLE_INTERVALS.items() if v == interval_seconds), f"{interval_seconds} ثانية")

    # Escape MarkdownV2 characters
    def escape_md(text):
        escape_chars = "\\_\\*\\[\\]\\(\\)\\~\\`\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"
        return "".join(["\\" + char if char in escape_chars else char for char in text])

    # Message Format (Currently only one format)
    message_text = (
        f"🔑 *{escape_md('ChatGPTPlus2FABot')}* 🔑\n\n"
        f"{escape_md('اضغط على الزر أدناه للحصول على رمز المصادقة الثنائية (2FA) الخاص بك.')}\n\n"
        f"⏳ *{escape_md('التحديث المتوقع التالي:')}* {escape_md(time_str)} \({escape_md(timezone_str)}\)\n"
        f"🔄 *{escape_md('الفاصل الزمني:')}* {escape_md(interval_desc)}\n\n"
        f"_{escape_md('(ملاحظة: الرمز يُرسل في رسالة خاصة عند الضغط على الزر)')}_"
    )

    keyboard = [[InlineKeyboardButton("📲 نسخ الرمز (Copy Code)", callback_data=f"copy_code_{group_id_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if message_id:
            # Try editing the existing message
            context.bot.edit_message_text(
                chat_id=group_id_str,
                message_id=message_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"Updated message {message_id} in group {group_id_str}")
        else:
            # Send a new message
            sent_message = context.bot.send_message(
                chat_id=group_id_str,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            groups_data[group_id_str]["message_id"] = sent_message.message_id
            save_json(GROUPS_FILE, groups_data)
            logger.info(f"Sent new message {sent_message.message_id} to group {group_id_str}")

    except BadRequest as e:
        if "message is not modified" in str(e):
            logger.debug(f"Message {message_id} in group {group_id_str} was not modified.")
        elif "message to edit not found" in str(e) or "message to delete not found" in str(e):
            logger.warning(f"Message {message_id} not found in group {group_id_str}. Sending a new one.")
            groups_data[group_id_str]["message_id"] = None # Clear invalid message ID
            save_json(GROUPS_FILE, groups_data)
            send_or_update_group_message(context, group_id_str) # Retry sending
        elif "Can't parse entities" in str(e):
             logger.error(f"Markdown parsing error for group {group_id_str}: {e}. Check message format and escaping.")
             # Consider sending plain text as fallback?
        else:
            logger.error(f"Error sending/editing message in group {group_id_str}: {e}")
            # Could potentially disable the group or clear message_id if persistent errors occur
    except TelegramError as e:
        logger.error(f"Telegram error sending/editing message in group {group_id_str}: {e}")
        # Handle specific errors like bot blocked, chat not found etc.
        if "bot was kicked" in str(e) or "chat not found" in str(e):
             logger.warning(f"Bot seems to be removed from group {group_id_str}. Disabling it.")
             if group_id_str in groups_data:
                 groups_data[group_id_str]["settings"]["enabled"] = False
                 groups_data[group_id_str]["message_id"] = None
                 save_json(GROUPS_FILE, groups_data)

# --- معالجات الأوامر الأساسية --- #
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    get_user_attempts_data(user.id, user.first_name)
    update.message.reply_html(
        f"أهلاً بك يا {user.mention_html()} في بوت ChatGPTPlus2FABot!\n"
        f"إذا كنت مسؤولاً، يمكنك استخدام الأمر /admin لإدارة البوت."
    )

def admin_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("عذراً، هذا الأمر مخصص للمسؤولين فقط.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🔐 إدارة المجموعات/الأسرار", callback_data="grp_manage")],
        [InlineKeyboardButton("🔄 إدارة فترة التكرار/التفعيل", callback_data="interval_manage")],
        [InlineKeyboardButton("🎨 إدارة شكل/توقيت الرسالة", callback_data="format_manage")],
        [InlineKeyboardButton("👥 إدارة محاولات المستخدمين", callback_data="attempts_manage")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admins_manage")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg_text = "لوحة تحكم المسؤول:\n(ملاحظة: الإرسال الدوري التلقائي غير مفعل حالياً)"
    if update.callback_query:
        query = update.callback_query
        query.answer()
        try:
            query.edit_message_text(msg_text, reply_markup=reply_markup)
        except Exception as e:
             logger.warning(f"Failed to edit admin menu message: {e}")
             try:
                 context.bot.send_message(chat_id=query.message.chat_id, text=msg_text, reply_markup=reply_markup)
             except Exception as send_e:
                 logger.error(f"Failed to send admin menu message after edit failure: {send_e}")
    else:
        update.message.reply_text(msg_text, reply_markup=reply_markup)

    return ADMIN_MAIN_MENU

# --- إدارة المجموعات والأسرار (ConversationHandler) --- #
def manage_groups_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="grp_add")],
    ]
    if groups_data:
        keyboard.append([InlineKeyboardButton("✏️ تعديل/حذف مجموعة", callback_data="grp_edit_select")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="إدارة المجموعات والأسرار:", reply_markup=reply_markup)
    return SELECTING_GROUP_ACTION

def ask_group_id(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="يرجى إرسال معرف المجموعة (Group ID) الذي يبدأ بـ '-' (مثال: -100123456789).")
    return ASKING_GROUP_ID

def receive_group_id(update: Update, context: CallbackContext) -> int:
    group_id_str = update.message.text.strip()
    if not is_valid_group_id(group_id_str):
        update.message.reply_text("المعرف غير صالح. يجب أن يبدأ بـ '-' ويحتوي على أرقام فقط. يرجى المحاولة مرة أخرى.")
        return ASKING_GROUP_ID
    if group_id_str in groups_data:
        update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة التعديل.")
        # Simulate callback to go back to menu
        dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
        dummy_update = Update(update.update_id, callback_query=dummy_query)
        return manage_groups_entry(dummy_update, context)
    context.user_data["current_group_id"] = group_id_str
    update.message.reply_text("تم استلام معرف المجموعة. الآن يرجى إرسال مفتاح TOTP السري (TOTP Secret) لهذه المجموعة.")
    return ASKING_TOTP_SECRET

def receive_totp_secret(update: Update, context: CallbackContext) -> int:
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("current_group_id")
    if not group_id_str:
        update.message.reply_text("خطأ. يرجى البدء من جديد.")
        admin_command(update, context)
        return ConversationHandler.END
    if not is_valid_totp_secret(totp_secret):
        update.message.reply_text("المفتاح السري غير صالح (يجب أن يكون بتنسيق Base32). يرجى المحاولة مرة أخرى.")
        return ASKING_TOTP_SECRET
    groups_data[group_id_str] = {
        "totp_secret": totp_secret,
        "message_id": None,
        "settings": {
            "interval": global_settings.get("default_interval", 600),
            "message_format": global_settings.get("default_message_format", 1),
            "time_format": global_settings.get("default_time_format", "12"),
            "timezone": global_settings.get("default_timezone", "Asia/Gaza"),
            "enabled": True
        }
    }
    save_json(GROUPS_FILE, groups_data)
    context.user_data.pop("current_group_id", None)
    update.message.reply_text(f"✅ تم إضافة المجموعة {group_id_str} بنجاح! سيتم إرسال رسالة الزر للمجموعة الآن.")
    # Send the initial message to the group
    send_or_update_group_message(context, group_id_str)
    # Simulate callback to go back to menu
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    return manage_groups_entry(dummy_update, context)

def select_group_to_edit(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = []
    if not groups_data:
        query.edit_message_text("لا توجد مجموعات مضافة.")
        return manage_groups_entry(update, context)
    for group_id in groups_data:
        title = get_group_title(context, group_id)
        keyboard.append([InlineKeyboardButton(f"{title} ({group_id})", callback_data=f"grp_select_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="grp_back_to_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر المجموعة للتعديل أو الحذف:", reply_markup=reply_markup)
    return SELECTING_GROUP_TO_EDIT

def select_edit_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["selected_group_id"] = group_id_str
    if group_id_str not in groups_data:
         query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
         return select_group_to_edit(update, context)
    title = get_group_title(context, group_id_str)
    keyboard = [
        [InlineKeyboardButton("🔑 تعديل المفتاح السري (TOTP)", callback_data=f"grp_edit_secret_{group_id_str}")],
        [InlineKeyboardButton("🗑️ حذف المجموعة", callback_data=f"grp_delete_confirm_{group_id_str}")],
        [InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="grp_edit_select")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"إدارة المجموعة: {title} ({group_id_str})", reply_markup=reply_markup)
    return SELECTING_EDIT_ACTION

def ask_new_totp(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم تحديد مجموعة صالحة.")
        return select_group_to_edit(update, context)
    title = get_group_title(context, group_id_str)
    query.edit_message_text(f"يرجى إرسال مفتاح TOTP السري الجديد للمجموعة {title} ({group_id_str}).")
    return ASKING_NEW_TOTP

def receive_new_totp(update: Update, context: CallbackContext) -> int:
    new_totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("selected_group_id")
    if not group_id_str or group_id_str not in groups_data:
        update.message.reply_text("حدث خطأ ما. يرجى البدء من جديد.")
        admin_command(update, context)
        return ConversationHandler.END
    if not is_valid_totp_secret(new_totp_secret):
        update.message.reply_text("المفتاح السري الجديد غير صالح. حاول مرة أخرى.")
        return ASKING_NEW_TOTP
    groups_data[group_id_str]["totp_secret"] = new_totp_secret
    save_json(GROUPS_FILE, groups_data)
    context.user_data.pop("selected_group_id", None)
    update.message.reply_text(f"✅ تم تحديث المفتاح السري للمجموعة {group_id_str} بنجاح!")
    # Simulate callback to go back to menu
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    return manage_groups_entry(dummy_update, context)

def confirm_delete_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["group_to_delete"] = group_id_str
    if group_id_str not in groups_data:
         query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
         return select_group_to_edit(update, context)
    title = get_group_title(context, group_id_str)
    keyboard = [
        [InlineKeyboardButton("✅ نعم، حذف", callback_data=f"grp_delete_yes_{group_id_str}")],
        [InlineKeyboardButton("❌ لا، إلغاء", callback_data=f"grp_delete_no_{group_id_str}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"⚠️ هل أنت متأكد من حذف المجموعة {title} ({group_id_str})؟", reply_markup=reply_markup)
    return CONFIRMING_DELETE

def execute_delete_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("group_to_delete")
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        context.user_data.pop("group_to_delete", None)
        return select_group_to_edit(update, context)

    # Try to delete the message in the group first
    message_id = groups_data[group_id_str].get("message_id")
    if message_id:
        try:
            context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
            logger.info(f"Deleted message {message_id} from group {group_id_str} before deleting group data.")
        except Exception as e:
            logger.warning(f"Could not delete message {message_id} from group {group_id_str} during group deletion: {e}")

    del groups_data[group_id_str]
    save_json(GROUPS_FILE, groups_data)
    context.user_data.pop("group_to_delete", None)
    query.edit_message_text(f"🗑️ تم حذف المجموعة {group_id_str}.")
    return manage_groups_entry(update, context)

def cancel_delete_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    context.user_data.pop("group_to_delete", None)
    group_id_str = context.user_data.get("selected_group_id")
    if not group_id_str or group_id_str not in groups_data:
         query.edit_message_text("تم إلغاء الحذف.")
         return select_group_to_edit(update, context)
    # Reconstruct callback data to go back to edit action selection
    query.data = f"grp_select_{group_id_str}"
    return select_edit_action(update, context)

def back_to_group_manage_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    context.user_data.pop("selected_group_id", None)
    context.user_data.pop("group_to_delete", None)
    return manage_groups_entry(update, context)

def back_to_admin_main_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    context.user_data.clear()
    admin_update = Update(update.update_id, callback_query=query)
    return admin_command(admin_update, context)

def cancel_conversation(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    msg_text = "تم إلغاء العملية."
    if update.callback_query:
        query = update.callback_query
        query.answer()
        try:
            query.edit_message_text(msg_text)
        except Exception as e:
            logger.warning(f"Failed to edit message on cancel: {e}")
            # Send new message if edit fails
            try:
                context.bot.send_message(chat_id=query.message.chat_id, text=msg_text)
            except Exception as send_e:
                 logger.error(f"Failed to send cancel message after edit failure: {send_e}")
        # Go back to admin menu after cancelling
        admin_update = Update(update.update_id, callback_query=query)
        return admin_command(admin_update, context)
    elif update.message:
        update.message.reply_text(msg_text)
        admin_update = Update(update.update_id, message=update.message)
        return admin_command(admin_update, context)
    return ConversationHandler.END # Fallback

# --- إدارة محاولات المستخدمين (ConversationHandler) --- #
def manage_attempts_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if not user_attempts:
        query.edit_message_text(
            text="لا يوجد مستخدمون مسجلون في نظام المحاولات بعد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")]])
        )
        return ADMIN_MAIN_MENU
    keyboard = []
    for user_id_str, data in user_attempts.items():
        name = data.get("first_name", f"User_{user_id_str}")
        attempts = data.get("attempts_left", "N/A")
        status = "🚫" if data.get("banned", False) else "✅"
        button_text = f"{status} {name} ({user_id_str}) - محاولات: {attempts}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"att_select_user_{user_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text="إدارة محاولات المستخدمين: اختر مستخدماً", reply_markup=reply_markup)
    return SELECTING_USER_FOR_ATTEMPTS

def select_attempt_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = query.data.split("_")[-1]
    context.user_data["selected_user_id"] = user_id_str
    if user_id_str not in user_attempts:
        query.edit_message_text("خطأ: المستخدم لم يعد موجوداً.")
        return manage_attempts_entry(update, context)
    user_data = user_attempts[user_id_str]
    name = user_data.get("first_name", f"User_{user_id_str}")
    attempts = user_data.get("attempts_left", "N/A")
    is_banned = user_data.get("banned", False)
    ban_button_text = "🔓 إلغاء حظر المستخدم" if is_banned else "🚫 حظر المستخدم"
    ban_callback = f"att_unban_{user_id_str}" if is_banned else f"att_ban_{user_id_str}"
    keyboard = [
        [InlineKeyboardButton(ban_button_text, callback_data=ban_callback)],
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data=f"att_add_{user_id_str}")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data=f"att_remove_{user_id_str}")],
        [InlineKeyboardButton("🔙 العودة لاختيار مستخدم", callback_data="attempts_manage")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"إدارة المستخدم: {name} ({user_id_str})\nمحاولات متبقية: {attempts}", reply_markup=reply_markup)
    return SELECTING_ATTEMPTS_ACTION

def toggle_ban_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = context.user_data.get("selected_user_id")
    action = query.data.split("_")[1] # ban or unban
    if not user_id_str or user_id_str not in user_attempts:
        query.edit_message_text("خطأ: لم يتم العثور على المستخدم.")
        return manage_attempts_entry(update, context)
    should_ban = (action == "ban")
    user_attempts[user_id_str]["banned"] = should_ban
    save_json(ATTEMPTS_FILE, user_attempts)
    status_message = "محظور" if should_ban else "غير محظور"
    query.edit_message_text(f"✅ تم تحديث حالة المستخدم {user_id_str}. الحالة الآن: {status_message}")
    query.data = f"att_select_user_{user_id_str}"
    return select_attempt_action(update, context)

def ask_attempts_number(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = context.user_data.get("selected_user_id")
    action = query.data.split("_")[1] # add or remove
    context.user_data["attempt_action"] = action
    if not user_id_str or user_id_str not in user_attempts:
        query.edit_message_text("خطأ: لم يتم العثور على المستخدم.")
        return manage_attempts_entry(update, context)
    prompt = "إضافة" if action == "add" else "حذف"
    query.edit_message_text(f"كم عدد المحاولات التي تريد {prompt}ها للمستخدم {user_id_str}؟ يرجى إرسال رقم.")
    return ASKING_ATTEMPTS_NUMBER_ADD if action == "add" else ASKING_ATTEMPTS_NUMBER_REMOVE

def receive_attempts_number(update: Update, context: CallbackContext) -> int:
    try:
        num_attempts = int(update.message.text.strip())
        if num_attempts <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        update.message.reply_text("الرجاء إدخال رقم صحيح موجب.")
        action = context.user_data.get("attempt_action")
        return ASKING_ATTEMPTS_NUMBER_ADD if action == "add" else ASKING_ATTEMPTS_NUMBER_REMOVE
    user_id_str = context.user_data.get("selected_user_id")
    action = context.user_data.get("attempt_action")
    if not user_id_str or user_id_str not in user_attempts or not action:
        update.message.reply_text("حدث خطأ ما. يرجى البدء من جديد.")
        context.user_data.clear()
        admin_command(update, context)
        return ConversationHandler.END
    current_attempts = user_attempts[user_id_str].get("attempts_left", 0)
    if action == "add":
        user_attempts[user_id_str]["attempts_left"] = current_attempts + num_attempts
        result_verb = "إضافة"
    elif action == "remove":
        user_attempts[user_id_str]["attempts_left"] = max(0, current_attempts - num_attempts)
        result_verb = "حذف"
    else:
         update.message.reply_text("حدث خطأ غير متوقع في تحديد الإجراء.")
         context.user_data.clear()
         admin_command(update, context)
         return ConversationHandler.END
    save_json(ATTEMPTS_FILE, user_attempts)
    new_attempts = user_attempts[user_id_str]["attempts_left"]
    update.message.reply_text(f"✅ تم {result_verb} {num_attempts} محاولة للمستخدم {user_id_str}. الرصيد الحالي: {new_attempts}")
    context.user_data.pop("attempt_action", None)
    # Simulate callback to go back
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.from_user = update.effective_user; dummy_query.data = f"att_select_user_{user_id_str}"; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    return select_attempt_action(dummy_update, context)

# --- إدارة الفاصل الزمني (للعرض) والتفعيل (ConversationHandler) --- #
def manage_interval_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = []
    if not groups_data:
        query.edit_message_text(
            "لا توجد مجموعات مضافة لإدارة إعداداتها.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")]])
        )
        return ADMIN_MAIN_MENU
    for group_id in groups_data:
        title = get_group_title(context, group_id)
        keyboard.append([InlineKeyboardButton(f"{title} ({group_id})", callback_data=f"interval_select_grp_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("إدارة الفاصل الزمني/التفعيل: اختر مجموعة", reply_markup=reply_markup)
    return SELECTING_GROUP_FOR_INTERVAL

def select_interval_options(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["selected_group_id"] = group_id_str
    if group_id_str not in groups_data:
        query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
        return manage_interval_entry(update, context)
    settings = groups_data[group_id_str].get("settings", {})
    current_interval = settings.get("interval", global_settings["default_interval"])
    is_enabled = settings.get("enabled", True)
    title = get_group_title(context, group_id_str)
    keyboard = []
    interval_buttons = []
    for name, seconds in AVAILABLE_INTERVALS.items():
        prefix = "✅ " if seconds == current_interval else ""
        interval_buttons.append(InlineKeyboardButton(f"{prefix}{name}", callback_data=f"interval_set_{seconds}"))
    for i in range(0, len(interval_buttons), 2):
        keyboard.append(interval_buttons[i:i+2])
    enable_text = "🟢 تفعيل النسخ" if not is_enabled else "🔴 تعطيل النسخ"
    enable_callback = f"interval_enable_{group_id_str}" if not is_enabled else f"interval_disable_{group_id_str}"
    keyboard.append([InlineKeyboardButton(enable_text, callback_data=enable_callback)])
    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="interval_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    current_interval_desc = next((k for k, v in AVAILABLE_INTERVALS.items() if v == current_interval), f"{current_interval} ثانية")
    status_desc = "مفعل" if is_enabled else "معطل"
    query.edit_message_text(
        f"إعدادات المجموعة: {title} ({group_id_str})\n"
        f"الحالة الحالية: {status_desc}\n"
        f"الفاصل الزمني (للعرض): {current_interval_desc}\n\n"
        f"اختر الفاصل الزمني الجديد أو قم بتغيير حالة التفعيل:",
        reply_markup=reply_markup
    )
    return SELECTING_INTERVAL_ACTION

def set_interval(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    try:
        new_interval = int(query.data.split("_")[-1])
    except (IndexError, ValueError):
        query.edit_message_text("خطأ في بيانات الفاصل الزمني.")
        return manage_interval_entry(update, context)
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        return manage_interval_entry(update, context)
    groups_data[group_id_str]["settings"]["interval"] = new_interval
    save_json(GROUPS_FILE, groups_data)
    query.edit_message_text(f"✅ تم تحديث الفاصل الزمني للمجموعة {group_id_str}.")
    send_or_update_group_message(context, group_id_str)
    query.data = f"interval_select_grp_{group_id_str}"
    return select_interval_options(update, context)

def toggle_enable_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    action = query.data.split("_")[1] # enable or disable
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        return manage_interval_entry(update, context)
    should_enable = (action == "enable")
    groups_data[group_id_str]["settings"]["enabled"] = should_enable
    save_json(GROUPS_FILE, groups_data)
    status_message = "تفعيل" if should_enable else "تعطيل"
    query.edit_message_text(f"✅ تم {status_message} النسخ للمجموعة {group_id_str}.")
    send_or_update_group_message(context, group_id_str)
    query.data = f"interval_select_grp_{group_id_str}"
    return select_interval_options(update, context)

# --- إدارة التنسيق/الوقت (ConversationHandler) --- #
def manage_format_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = []
    if not groups_data:
        query.edit_message_text(
            "لا توجد مجموعات مضافة لإدارة إعداداتها.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")]])
        )
        return ADMIN_MAIN_MENU
    for group_id in groups_data:
        title = get_group_title(context, group_id)
        keyboard.append([InlineKeyboardButton(f"{title} ({group_id})", callback_data=f"format_select_grp_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("إدارة شكل/توقيت الرسالة: اختر مجموعة", reply_markup=reply_markup)
    return SELECTING_GROUP_FOR_FORMAT

def select_format_options(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["selected_group_id"] = group_id_str
    if group_id_str not in groups_data:
        query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
        return manage_format_entry(update, context)
    settings = groups_data[group_id_str].get("settings", {})
    current_time_format = settings.get("time_format", global_settings["default_time_format"])
    current_timezone = settings.get("timezone", global_settings["default_timezone"])
    title = get_group_title(context, group_id_str)
    keyboard = []
    tf_buttons = []
    for name, value in AVAILABLE_TIME_FORMATS.items():
        prefix = "✅ " if value == current_time_format else ""
        tf_buttons.append(InlineKeyboardButton(f"{prefix}{name}", callback_data=f"format_set_tf_{value}"))
    keyboard.append(tf_buttons)
    tz_buttons = []
    for name, value in AVAILABLE_TIMEZONES.items():
        prefix = "✅ " if value == current_timezone else ""
        # Use a simple replacement for '/' to avoid issues in callback data
        tz_callback_value = value.replace("/", "-")
        tz_buttons.append(InlineKeyboardButton(f"{prefix}{name}", callback_data=f"format_set_tz_{tz_callback_value}"))
    keyboard.append(tz_buttons)
    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="format_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        f"إعدادات المجموعة: {title} ({group_id_str})\n"
        f"تنسيق الوقت الحالي: {current_time_format} ساعة\n"
        f"المنطقة الزمنية الحالية: {current_timezone}\n\n"
        f"اختر الإعدادات الجديدة:",
        reply_markup=reply_markup
    )
    return SELECTING_FORMAT_ACTION

def set_time_format(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    try:
        new_format = query.data.split("_")[-1]
        if new_format not in ["12", "24"]:
             raise ValueError("Invalid time format")
    except (IndexError, ValueError):
        query.edit_message_text("خطأ في بيانات تنسيق الوقت.")
        return manage_format_entry(update, context)
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        return manage_format_entry(update, context)
    groups_data[group_id_str]["settings"]["time_format"] = new_format
    save_json(GROUPS_FILE, groups_data)
    query.edit_message_text(f"✅ تم تحديث تنسيق الوقت للمجموعة {group_id_str}.")
    send_or_update_group_message(context, group_id_str)
    query.data = f"format_select_grp_{group_id_str}"
    return select_format_options(update, context)

def set_timezone(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    try:
        # Reconstruct timezone from callback data (replace '-' back with '/')
        tz_callback_value = "_".join(query.data.split("_")[3:])
        new_timezone = tz_callback_value.replace("-", "/")
        if new_timezone not in AVAILABLE_TIMEZONES:
            raise ValueError(f"Invalid timezone reconstructed: {new_timezone}")
    except (IndexError, ValueError) as e:
        logger.error(f"Timezone reconstruction error: {e}, Data: {query.data}")
        query.edit_message_text("خطأ في بيانات المنطقة الزمنية.")
        return manage_format_entry(update, context)
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        return manage_format_entry(update, context)
    groups_data[group_id_str]["settings"]["timezone"] = new_timezone
    save_json(GROUPS_FILE, groups_data)
    query.edit_message_text(f"✅ تم تحديث المنطقة الزمنية للمجموعة {group_id_str}.")
    send_or_update_group_message(context, group_id_str)
    query.data = f"format_select_grp_{group_id_str}"
    return select_format_options(update, context)

# --- إدارة المسؤولين (ConversationHandler) --- #
def manage_admins_entry(update: Update, context: CallbackContext) -> int:
    """Entry point for managing admins."""
    query = update.callback_query
    query.answer()
    admin_list_str = "\n".join([f"- `{admin_id}`" for admin_id in admins])
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول", callback_data="admin_add")],
        [InlineKeyboardButton("➖ إزالة مسؤول", callback_data="admin_remove")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text=f"إدارة المسؤولين:\n\n*المسؤولون الحاليون:*\n{admin_list_str}\n\nاختر إجراءً:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    return SELECTING_ADMIN_ACTION

def ask_admin_id_to_add(update: Update, context: CallbackContext) -> int:
    """Asks for the User ID of the admin to add."""
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="يرجى إرسال معرف المستخدم (User ID) للمسؤول الجديد الذي تريد إضافته.")
    return ASKING_ADMIN_ID_TO_ADD

def receive_admin_id_to_add(update: Update, context: CallbackContext) -> int:
    """Receives, validates, and adds the new admin ID."""
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("معرف المستخدم يجب أن يكون رقماً. يرجى المحاولة مرة أخرى.")
        return ASKING_ADMIN_ID_TO_ADD

    if new_admin_id in admins:
        update.message.reply_text(f"المستخدم `{new_admin_id}` هو مسؤول بالفعل.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        admins.append(new_admin_id)
        save_json(ADMINS_FILE, admins)
        update.message.reply_text(f"✅ تم إضافة المستخدم `{new_admin_id}` كمسؤول جديد بنجاح!", parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Admin {update.effective_user.id} added new admin {new_admin_id}")

    # Simulate callback to go back to admin management menu
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    # Need to set the callback data correctly to trigger manage_admins_entry
    dummy_query.data = "admins_manage"
    return manage_admins_entry(dummy_update, context)

def ask_admin_id_to_remove(update: Update, context: CallbackContext) -> int:
    """Asks for the User ID of the admin to remove."""
    query = update.callback_query
    query.answer()
    if len(admins) <= 1:
        query.edit_message_text(
            text="لا يمكن إزالة المسؤول الوحيد المتبقي.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admins_manage")]])
        )
        return SELECTING_ADMIN_ACTION

    admin_buttons = []
    for admin_id in admins:
        # Avoid showing button to remove the primary admin (optional safeguard)
        # if admin_id == ADMIN_ID:
        #     continue
        admin_buttons.append([InlineKeyboardButton(f"➖ إزالة `{admin_id}`", callback_data=f"admin_remove_id_{admin_id}")])
    admin_buttons.append([InlineKeyboardButton("🔙 إلغاء", callback_data="admins_manage")])
    reply_markup = InlineKeyboardMarkup(admin_buttons)
    query.edit_message_text(text="اختر المسؤول الذي تريد إزالته:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return ASKING_ADMIN_ID_TO_REMOVE # Stay in this state to handle button press

def execute_remove_admin(update: Update, context: CallbackContext) -> int:
    """Removes the selected admin ID."""
    query = update.callback_query
    query.answer()
    try:
        admin_id_to_remove = int(query.data.split("_")[-1])
    except (IndexError, ValueError):
        query.edit_message_text("خطأ في بيانات المعرف.")
        return manage_admins_entry(update, context)

    if admin_id_to_remove not in admins:
        query.edit_message_text(f"المستخدم `{admin_id_to_remove}` ليس مسؤولاً.", parse_mode=ParseMode.MARKDOWN_V2)
    elif len(admins) <= 1:
         query.edit_message_text("لا يمكن إزالة المسؤول الوحيد المتبقي.")
    elif admin_id_to_remove == update.effective_user.id:
         query.edit_message_text("لا يمكنك إزالة نفسك كمسؤول.")
    else:
        admins.remove(admin_id_to_remove)
        save_json(ADMINS_FILE, admins)
        query.edit_message_text(f"🗑️ تم إزالة المسؤول `{admin_id_to_remove}` بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Admin {update.effective_user.id} removed admin {admin_id_to_remove}")

    # Go back to admin management menu
    query.data = "admins_manage"
    return manage_admins_entry(update, context)

# --- معالج زر نسخ الكود --- #
def copy_code_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user = query.from_user
    user_id_str = str(user.id)

    try:
        group_id_str = query.data.split("_")[-1]
    except (IndexError, ValueError):
        logger.error(f"Invalid callback data format for copy_code: {query.data}")
        query.answer("حدث خطأ في معالجة الطلب.", show_alert=True)
        return

    if group_id_str not in groups_data or not groups_data[group_id_str].get("settings", {}).get("enabled", False):
        query.answer("عذراً، خدمة الرمز غير مفعلة لهذه المجموعة حالياً.", show_alert=True)
        return

    group_info = groups_data[group_id_str]
    totp_secret = group_info.get("totp_secret")

    if not totp_secret:
        logger.warning(f"No TOTP secret configured for group {group_id_str}")
        query.answer("خطأ: لم يتم إعداد المفتاح السري لهذه المجموعة.", show_alert=True)
        return

    user_data = get_user_attempts_data(user.id, user.first_name)

    if user_data.get("banned", False):
        query.answer("عذراً، لقد تم حظرك من استخدام هذه الميزة.", show_alert=True)
        return

    attempts_left = user_data.get("attempts_left", 0)
    if attempts_left <= 0:
        query.answer(
            "لقد استنفدت محاولاتك لهذا اليوم. سيتم إعادة تعيينها غداً.",
            show_alert=True
        )
        try:
            context.bot.send_message(
                chat_id=user.id,
                text="⚠️ لقد استنفدت محاولاتك لنسخ الرمز لهذا اليوم. سيتم تحديث المحاولات تلقائياً عند أول استخدام لك غداً."
            )
        except Exception as e:
            logger.error(f"Failed to send 'out of attempts' notification to {user.id}: {e}")
        return

    code, error = generate_totp(totp_secret)

    if error:
        query.answer(f"حدث خطأ أثناء توليد الرمز: {error}. يرجى إبلاغ المسؤول.", show_alert=True)
        return

    user_data["attempts_left"] -= 1
    save_json(ATTEMPTS_FILE, user_attempts)
    remaining_attempts = user_data["attempts_left"]

    def escape_md(text):
        escape_chars = "\\_\\*\\[\\]\\(\\)\\~\\`\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"
        return "".join(["\\" + char if char in escape_chars else char for char in str(text)])

    message_text = (
        f"🔐 {escape_md('رمز المصادقة الثنائية الخاص بك:')}\n\n"
        f"`{code}`\n\n"
        f"⚠️ {escape_md('هذا الرمز صالح لمدة 30 ثانية فقط.')}\n"
        f"🔄 {escape_md('المحاولات المتبقية اليوم:')} {remaining_attempts}"
    )
    try:
        context.bot.send_message(
            chat_id=user.id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        query.answer("✅ تم إرسال الرمز إليك في رسالة خاصة.")
        logger.info(f"Sent 2FA code to user {user.id} ({user_data.get('first_name')}) for group {group_id_str}. Attempts left: {remaining_attempts}")

        if global_settings.get("notify_admin_on_copy", False):
            group_title_safe = escape_md(get_group_title(context, group_id_str))
            user_name_safe = escape_md(user_data.get('first_name'))
            admin_notification = f"🔔 المستخدم {user_name_safe} \({escape_md(user.id)}\) طلب رمزاً للمجموعة {group_title_safe}\. المحاولات المتبقية: {remaining_attempts}\."
            for admin_id_ in admins:
                try:
                    context.bot.send_message(chat_id=admin_id_, text=admin_notification, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception as e:
                    logger.error(f"Failed to send admin notification to {admin_id_}: {e}")

    except BadRequest as e:
        if "Can't parse entities" in str(e):
             logger.error(f"Markdown parsing error sending code to {user.id}: {e}. Sending as plain text.")
             plain_text = (
                f"🔐 رمز المصادقة الثنائية الخاص بك:\n\n"
                f"{code}\n\n"
                f"⚠️ هذا الرمز صالح لمدة 30 ثانية فقط.\n"
                f"🔄 المحاولات المتبقية اليوم: {remaining_attempts}"
             )
             try:
                 context.bot.send_message(chat_id=user.id, text=plain_text)
                 query.answer("✅ تم إرسال الرمز إليك في رسالة خاصة.")
             except Exception as plain_e:
                 logger.error(f"Failed to send 2FA code as plain text to user {user.id}: {plain_e}")
                 query.answer("حدث خطأ أثناء إرسال الرمز. حاول مرة أخرى أو تواصل مع المسؤول.", show_alert=True)
        else:
            logger.error(f"Failed to send 2FA code to user {user.id}: {e}")
            query.answer("حدث خطأ أثناء إرسال الرمز. حاول مرة أخرى أو تواصل مع المسؤول.", show_alert=True)
    except TelegramError as e:
        logger.error(f"Telegram error sending 2FA code to user {user.id}: {e}")
        query.answer("حدث خطأ أثناء إرسال الرمز. حاول مرة أخرى أو تواصل مع المسؤول.", show_alert=True)

# --- معالج ردود الأزرار المضمنة العام (خارج المحادثات) --- #
def general_callback_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query:
        return
    user_id = query.from_user.id
    data = query.data

    if data == "admin_close" and is_admin(user_id):
        query.answer()
        try:
            query.edit_message_text(text="تم إغلاق لوحة التحكم.")
        except Exception as e:
            logger.info(f"Failed to edit message on close: {e}")
        return

    elif data.startswith(("grp_", "interval_", "format_", "attempts_", "admins_")) and not is_admin(user_id):
        try:
            query.answer("عذراً، هذه الأزرار مخصصة للمسؤولين فقط.", show_alert=True)
        except BadRequest:
            pass
        return
    else:
        try:
            # Answer callbacks not handled by conversations to remove loading state
            query.answer()
            logger.debug(f"General callback answered: {data}")
        except BadRequest:
             pass

# --- الدالة الرئيسية --- #
def main() -> None:
    persistence = PicklePersistence(filename=PERSISTENCE_FILE)
    updater = Updater(TOKEN, persistence=persistence, use_context=True)
    dispatcher = updater.dispatcher

    # --- محادثة إدارة المجموعات --- #
    group_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_groups_entry, pattern="^grp_manage$")],
        states={
            SELECTING_GROUP_ACTION: [
                CallbackQueryHandler(ask_group_id, pattern="^grp_add$"),
                CallbackQueryHandler(select_group_to_edit, pattern="^grp_edit_select$"),
                CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$")
            ],
            ASKING_GROUP_ID: [MessageHandler(Filters.text & ~Filters.command, receive_group_id)],
            ASKING_TOTP_SECRET: [MessageHandler(Filters.text & ~Filters.command, receive_totp_secret)],
            SELECTING_GROUP_TO_EDIT: [
                CallbackQueryHandler(select_edit_action, pattern="^grp_select_-?\\d+$"),
                CallbackQueryHandler(back_to_group_manage_menu, pattern="^grp_back_to_manage$")
            ],
            SELECTING_EDIT_ACTION: [
                CallbackQueryHandler(ask_new_totp, pattern="^grp_edit_secret_-?\\d+$"),
                CallbackQueryHandler(confirm_delete_group, pattern="^grp_delete_confirm_-?\\d+$"),
                CallbackQueryHandler(select_group_to_edit, pattern="^grp_edit_select$")
            ],
            ASKING_NEW_TOTP: [MessageHandler(Filters.text & ~Filters.command, receive_new_totp)],
            CONFIRMING_DELETE: [
                CallbackQueryHandler(execute_delete_group, pattern="^grp_delete_yes_-?\\d+$"),
                CallbackQueryHandler(cancel_delete_group, pattern="^grp_delete_no_-?\\d+$")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$"),
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command)
        ],
        map_to_parent={
            ADMIN_MAIN_MENU: ADMIN_MAIN_MENU,
            ConversationHandler.END: ADMIN_MAIN_MENU
        },
        persistent=True,
        name="group_management_conversation"
    )

    # --- محادثة إدارة المحاولات --- #
    attempts_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_attempts_entry, pattern="^attempts_manage$")],
        states={
            SELECTING_USER_FOR_ATTEMPTS: [
                 CallbackQueryHandler(select_attempt_action, pattern="^att_select_user_\\d+$"),
                 CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$")
            ],
            SELECTING_ATTEMPTS_ACTION: [
                CallbackQueryHandler(toggle_ban_user, pattern="^att_(?:ban|unban)_\\d+$"),
                CallbackQueryHandler(ask_attempts_number, pattern="^att_(?:add|remove)_\\d+$"),
                CallbackQueryHandler(manage_attempts_entry, pattern="^attempts_manage$") # Back to user list
            ],
            ASKING_ATTEMPTS_NUMBER_ADD: [MessageHandler(Filters.text & ~Filters.command, receive_attempts_number)],
            ASKING_ATTEMPTS_NUMBER_REMOVE: [MessageHandler(Filters.text & ~Filters.command, receive_attempts_number)],
        },
         fallbacks=[
            CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$"),
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command)
        ],
        map_to_parent={
            ADMIN_MAIN_MENU: ADMIN_MAIN_MENU,
            ConversationHandler.END: ADMIN_MAIN_MENU
        },
        persistent=True,
        name="attempts_management_conversation"
    )

    # --- محادثة إدارة الفاصل الزمني/التفعيل --- #
    interval_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_interval_entry, pattern="^interval_manage$")],
        states={
            SELECTING_GROUP_FOR_INTERVAL: [
                CallbackQueryHandler(select_interval_options, pattern="^interval_select_grp_-?\\d+$"),
                CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$")
            ],
            SELECTING_INTERVAL_ACTION: [
                CallbackQueryHandler(set_interval, pattern="^interval_set_\\d+$"),
                CallbackQueryHandler(toggle_enable_group, pattern="^interval_(?:enable|disable)_-?\\d+$"),
                CallbackQueryHandler(manage_interval_entry, pattern="^interval_manage$") # Back to group list
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$"),
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command)
        ],
        map_to_parent={
            ADMIN_MAIN_MENU: ADMIN_MAIN_MENU,
            ConversationHandler.END: ADMIN_MAIN_MENU
        },
        persistent=True,
        name="interval_management_conversation"
    )

    # --- محادثة إدارة التنسيق/الوقت --- #
    format_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_format_entry, pattern="^format_manage$")],
        states={
            SELECTING_GROUP_FOR_FORMAT: [
                CallbackQueryHandler(select_format_options, pattern="^format_select_grp_-?\\d+$"),
                CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$")
            ],
            SELECTING_FORMAT_ACTION: [
                CallbackQueryHandler(set_time_format, pattern="^format_set_tf_(?:12|24)$"), # Added comma here
                CallbackQueryHandler(set_timezone, pattern="^format_set_tz_.+$"), # Pattern for timezone
                CallbackQueryHandler(manage_format_entry, pattern="^format_manage$") # Back to group list
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$"),
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command)
        ],
        map_to_parent={
            ADMIN_MAIN_MENU: ADMIN_MAIN_MENU,
            ConversationHandler.END: ADMIN_MAIN_MENU
        },
        persistent=True,
        name="format_management_conversation"
    )

    # --- محادثة إدارة المسؤولين --- #
    admins_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_admins_entry, pattern="^admins_manage$")],
        states={
            SELECTING_ADMIN_ACTION: [
                CallbackQueryHandler(ask_admin_id_to_add, pattern="^admin_add$"),
                CallbackQueryHandler(ask_admin_id_to_remove, pattern="^admin_remove$"),
                CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$")
            ],
            ASKING_ADMIN_ID_TO_ADD: [MessageHandler(Filters.text & ~Filters.command, receive_admin_id_to_add)],
            ASKING_ADMIN_ID_TO_REMOVE: [
                CallbackQueryHandler(execute_remove_admin, pattern="^admin_remove_id_\\d+$"),
                CallbackQueryHandler(manage_admins_entry, pattern="^admins_manage$") # Go back if cancel/invalid
            ],
        },
        fallbacks=[
            CallbackQueryHandler(back_to_admin_main_menu, pattern="^admin_back$"),
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command)
        ],
        map_to_parent={
            ADMIN_MAIN_MENU: ADMIN_MAIN_MENU,
            ConversationHandler.END: ADMIN_MAIN_MENU
        },
        persistent=True,
        name="admin_management_conversation"
    )

    # تسجيل معالجات الأوامر
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("admin", admin_command))

    # تسجيل محادثات الإدارة (يجب أن تكون قبل المعالجات العامة)
    dispatcher.add_handler(group_conv_handler)
    dispatcher.add_handler(attempts_conv_handler)
    dispatcher.add_handler(interval_conv_handler)
    dispatcher.add_handler(format_conv_handler)
    dispatcher.add_handler(admins_conv_handler)

    # تسجيل معالج زر النسخ
    dispatcher.add_handler(CallbackQueryHandler(copy_code_callback, pattern="^copy_code_-?\\d+$"))

    # تسجيل معالج ردود الأزرار العام (أولوية منخفضة)
    dispatcher.add_handler(CallbackQueryHandler(general_callback_handler), group=1)

    logger.info("Starting bot...")
    updater.start_polling()
    logger.info("Bot ChatGPTPlus2FABot started successfully.")
    updater.idle()

if __name__ == "__main__":
    main()


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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, User
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, MessageHandler,
    Filters, CallbackContext, ConversationHandler, PicklePersistence
    # ملاحظة: استيراد Filters من telegram.ext صحيح لـ python-telegram-bot v13.15.
    # إذا استمر ظهور خطأ ImportError بخصوص Filters، يرجى التأكد من أن البيئة تستخدم
    # الإصدار 13.15 بالضبط وأنه لا يوجد تعارض مع إصدارات أقدم مثبتة.
)
from unittest.mock import MagicMock # Import MagicMock for dummy updates

# --- إعدادات أساسية --- #
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM" # استبدل بالتوكن الخاص بك
ADMIN_ID = 764559466 # استبدل بمعرف المستخدم المسؤول الأولي

# --- مسارات الملفات --- #
# تأكد من أن هذا المسار صحيح وقابل للكتابة بواسطة البوت
DATA_DIR = "data" # تم تغيير المسار ليكون نسبياً لمجلد التشغيل
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
        # Ensure secret is a string before stripping
        if not isinstance(secret, str):
            secret = str(secret)
        secret = secret.strip().upper()
        # Add padding if necessary
        padding = len(secret) % 8
        if padding != 0:
            secret += "=" * (8 - padding)
        # Validate base32 decoding before creating TOTP object
        base64.b32decode(secret, casefold=True)
        totp = pyotp.TOTP(secret)
        return totp.now(), None
    except (binascii.Error, ValueError, Exception) as e:
        error_msg = f"خطأ في توليد TOTP (قد يكون المفتاح غير صالح): {e}"
        logger.error(error_msg)
        return None, error_msg

def is_valid_totp_secret(secret):
    if not secret or not isinstance(secret, str):
        return False
    try:
        secret_upper = secret.strip().upper()
        padding = len(secret_upper) % 8
        if padding != 0:
            secret_upper += "=" * (8 - padding)
        base64.b32decode(secret_upper, casefold=True)
        # Don't generate OTP here, just check decode
        # pyotp.TOTP(secret_upper).now() # This might fail if time sync is off
        return True
    except Exception:
        return False

def is_valid_group_id(group_id_str):
    if not group_id_str or not isinstance(group_id_str, str):
        return False
    if not group_id_str.startswith("-"):
        return False
    try:
        int(group_id_str) # Check if the rest is numeric
        return True
    except ValueError:
        return False

def get_user_attempts_data(user_id, user_first_name=None):
    user_id_str = str(user_id)
    # Use bot's default timezone for daily reset consistency
    bot_timezone_str = global_settings.get("default_timezone", "Asia/Gaza")
    today_str = get_current_time(bot_timezone_str).date().isoformat()
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

    # Update first name if it was generic before
    if user_first_name and user_data.get("first_name", "").startswith("User_"):
        user_data["first_name"] = user_first_name
        # Save will happen on reset or modification

    # Check for daily reset
    if user_data.get("last_reset") != today_str:
        first_name = user_data.get("first_name", f"User_{user_id_str}") # Get name with fallback
        logger.info(f"إعادة تعيين المحاولات للمستخدم {user_id_str} ({first_name}) لليوم الجديد {today_str}")
        user_data["attempts_left"] = default_attempts
        user_data["last_reset"] = today_str
        # Reset ban status on daily reset? Decide based on requirements. Let's keep ban status persistent.
        # user_data["banned"] = False
        save_json(ATTEMPTS_FILE, user_attempts)

    return user_data

def get_group_title(context: CallbackContext, group_id_str: str) -> str:
    """Helper to get group title, falling back to ID."""
    try:
        chat = context.bot.get_chat(chat_id=group_id_str)
        return chat.title if chat.title else group_id_str
    except Exception as e:
        logger.warning(f"لم يتم العثور على عنوان المجموعة {group_id_str}: {e}")
        return group_id_str

# --- دالة إرسال/تحديث رسالة المجموعة --- #
def send_or_update_group_message(context: CallbackContext, group_id_str: str):
    """Sends or edits the main message in the group with the Copy Code button."""
    if group_id_str not in groups_data:
        logger.warning(f"محاولة إرسال رسالة لمجموعة غير موجودة {group_id_str}")
        return

    group_info = groups_data[group_id_str]
    settings = group_info.get("settings", {})
    is_enabled = settings.get("enabled", False) # Default to False if not set
    interval_seconds = settings.get("interval", global_settings["default_interval"])
    time_format = settings.get("time_format", global_settings["default_time_format"])
    timezone_str = settings.get("timezone", global_settings["default_timezone"])
    message_id = group_info.get("message_id")

    if not is_enabled:
        # If disabled, try to delete the existing message
        if message_id:
            try:
                context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
                logger.info(f"تم حذف الرسالة {message_id} في المجموعة {group_id_str} لأنها معطلة.")
                groups_data[group_id_str]["message_id"] = None
                save_json(GROUPS_FILE, groups_data)
            except Exception as e:
                # Log error but don't stop execution, message might already be deleted
                logger.error(f"فشل حذف الرسالة {message_id} في المجموعة {group_id_str}: {e}")
                # Clear the message ID anyway if deletion fails
                groups_data[group_id_str]["message_id"] = None
                save_json(GROUPS_FILE, groups_data)
        return # Do not send a new message if disabled

    # Construct the message text
    now = get_current_time(timezone_str)
    next_update_time = now + timedelta(seconds=interval_seconds)
    time_str = format_time(next_update_time, time_format)
    interval_desc = next((k for k, v in AVAILABLE_INTERVALS.items() if v == interval_seconds), f"{interval_seconds} ثانية")

    # Escape MarkdownV2 characters
    def escape_md(text):
        # Ensure text is a string before escaping
        text = str(text)
        escape_chars = "\\_\\*\\[\\]\\(\\)\\~\\`\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"
        # Use replace method for efficiency
        for char in escape_chars:
            text = text.replace(char, "\\" + char)
        return text

    # Message Format (Currently only one format)
    group_title_escaped = escape_md(get_group_title(context, group_id_str))
    # Pre-escape static text parts to avoid issues within f-string
    bot_name_escaped = escape_md("ChatGPTPlus2FABot")
    instruction_escaped = escape_md("اضغط على الزر أدناه للحصول على رمز المصادقة الثنائية (2FA) الخاص بك.")
    next_update_label_escaped = escape_md("التحديث المتوقع التالي:")
    interval_label_escaped = escape_md("الفاصل الزمني:")
    note_escaped = escape_md("(ملاحظة: الرمز يُرسل في رسالة خاصة عند الضغط على الزر)")
    time_str_escaped = escape_md(time_str)
    timezone_str_escaped = escape_md(timezone_str)
    interval_desc_escaped = escape_md(interval_desc)

    message_text = (
        f"🔑 *{bot_name_escaped} \| {group_title_escaped}* 🔑\n\n"
        f"{instruction_escaped}\n\n"
        f"⏳ *{next_update_label_escaped}* {time_str_escaped} \({timezone_str_escaped}\)\n"
        f"🔄 *{interval_label_escaped}* {interval_desc_escaped}\n\n"
        f"_{note_escaped}_"
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
            logger.info(f"تم تحديث الرسالة {message_id} في المجموعة {group_id_str}")
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
            logger.info(f"تم إرسال رسالة جديدة {sent_message.message_id} إلى المجموعة {group_id_str}")

    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"الرسالة {message_id} في المجموعة {group_id_str} لم يتم تعديلها.")
        elif "message to edit not found" in str(e).lower() or "message to delete not found" in str(e).lower():
            logger.warning(f"الرسالة {message_id} غير موجودة في المجموعة {group_id_str}. سيتم إرسال واحدة جديدة.")
            groups_data[group_id_str]["message_id"] = None # Clear invalid message ID
            save_json(GROUPS_FILE, groups_data)
            # Avoid recursion loop, let the next trigger handle it or handle manually
            # send_or_update_group_message(context, group_id_str) # Retry sending - POTENTIAL LOOP
        elif "can't parse entities" in str(e).lower():
             logger.error(f"خطأ في تحليل Markdown للمجموعة {group_id_str}: {e}. تحقق من تنسيق الرسالة والـ escaping.")
             # Consider sending plain text as fallback?
             try:
                 context.bot.send_message(chat_id=group_id_str, text="حدث خطأ في عرض الرسالة. يرجى مراجعة الإعدادات.", reply_markup=reply_markup)
             except Exception as fallback_e:
                 logger.error(f"فشل إرسال رسالة الخطأ البديلة: {fallback_e}")
        else:
            logger.error(f"خطأ BadRequest عند إرسال/تعديل الرسالة في المجموعة {group_id_str}: {e}")
            # Could potentially disable the group or clear message_id if persistent errors occur
    except TelegramError as e:
        logger.error(f"خطأ Telegram عند إرسال/تعديل الرسالة في المجموعة {group_id_str}: {e}")
        # Handle specific errors like bot blocked, chat not found etc.
        if "bot was kicked" in str(e).lower() or "chat not found" in str(e).lower() or "bot was blocked" in str(e).lower():
             logger.warning(f"يبدو أن البوت تم إزالته/حظره من المجموعة {group_id_str}. سيتم تعطيلها.")
             if group_id_str in groups_data:
                 groups_data[group_id_str]["settings"]["enabled"] = False
                 groups_data[group_id_str]["message_id"] = None
                 save_json(GROUPS_FILE, groups_data)

# --- معالجات الأوامر الأساسية --- #
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    # Initialize user data if not present
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
        [InlineKeyboardButton("🔐 إدارة المجموعات/الأسرار", callback_data="admin_grp_manage")],
        [InlineKeyboardButton("🔄 إدارة فترة التكرار/التفعيل", callback_data="admin_interval_manage")],
        [InlineKeyboardButton("🎨 إدارة شكل/توقيت الرسالة", callback_data="admin_format_manage")],
        [InlineKeyboardButton("👥 إدارة محاولات المستخدمين", callback_data="admin_attempts_manage")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_admins_manage")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg_text = "لوحة تحكم المسؤول:\n(ملاحظة: الإرسال الدوري التلقائي غير مفعل حالياً)"
    if update.callback_query:
        query = update.callback_query
        try:
            query.answer()
            query.edit_message_text(msg_text, reply_markup=reply_markup)
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug("Admin menu message not modified.")
            else:
                logger.warning(f"Failed to edit admin menu message: {e}")
                # If edit fails, maybe the original message was deleted, try sending new one
                try:
                    context.bot.send_message(chat_id=query.message.chat_id, text=msg_text, reply_markup=reply_markup)
                except Exception as send_e:
                    logger.error(f"Failed to send admin menu message after edit failure: {send_e}")
        except Exception as e:
             logger.error(f"Unexpected error editing admin menu: {e}")
    else:
        update.message.reply_text(msg_text, reply_markup=reply_markup)

    # Use a unique state for the main admin menu to avoid conflicts
    return SELECTING_GROUP_ACTION # Or a dedicated ADMIN_MENU_STATE

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
        update.message.reply_text("معرف المجموعة غير صالح. يجب أن يبدأ بـ '-' ويحتوي على أرقام فقط. حاول مرة أخرى.")
        return ASKING_GROUP_ID

    if group_id_str in groups_data:
        update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة التعديل.")
        # Go back to group management menu
        # Need to resend the menu - how to get the original message?
        # Maybe just end the conversation here or send a new menu
        admin_command(update, context) # Try to resend main menu
        return ConversationHandler.END # End this specific flow

    context.user_data['new_group_id'] = group_id_str
    update.message.reply_text("تم استلام معرف المجموعة. الآن يرجى إرسال المفتاح السري TOTP (بتنسيق Base32).")
    return ASKING_TOTP_SECRET

def receive_totp_secret(update: Update, context: CallbackContext) -> int:
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get('new_group_id')

    if not group_id_str:
         update.message.reply_text("حدث خطأ، لم يتم العثور على معرف المجموعة. يرجى البدء من جديد.")
         admin_command(update, context)
         return ConversationHandler.END

    if not is_valid_totp_secret(totp_secret):
        update.message.reply_text("المفتاح السري TOTP غير صالح (يجب أن يكون Base32). حاول مرة أخرى.")
        return ASKING_TOTP_SECRET

    # Add the new group
    groups_data[group_id_str] = {
        "totp_secret": totp_secret,
        "message_id": None,
        "settings": {
            "enabled": True, # Enable by default
            "interval": global_settings["default_interval"],
            "time_format": global_settings["default_time_format"],
            "timezone": global_settings["default_timezone"]
        }
    }
    save_json(GROUPS_FILE, groups_data)
    update.message.reply_text(f"تمت إضافة المجموعة {group_id_str} بنجاح وتفعيلها.")
    logger.info(f"Admin {update.effective_user.id} added group {group_id_str}")

    # Send the initial message to the group
    try:
        send_or_update_group_message(context, group_id_str)
    except Exception as e:
        logger.error(f"فشل إرسال الرسالة الأولية للمجموعة {group_id_str}: {e}")
        update.message.reply_text(f"تحذير: لم يتم إرسال رسالة الزر إلى المجموعة {group_id_str}. قد تحتاج إلى إضافتي كمسؤول في المجموعة أولاً أو التحقق من الأذونات.")

    # Clean up user_data
    if 'new_group_id' in context.user_data:
        del context.user_data['new_group_id']

    # Go back to main admin menu
    admin_command(update, context)
    return ConversationHandler.END

def select_group_to_edit(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    if not groups_data:
        query.edit_message_text("لا توجد مجموعات مضافة للتعديل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_back")]]))
        return SELECTING_GROUP_ACTION

    keyboard = []
    for group_id in groups_data.keys():
        title = get_group_title(context, group_id)
        # *** FIX: Corrected SyntaxError here ***
        keyboard.append([InlineKeyboardButton(f"{title} ({group_id})", callback_data=f"grp_select_{group_id}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="grp_manage_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر المجموعة للتعديل أو الحذف:", reply_markup=reply_markup)
    return SELECTING_GROUP_TO_EDIT

def select_edit_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="grp_manage_back")]]))
        return SELECTING_GROUP_TO_EDIT

    context.user_data['selected_group_id'] = group_id_str
    title = get_group_title(context, group_id_str)

    keyboard = [
        [InlineKeyboardButton("🔑 تعديل المفتاح السري (TOTP)", callback_data="grp_edit_secret")],
        [InlineKeyboardButton("🗑️ حذف المجموعة", callback_data="grp_delete_confirm")],
        [InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="grp_edit_select_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"اختر الإجراء للمجموعة: {title} ({group_id_str})", reply_markup=reply_markup)
    return SELECTING_EDIT_ACTION

def ask_new_totp(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get('selected_group_id')
    if not group_id_str:
        query.edit_message_text("حدث خطأ، لم يتم العثور على معرف المجموعة. يرجى البدء من جديد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_back")]]))
        return ConversationHandler.END

    query.edit_message_text(f"أرسل المفتاح السري TOTP الجديد للمجموعة {group_id_str}.")
    return ASKING_NEW_TOTP

def receive_new_totp(update: Update, context: CallbackContext) -> int:
    new_secret = update.message.text.strip()
    group_id_str = context.user_data.get('selected_group_id')

    if not group_id_str or group_id_str not in groups_data:
        update.message.reply_text("خطأ: المجموعة غير محددة أو غير موجودة. ابدأ من جديد.")
        admin_command(update, context)
        return ConversationHandler.END

    if not is_valid_totp_secret(new_secret):
        update.message.reply_text("المفتاح السري TOTP الجديد غير صالح. حاول مرة أخرى.")
        return ASKING_NEW_TOTP

    groups_data[group_id_str]["totp_secret"] = new_secret
    save_json(GROUPS_FILE, groups_data)
    update.message.reply_text(f"تم تحديث المفتاح السري للمجموعة {group_id_str} بنجاح.")
    logger.info(f"Admin {update.effective_user.id} updated TOTP secret for group {group_id_str}")

    # Go back to group edit selection
    # Need to simulate a callback query to redisplay the menu
    # This is tricky, maybe just go back to main menu?
    if 'selected_group_id' in context.user_data:
        del context.user_data['selected_group_id']
    admin_command(update, context)
    return ConversationHandler.END

def confirm_delete_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = context.user_data.get('selected_group_id')
    if not group_id_str or group_id_str not in groups_data:
        query.edit_message_text("خطأ: المجموعة غير محددة أو غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="grp_manage_back")]]))
        return SELECTING_GROUP_TO_EDIT

    title = get_group_title(context, group_id_str)
    keyboard = [
        [InlineKeyboardButton("🔴 نعم، احذفها", callback_data=f"grp_delete_yes_{group_id_str}")],
        [InlineKeyboardButton("🟢 لا، تراجع", callback_data=f"grp_delete_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"هل أنت متأكد من حذف المجموعة {title} ({group_id_str})؟ سيتم حذف رسالة الزر من المجموعة أيضاً.", reply_markup=reply_markup)
    return CONFIRMING_DELETE

def execute_delete_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة تم حذفها بالفعل أو غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="grp_manage_back")]]))
        return SELECTING_GROUP_TO_EDIT

    # Try to delete the message first
    message_id = groups_data[group_id_str].get("message_id")
    if message_id:
        try:
            context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
            logger.info(f"Deleted message {message_id} from group {group_id_str} before deleting group data.")
        except Exception as e:
            logger.warning(f"Failed to delete message {message_id} from group {group_id_str} during group deletion: {e}")

    # Delete group data
    del groups_data[group_id_str]
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {query.effective_user.id} deleted group {group_id_str}")
    query.edit_message_text(f"تم حذف المجموعة {group_id_str} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة لإدارة المجموعات", callback_data="grp_manage_back")]]))

    if 'selected_group_id' in context.user_data:
        del context.user_data['selected_group_id']

    return SELECTING_GROUP_ACTION

# --- إدارة فترة التكرار/التفعيل (CallbackQueryHandler only) --- #
def manage_interval_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if not groups_data:
        query.edit_message_text("لا توجد مجموعات مضافة لإدارة الفاصل الزمني.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_back")]]))
        return ADMIN_MAIN_MENU

    keyboard = []
    for group_id, data in groups_data.items():
        title = get_group_title(context, group_id)
        status = "🟢" if data.get("settings", {}).get("enabled", False) else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {title} ({group_id})", callback_data=f"interval_select_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر مجموعة لإدارة الفاصل الزمني (للعرض) والتفعيل:", reply_markup=reply_markup)
    return SELECTING_GROUP_FOR_INTERVAL

def select_interval_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_interval_manage")]]))
        return SELECTING_GROUP_FOR_INTERVAL

    context.user_data['selected_group_id_interval'] = group_id_str
    title = get_group_title(context, group_id_str)
    settings = groups_data[group_id_str].get("settings", {})
    current_interval = settings.get("interval", global_settings["default_interval"])
    is_enabled = settings.get("enabled", False)

    keyboard = []
    # Interval buttons
    for name, seconds in AVAILABLE_INTERVALS.items():
        prefix = "✅" if seconds == current_interval else ""
        keyboard.append([InlineKeyboardButton(f"{prefix} {name}", callback_data=f"interval_set_{group_id_str}_{seconds}")])

    # Enable/Disable button
    enable_text = "🔴 تعطيل النسخ" if is_enabled else "🟢 تفعيل النسخ"
    enable_action = "disable" if is_enabled else "enable"
    keyboard.append([InlineKeyboardButton(enable_text, callback_data=f"interval_toggle_{group_id_str}_{enable_action}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="admin_interval_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"إعدادات الفاصل الزمني والتفعيل للمجموعة: {title} ({group_id_str})", reply_markup=reply_markup)
    return SELECTING_INTERVAL_ACTION

def set_interval(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    parts = query.data.split("_")
    group_id_str = parts[2]
    interval_seconds = int(parts[3])

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_interval_manage")]]))
        return SELECTING_GROUP_FOR_INTERVAL

    groups_data[group_id_str]["settings"]["interval"] = interval_seconds
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {query.effective_user.id} set interval for group {group_id_str} to {interval_seconds}s")

    # Update the message in the group
    send_or_update_group_message(context, group_id_str)

    # Refresh the interval selection menu for this group
    # Need to simulate the previous callback
    query.data = f"interval_select_{group_id_str}" # Simulate previous callback
    return select_interval_action(update, context)

def toggle_enable_group(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    parts = query.data.split("_")
    group_id_str = parts[2]
    action = parts[3] # "enable" or "disable"

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_interval_manage")]]))
        return SELECTING_GROUP_FOR_INTERVAL

    new_status = (action == "enable")
    groups_data[group_id_str]["settings"]["enabled"] = new_status
    save_json(GROUPS_FILE, groups_data)
    status_text = "تفعيل" if new_status else "تعطيل"
    logger.info(f"Admin {query.effective_user.id} {status_text} group {group_id_str}")

    # Update/delete the message in the group
    send_or_update_group_message(context, group_id_str)

    # Refresh the interval selection menu for this group
    query.data = f"interval_select_{group_id_str}" # Simulate previous callback
    return select_interval_action(update, context)

# --- إدارة شكل/توقيت الرسالة (CallbackQueryHandler only) --- #
def manage_format_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if not groups_data:
        query.edit_message_text("لا توجد مجموعات مضافة لإدارة التنسيق.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_back")]]))
        return ADMIN_MAIN_MENU

    keyboard = []
    for group_id, data in groups_data.items():
        title = get_group_title(context, group_id)
        settings = data.get("settings", {})
        tf = settings.get("time_format", global_settings["default_time_format"])
        tz = settings.get("timezone", global_settings["default_timezone"])
        keyboard.append([InlineKeyboardButton(f"{title} ({group_id}) [وقت:{tf}h, منطقة:{tz}]", callback_data=f"format_select_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر مجموعة لإدارة تنسيق الوقت والمنطقة الزمنية:", reply_markup=reply_markup)
    return SELECTING_GROUP_FOR_FORMAT

def select_format_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    group_id_str = query.data.split("_")[-1]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_format_manage")]]))
        return SELECTING_GROUP_FOR_FORMAT

    context.user_data['selected_group_id_format'] = group_id_str
    title = get_group_title(context, group_id_str)
    settings = groups_data[group_id_str].get("settings", {})
    current_tf = settings.get("time_format", global_settings["default_time_format"])
    current_tz = settings.get("timezone", global_settings["default_timezone"])

    keyboard = []
    # Time Format buttons
    keyboard.append([InlineKeyboardButton("--- تنسيق الوقت ---", callback_data="noop")])
    for name, value in AVAILABLE_TIME_FORMATS.items():
        prefix = "✅" if value == current_tf else ""
        keyboard.append([InlineKeyboardButton(f"{prefix} {name}", callback_data=f"format_set_tf_{group_id_str}_{value}")])

    # Timezone buttons
    keyboard.append([InlineKeyboardButton("--- المنطقة الزمنية ---", callback_data="noop")])
    for name, value in AVAILABLE_TIMEZONES.items():
        prefix = "✅" if value == current_tz else ""
        keyboard.append([InlineKeyboardButton(f"{prefix} {name}", callback_data=f"format_set_tz_{group_id_str}_{value}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة لاختيار مجموعة", callback_data="admin_format_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"إعدادات التنسيق للمجموعة: {title} ({group_id_str})", reply_markup=reply_markup)
    return SELECTING_FORMAT_ACTION

def set_time_format(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    parts = query.data.split("_")
    group_id_str = parts[3]
    time_format_value = parts[4]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_format_manage")]]))
        return SELECTING_GROUP_FOR_FORMAT

    groups_data[group_id_str]["settings"]["time_format"] = time_format_value
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {query.effective_user.id} set time format for group {group_id_str} to {time_format_value}h")

    # Update the message in the group
    send_or_update_group_message(context, group_id_str)

    # Refresh the format selection menu
    query.data = f"format_select_{group_id_str}"
    return select_format_action(update, context)

def set_timezone(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    parts = query.data.split("_")
    group_id_str = parts[3]
    timezone_value = parts[4]

    if group_id_str not in groups_data:
        query.edit_message_text("المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_format_manage")]]))
        return SELECTING_GROUP_FOR_FORMAT

    # Validate timezone just in case
    try:
        pytz.timezone(timezone_value)
    except pytz.UnknownTimeZoneError:
        query.edit_message_text(f"خطأ: المنطقة الزمنية '{timezone_value}' غير صالحة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data=f"format_select_{group_id_str}")]]))
        # Go back to format selection menu for this group
        query.data = f"format_select_{group_id_str}"
        return select_format_action(update, context)

    groups_data[group_id_str]["settings"]["timezone"] = timezone_value
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {query.effective_user.id} set timezone for group {group_id_str} to {timezone_value}")

    # Update the message in the group
    send_or_update_group_message(context, group_id_str)

    # Refresh the format selection menu
    query.data = f"format_select_{group_id_str}"
    return select_format_action(update, context)

# --- إدارة محاولات المستخدمين (ConversationHandler) --- #
def manage_attempts_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    if not user_attempts:
        query.edit_message_text("لا يوجد مستخدمون مسجلون لإدارة محاولاتهم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_back")]]))
        return ADMIN_MAIN_MENU

    keyboard = []
    for user_id_str, data in user_attempts.items():
        name = data.get("first_name", f"User_{user_id_str}")
        attempts = data.get("attempts_left", "N/A")
        banned_status = "🚫" if data.get("banned", False) else "✅"
        keyboard.append([InlineKeyboardButton(f"{banned_status} {name} ({user_id_str}) - محاولات: {attempts}", callback_data=f"attempts_select_{user_id_str}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر مستخدماً لإدارة محاولاته أو حظره:", reply_markup=reply_markup)
    return SELECTING_USER_FOR_ATTEMPTS

def select_user_action(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = query.data.split("_")[-1]

    if user_id_str not in user_attempts:
        query.edit_message_text("المستخدم لم يعد موجوداً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_attempts_manage")]]))
        return SELECTING_USER_FOR_ATTEMPTS

    context.user_data['selected_user_id_attempts'] = user_id_str
    user_data = user_attempts[user_id_str]
    name = user_data.get("first_name", f"User_{user_id_str}")
    attempts = user_data.get("attempts_left", "N/A")
    is_banned = user_data.get("banned", False)

    ban_text = "🔓 إلغاء حظر المستخدم" if is_banned else "🚫 حظر المستخدم"
    ban_action = "unban" if is_banned else "ban"

    keyboard = [
        [InlineKeyboardButton(ban_text, callback_data=f"attempts_toggleban_{user_id_str}_{ban_action}")],
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data=f"attempts_add_{user_id_str}")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data=f"attempts_remove_{user_id_str}")],
        [InlineKeyboardButton("🔙 العودة لاختيار مستخدم", callback_data="admin_attempts_manage")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"إدارة المستخدم: {name} ({user_id_str})\nمحاولات متبقية: {attempts}", reply_markup=reply_markup)
    return SELECTING_ATTEMPTS_ACTION

def toggle_ban_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    parts = query.data.split("_")
    user_id_str = parts[2]
    action = parts[3] # "ban" or "unban"

    if user_id_str not in user_attempts:
        query.edit_message_text("المستخدم لم يعد موجوداً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_attempts_manage")]]))
        return SELECTING_USER_FOR_ATTEMPTS

    new_ban_status = (action == "ban")
    user_attempts[user_id_str]["banned"] = new_ban_status
    save_json(ATTEMPTS_FILE, user_attempts)
    status_text = "حظر" if new_ban_status else "إلغاء حظر"
    logger.info(f"Admin {query.effective_user.id} {status_text} user {user_id_str}")
    # query.edit_message_text(f"تم {status_text} المستخدم {user_id_str} بنجاح.") # Keep the menu

    # Refresh the user selection menu
    query.data = f"attempts_select_{user_id_str}"
    return select_user_action(update, context)

def ask_attempts_add(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = query.data.split("_")[-1]
    context.user_data['selected_user_id_attempts'] = user_id_str # Ensure it's set
    query.edit_message_text(f"أرسل عدد المحاولات التي تريد إضافتها للمستخدم {user_id_str}.")
    return ASKING_ATTEMPTS_NUMBER_ADD

def receive_attempts_add(update: Update, context: CallbackContext) -> int:
    try:
        num_to_add = int(update.message.text.strip())
        if num_to_add <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        update.message.reply_text("الرجاء إدخال رقم صحيح موجب لعدد المحاولات.")
        return ASKING_ATTEMPTS_NUMBER_ADD

    user_id_str = context.user_data.get('selected_user_id_attempts')
    if not user_id_str or user_id_str not in user_attempts:
        update.message.reply_text("خطأ: المستخدم غير محدد أو غير موجود. ابدأ من جديد.")
        admin_command(update, context)
        return ConversationHandler.END

    # Ensure attempts_left is initialized correctly
    if "attempts_left" not in user_attempts[user_id_str] or not isinstance(user_attempts[user_id_str]["attempts_left"], int):
        user_attempts[user_id_str]["attempts_left"] = 0 # Initialize if missing or invalid

    user_attempts[user_id_str]["attempts_left"] += num_to_add
    save_json(ATTEMPTS_FILE, user_attempts)
    logger.info(f"Admin {update.effective_user.id} added {num_to_add} attempts to user {user_id_str}")
    update.message.reply_text(f"تمت إضافة {num_to_add} محاولة للمستخدم {user_id_str}. الرصيد الحالي: {user_attempts[user_id_str]['attempts_left']}")

    # Go back to user action selection menu
    # Need to simulate callback query
    # Create a dummy update for the callback
    dummy_update = MagicMock(spec=Update)
    dummy_update.callback_query = MagicMock()
    dummy_update.callback_query.data = f"attempts_select_{user_id_str}"
    dummy_update.callback_query.message = update.message # Use original message context if possible
    dummy_update.callback_query.from_user = update.effective_user
    dummy_update.callback_query.answer = lambda: None
    # Use reply_text as edit_message_text is not available on message update
    dummy_update.callback_query.edit_message_text = lambda text, reply_markup=None, parse_mode=None: update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

    return select_user_action(dummy_update, context)

def ask_attempts_remove(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    user_id_str = query.data.split("_")[-1]
    context.user_data['selected_user_id_attempts'] = user_id_str # Ensure it's set
    query.edit_message_text(f"أرسل عدد المحاولات التي تريد حذفها من المستخدم {user_id_str}.")
    return ASKING_ATTEMPTS_NUMBER_REMOVE

def receive_attempts_remove(update: Update, context: CallbackContext) -> int:
    try:
        num_to_remove = int(update.message.text.strip())
        if num_to_remove <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        update.message.reply_text("الرجاء إدخال رقم صحيح موجب لعدد المحاولات.")
        return ASKING_ATTEMPTS_NUMBER_REMOVE

    user_id_str = context.user_data.get('selected_user_id_attempts')
    if not user_id_str or user_id_str not in user_attempts:
        update.message.reply_text("خطأ: المستخدم غير محدد أو غير موجود. ابدأ من جديد.")
        admin_command(update, context)
        return ConversationHandler.END

    # Ensure attempts_left is initialized correctly
    if "attempts_left" not in user_attempts[user_id_str] or not isinstance(user_attempts[user_id_str]["attempts_left"], int):
        user_attempts[user_id_str]["attempts_left"] = 0 # Initialize if missing or invalid

    current_attempts = user_attempts[user_id_str]["attempts_left"]
    user_attempts[user_id_str]["attempts_left"] = max(0, current_attempts - num_to_remove)
    removed_count = current_attempts - user_attempts[user_id_str]["attempts_left"]
    save_json(ATTEMPTS_FILE, user_attempts)
    logger.info(f"Admin {update.effective_user.id} removed {removed_count} attempts from user {user_id_str}")
    update.message.reply_text(f"تم حذف {removed_count} محاولة من المستخدم {user_id_str}. الرصيد الحالي: {user_attempts[user_id_str]['attempts_left']}")

    # Go back to user action selection menu (using dummy update)
    dummy_update = MagicMock(spec=Update)
    dummy_update.callback_query = MagicMock()
    dummy_update.callback_query.data = f"attempts_select_{user_id_str}"
    dummy_update.callback_query.message = update.message
    dummy_update.callback_query.from_user = update.effective_user
    dummy_update.callback_query.answer = lambda: None
    dummy_update.callback_query.edit_message_text = lambda text, reply_markup=None, parse_mode=None: update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

    return select_user_action(dummy_update, context)

# --- إدارة المسؤولين (ConversationHandler) --- #
def manage_admins_entry(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admin_add")],
    ]
    if len(admins) > 1:
        keyboard.append([InlineKeyboardButton("➖ إزالة مسؤول", callback_data="admin_remove_select")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_list = "\n".join([f"- `{admin_id}`" for admin_id in admins])
    query.edit_message_text(text=f"إدارة المسؤولين:\nالمسؤولون الحاليون:\n{admin_list}", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return SELECTING_ADMIN_ACTION

def ask_admin_id_add(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="يرجى إرسال معرف المستخدم (User ID) للمسؤول الجديد.")
    return ASKING_ADMIN_ID_TO_ADD

def receive_admin_id_add(update: Update, context: CallbackContext) -> int:
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("معرف المستخدم يجب أن يكون رقماً صحيحاً. حاول مرة أخرى.")
        return ASKING_ADMIN_ID_TO_ADD

    if new_admin_id in admins:
        update.message.reply_text("هذا المستخدم هو مسؤول بالفعل.")
    else:
        admins.append(new_admin_id)
        save_json(ADMINS_FILE, admins)
        logger.info(f"Admin {update.effective_user.id} added new admin {new_admin_id}")
        update.message.reply_text(f"تمت إضافة المسؤول {new_admin_id} بنجاح.")

    # Go back to admin management menu
    # Need to simulate callback query
    dummy_update = MagicMock(spec=Update)
    dummy_update.callback_query = MagicMock()
    dummy_update.callback_query.data = "admin_admins_manage"
    dummy_update.callback_query.message = update.message
    dummy_update.callback_query.from_user = update.effective_user
    dummy_update.callback_query.answer = lambda: None
    dummy_update.callback_query.edit_message_text = lambda text, reply_markup=None, parse_mode=None: update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

    return manage_admins_entry(dummy_update, context)

def select_admin_to_remove(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()

    removable_admins = [admin_id for admin_id in admins if admin_id != query.effective_user.id]

    if not removable_admins:
        query.edit_message_text("لا يوجد مسؤولون آخرون لإزالتهم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")]]))
        return SELECTING_ADMIN_ACTION

    keyboard = []
    for admin_id in removable_admins:
         # Try to get user info for display name
        try:
            user = context.bot.get_chat(admin_id)
            name = user.first_name or user.username or str(admin_id)
        except Exception:
            name = str(admin_id)
        keyboard.append([InlineKeyboardButton(f"إزالة {name} ({admin_id})", callback_data=f"admin_remove_{admin_id}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text("اختر المسؤول الذي تريد إزالته:", reply_markup=reply_markup)
    return ASKING_ADMIN_ID_TO_REMOVE # Reusing state, maybe rename state?

def execute_remove_admin(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    admin_id_to_remove = int(query.data.split("_")[-1])

    if admin_id_to_remove == query.effective_user.id:
        query.edit_message_text("لا يمكنك إزالة نفسك.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")]]))
        # Go back to admin selection
        return select_admin_to_remove(update, context)

    if admin_id_to_remove not in admins:
        query.edit_message_text("المستخدم لم يعد مسؤولاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")]]))
    elif len(admins) <= 1:
        query.edit_message_text("لا يمكن إزالة المسؤول الوحيد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")]]))
    else:
        admins.remove(admin_id_to_remove)
        save_json(ADMINS_FILE, admins)
        logger.info(f"Admin {query.effective_user.id} removed admin {admin_id_to_remove}")
        query.edit_message_text(f"تمت إزالة المسؤول {admin_id_to_remove} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_admins_manage")]]))

    # Go back to admin management menu
    query.data = "admin_admins_manage"
    return manage_admins_entry(update, context)

# --- معالج زر نسخ الرمز --- #
def copy_code_button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user = query.effective_user
    group_id_str = query.data.split("_")[-1]

    query.answer() # Acknowledge button press immediately

    if group_id_str not in groups_data:
        logger.warning(f"User {user.id} clicked copy for non-existent group {group_id_str}")
        try:
            # Can't edit message if it's gone, send new message to user
            context.bot.send_message(user.id, "عذراً، هذه المجموعة لم تعد مدارة بواسطة البوت.")
            # query.edit_message_text("عذراً، هذه المجموعة لم تعد مدارة بواسطة البوت.")
        except Exception as e:
             logger.error(f"Error sending message for non-existent group callback: {e}")
        return

    group_info = groups_data[group_id_str]
    settings = group_info.get("settings", {})

    # 1. Check if group is enabled
    if not settings.get("enabled", False):
        logger.info(f"User {user.id} clicked copy for disabled group {group_id_str}")
        context.bot.send_message(user.id, f"عذراً، النسخ معطل حالياً لهذه المجموعة: {get_group_title(context, group_id_str)}.")
        return

    # 2. Get user attempts data (handles daily reset)
    user_data = get_user_attempts_data(user.id, user.first_name)

    # 3. Check if user is banned
    if user_data.get("banned", False):
        logger.info(f"Banned user {user.id} ({user_data.get('first_name')}) attempted copy for group {group_id_str}")
        context.bot.send_message(user.id, "عذراً، أنت محظور من استخدام هذا البوت.")
        return

    # 4. Check attempts left
    attempts_left = user_data.get("attempts_left", 0)
    if attempts_left <= 0:
        logger.info(f"User {user.id} ({user_data.get('first_name')}) has no attempts left for group {group_id_str}")
        context.bot.send_message(user.id, "لقد استنفدت جميع محاولات النسخ لهذا اليوم. يتم تجديد المحاولات يومياً بعد منتصف الليل.")
        return

    # 5. Generate TOTP
    totp_secret = group_info.get("totp_secret")
    code, error = generate_totp(totp_secret)

    if error:
        logger.error(f"Failed to generate TOTP for group {group_id_str} for user {user.id}: {error}")
        context.bot.send_message(user.id, f"حدث خطأ أثناء توليد الرمز للمجموعة {get_group_title(context, group_id_str)}. يرجى إبلاغ المسؤول.")
        # Notify admin?
        try:
            context.bot.send_message(ADMIN_ID, f"⚠️ فشل توليد رمز TOTP للمجموعة {group_id_str} عند طلب المستخدم {user.id} ({user.first_name}). الخطأ: {error}")
        except Exception as admin_notify_e:
            logger.error(f"Failed to notify admin about TOTP generation error: {admin_notify_e}")
        return

    # 6. Decrement attempts and save
    user_data["attempts_left"] -= 1
    save_json(ATTEMPTS_FILE, user_attempts)
    remaining_attempts = user_data["attempts_left"]

    # 7. Send code privately
    code_message = (
        f"🔑 رمز المصادقة الخاص بك للمجموعة **{get_group_title(context, group_id_str)}** هو:\n\n"
        f"`{code}`\n\n"
        f"⚠️ *هذا الرمز صالح لمدة 30 ثانية فقط.*\n"
        f"🔄 المحاولات المتبقية لك اليوم: **{remaining_attempts}**"
    )
    try:
        context.bot.send_message(user.id, code_message, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Sent TOTP code for group {group_id_str} to user {user.id}. Attempts left: {remaining_attempts}")

        # 8. Notify admin (optional)
        if global_settings.get("notify_admin_on_copy", False):
            admin_notification = f"🔔 المستخدم {user.first_name} ({user.id}) قام بنسخ الرمز للمجموعة {get_group_title(context, group_id_str)}. المحاولات المتبقية: {remaining_attempts}."
            # Send to all admins
            for admin_user_id in admins:
                try:
                    context.bot.send_message(admin_user_id, admin_notification)
                except Exception as e:
                    logger.warning(f"Failed to send copy notification to admin {admin_user_id}: {e}")

    except TelegramError as e:
        logger.error(f"Failed to send code message to user {user.id}: {e}")
        # Revert attempt count if message failed?
        user_data["attempts_left"] += 1
        save_json(ATTEMPTS_FILE, user_attempts)
        logger.info(f"Reverted attempt count for user {user.id} due to send failure.")
        # Inform user in the group chat maybe? Or just log.

# --- معالج إلغاء المحادثة --- #
def cancel_conversation(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if query:
        try:
            query.answer()
            query.edit_message_text("تم إلغاء العملية.")
        except BadRequest as e:
             if "message is not modified" in str(e).lower():
                 logger.debug("Cancel message not modified.")
             else:
                 logger.warning(f"Failed to edit cancel message: {e}")
                 # Try sending a new message if edit fails
                 try:
                     context.bot.send_message(chat_id=query.message.chat_id, text="تم إلغاء العملية.")
                 except Exception as send_e:
                     logger.error(f"Failed to send cancel message after edit failure: {send_e}")
        except Exception as e:
            logger.error(f"Unexpected error editing cancel message: {e}")
    elif update.message:
        update.message.reply_text("تم إلغاء العملية.")

    # Clean up any temporary user data
    keys_to_clear = ['new_group_id', 'selected_group_id', 'selected_user_id_attempts', 'selected_group_id_interval', 'selected_group_id_format']
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]

    # Go back to main admin menu if possible
    if query and query.message:
        # Try to resend the main menu by calling admin_command with a dummy update
        dummy_update = MagicMock(spec=Update)
        dummy_update.callback_query = query # Pass the original query for context
        dummy_update.effective_user = query.effective_user
        # Ensure the dummy update has necessary attributes for admin_command
        dummy_update.message = query.message
        return admin_command(dummy_update, context)
    elif update.message:
         return admin_command(update, context)

    return ConversationHandler.END

# --- معالج الأزرار غير المعرفة / العودة --- #
def handle_back_button(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    callback_data = query.data

    if callback_data == "admin_back":
        return admin_command(update, context)
    elif callback_data == "grp_manage_back":
        return manage_groups_entry(update, context)
    elif callback_data == "grp_edit_select_back":
        return select_group_to_edit(update, context)
    elif callback_data == "grp_delete_no":
        # Go back to edit actions for the selected group
        group_id_str = context.user_data.get('selected_group_id')
        if group_id_str:
            query.data = f"grp_select_{group_id_str}" # Simulate selection
            return select_edit_action(update, context)
        else:
            # Fallback to group selection
            return select_group_to_edit(update, context)
    elif callback_data == "admin_interval_manage":
         return manage_interval_entry(update, context)
    elif callback_data == "admin_format_manage":
         return manage_format_entry(update, context)
    elif callback_data == "admin_attempts_manage":
         return manage_attempts_entry(update, context)
    elif callback_data == "admin_admins_manage":
         return manage_admins_entry(update, context)
    elif callback_data == "admin_close":
         try:
             query.edit_message_text("تم إغلاق لوحة التحكم.")
         except BadRequest as e:
             if "message is not modified" in str(e).lower():
                 logger.debug("Close message not modified.")
             else:
                 logger.warning(f"Failed to edit close message: {e}")
         except Exception as e:
             logger.error(f"Error editing close message: {e}")
         return ConversationHandler.END
    elif callback_data == "noop": # No operation button
        return # Stay in the same state
    else:
        logger.warning(f"Unhandled back/callback button: {callback_data}")
        # Default to main admin menu
        return admin_command(update, context)

# --- الدالة الرئيسية --- #
def main() -> None:
    """Start the bot."""
    # Create data directory if it doesn't exist
    os.makedirs(DATA_DIR, exist_ok=True)

    # Create the Updater and pass it your bot's token.
    # Use persistence to store conversation states
    persistence = PicklePersistence(filename=PERSISTENCE_FILE)
    updater = Updater(TOKEN, persistence=persistence, use_context=True)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # --- Handlers --- #

    # Basic command handler
    dispatcher.add_handler(CommandHandler("start", start))

    # Conversation handler for admin functions
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_command)],
        states={
            # Main Menu State (using SELECTING_GROUP_ACTION as the entry state for the menu)
            SELECTING_GROUP_ACTION: [
                CallbackQueryHandler(manage_groups_entry, pattern='^admin_grp_manage$'),
                CallbackQueryHandler(manage_interval_entry, pattern='^admin_interval_manage$'),
                CallbackQueryHandler(manage_format_entry, pattern='^admin_format_manage$'),
                CallbackQueryHandler(manage_attempts_entry, pattern='^admin_attempts_manage$'),
                CallbackQueryHandler(manage_admins_entry, pattern='^admin_admins_manage$'),
                CallbackQueryHandler(handle_back_button, pattern='^admin_close$'), # Close button
                # Group Management Actions from Main Menu
                CallbackQueryHandler(ask_group_id, pattern='^grp_add$'),
                CallbackQueryHandler(select_group_to_edit, pattern='^grp_edit_select$'),
                CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Back to main menu (redundant?)
            ],
            # Group Management States
            ASKING_GROUP_ID: [MessageHandler(Filters.text & ~Filters.command, receive_group_id)],
            ASKING_TOTP_SECRET: [MessageHandler(Filters.text & ~Filters.command, receive_totp_secret)],
            SELECTING_GROUP_TO_EDIT: [
                CallbackQueryHandler(select_edit_action, pattern='^grp_select_'),
                CallbackQueryHandler(manage_groups_entry, pattern='^grp_manage_back$'), # Back to group actions menu
            ],
            SELECTING_EDIT_ACTION: [
                CallbackQueryHandler(ask_new_totp, pattern='^grp_edit_secret$'),
                CallbackQueryHandler(confirm_delete_group, pattern='^grp_delete_confirm$'),
                CallbackQueryHandler(select_group_to_edit, pattern='^grp_edit_select_back$'), # Back to group selection
            ],
            ASKING_NEW_TOTP: [MessageHandler(Filters.text & ~Filters.command, receive_new_totp)],
            CONFIRMING_DELETE: [
                CallbackQueryHandler(execute_delete_group, pattern='^grp_delete_yes_'),
                CallbackQueryHandler(handle_back_button, pattern='^grp_delete_no$'), # Back to edit actions
            ],
            # Interval/Enable Management States (Callback only)
            SELECTING_GROUP_FOR_INTERVAL: [
                CallbackQueryHandler(select_interval_action, pattern='^interval_select_'),
                CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Back to main menu
            ],
            SELECTING_INTERVAL_ACTION: [
                CallbackQueryHandler(set_interval, pattern='^interval_set_'),
                CallbackQueryHandler(toggle_enable_group, pattern='^interval_toggle_'),
                CallbackQueryHandler(manage_interval_entry, pattern='^admin_interval_manage$'), # Back to interval group selection
            ],
            # Format/Time Management States (Callback only)
            SELECTING_GROUP_FOR_FORMAT: [
                CallbackQueryHandler(select_format_action, pattern='^format_select_'),
                CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Back to main menu
            ],
            SELECTING_FORMAT_ACTION: [
                CallbackQueryHandler(set_time_format, pattern='^format_set_tf_'),
                CallbackQueryHandler(set_timezone, pattern='^format_set_tz_'),
                CallbackQueryHandler(manage_format_entry, pattern='^admin_format_manage$'), # Back to format group selection
                CallbackQueryHandler(handle_back_button, pattern='^noop$'), # Handle noop button
            ],
            # Attempts Management States
            SELECTING_USER_FOR_ATTEMPTS: [
                 CallbackQueryHandler(select_user_action, pattern='^attempts_select_'),
                 CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Back to main menu
            ],
            SELECTING_ATTEMPTS_ACTION: [
                 CallbackQueryHandler(toggle_ban_user, pattern='^attempts_toggleban_'),
                 CallbackQueryHandler(ask_attempts_add, pattern='^attempts_add_'),
                 CallbackQueryHandler(ask_attempts_remove, pattern='^attempts_remove_'),
                 CallbackQueryHandler(manage_attempts_entry, pattern='^admin_attempts_manage$'), # Back to user selection
            ],
            ASKING_ATTEMPTS_NUMBER_ADD: [MessageHandler(Filters.text & ~Filters.command, receive_attempts_add)],
            ASKING_ATTEMPTS_NUMBER_REMOVE: [MessageHandler(Filters.text & ~Filters.command, receive_attempts_remove)],
            # Admin Management States
            SELECTING_ADMIN_ACTION: [
                CallbackQueryHandler(ask_admin_id_add, pattern='^admin_add$'),
                CallbackQueryHandler(select_admin_to_remove, pattern='^admin_remove_select$'),
                CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Back to main menu
            ],
            ASKING_ADMIN_ID_TO_ADD: [MessageHandler(Filters.text & ~Filters.command, receive_admin_id_add)],
            ASKING_ADMIN_ID_TO_REMOVE: [
                CallbackQueryHandler(execute_remove_admin, pattern='^admin_remove_'),
                CallbackQueryHandler(manage_admins_entry, pattern='^admin_admins_manage$'), # Back to admin management menu
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            CallbackQueryHandler(cancel_conversation, pattern='^cancel$'), # Generic cancel button if needed
            # Add fallbacks for main menu buttons if they are pressed in wrong state?
            CallbackQueryHandler(handle_back_button, pattern='^admin_back$'), # Catch-all back to main menu
            CallbackQueryHandler(handle_back_button, pattern='^admin_close$'), # Catch-all close
            # Fallback for unexpected callbacks in conversation
            CallbackQueryHandler(lambda u,c: u.callback_query.answer("أمر غير متوقع في هذه المرحلة.") or ConversationHandler.END)
        ],
        name="admin_conversation",
        persistent=True, # Remember state across restarts
    )
    dispatcher.add_handler(admin_conv_handler)

    # Handler for the Copy Code button (outside conversation)
    dispatcher.add_handler(CallbackQueryHandler(copy_code_button, pattern='^copy_code_'))

    # Handler for potential leftover callbacks or unexpected ones
    dispatcher.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.answer("زر غير معروف أو منتهي الصلاحية.")))

    # Start the Bot
    updater.start_polling()
    logger.info("Bot started successfully!")

    # Keep the bot running until interrupted
    updater.idle()

if __name__ == '__main__':
    main()


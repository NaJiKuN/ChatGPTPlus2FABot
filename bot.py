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
import binascii  # Needed for TOTP error handling
from datetime import datetime, date, time, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    BasePersistence,
)
from telegram.ext.filters import Filters
from unittest.mock import MagicMock  # Import MagicMock for dummy updates

# --- إعدادات أساسية --- #
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"  # استبدل بالتوكن الخاص بك
ADMIN_ID = 764559466  # استبدل بمعرف المستخدم المسؤول الأولي

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

# --- إعداد المثابرة --- #
class PicklePersistence(BasePersistence):
    def __init__(self, filename):
        super().__init__(store_data=PersistenceInput(bot_data=True, chat_data=True, user_data=True, callback_data=True))
        self.filename = filename
        self.bot_data = {}
        self.chat_data = {}
        self.user_data = {}
        self.callback_data = {}

    async def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "rb") as f:
                    data = pickle.load(f)
                    self.bot_data = data.get("bot_data", {})
                    self.chat_data = data.get("chat_data", {})
                    self.user_data = data.get("user_data", {})
                    self.callback_data = data.get("callback_data", {})
            except Exception as e:
                logger.error(f"Error loading persistence data: {e}")

    async def save(self):
        data = {
            "bot_data": self.bot_data,
            "chat_data": self.chat_data,
            "user_data": self.user_data,
            "callback_data": self.callback_data,
        }
        try:
            with open(self.filename, "wb") as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving persistence data: {e}")

    async def get_bot_data(self):
        return self.bot_data

    async def update_bot_data(self, data):
        self.bot_data = data
        await self.save()

    async def get_chat_data(self):
        return self.chat_data

    async def update_chat_data(self, chat_id, data):
        self.chat_data[chat_id] = data
        await self.save()

    async def get_user_data(self):
        return self.user_data

    async def update_user_data(self, user_id, data):
        self.user_data[user_id] = data
        await self.save()

    async def get_callback_data(self):
        return self.callback_data

    async def update_callback_data(self, data):
        self.callback_data = data
        await self.save()

    async def drop_chat_data(self, chat_id):
        if chat_id in self.chat_data:
            del self.chat_data[chat_id]
            await self.save()

    async def drop_user_data(self, user_id):
        if user_id in self.user_data:
            del self.user_data[user_id]
            await self.save()

    async def refresh_user_data(self, user_id, user_data):
        pass  # Not implemented for simplicity

    async def refresh_chat_data(self, chat_id, chat_data):
        pass  # Not implemented for simplicity

    async def refresh_bot_data(self, bot_data):
        pass  # Not implemented for simplicity

    async def flush(self):
        await self.save()

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
groups_data = load_json(GROUPS_FILE, {})  # {group_id_str: { "totp_secret": "...", "message_id": null, "settings": {...} }}
user_attempts = load_json(ATTEMPTS_FILE, {})  # {user_id_str: { "attempts_left": N, "last_reset": "YYYY-MM-DD", "banned": false, "first_name": "..." }}
global_settings = load_json(SETTINGS_FILE, {
    "default_attempts": 5,
    "notify_admin_on_copy": False,
    "default_interval": 600,  # 10 minutes in seconds
    "default_message_format": 1,  # حالياً لا يوجد تنسيقات متعددة، لكن نتركه للمستقبل
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
        int(group_id_str)  # Check if the rest is numeric after removing the first char
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

async def get_group_title(context: ContextTypes.DEFAULT_TYPE, group_id_str: str) -> str:
    """Helper to get group title, falling back to ID."""
    try:
        chat = await context.bot.get_chat(chat_id=group_id_str)
        return chat.title if chat.title else group_id_str
    except Exception as e:
        logger.warning(f"Could not get title for group {group_id_str}: {e}")
        return group_id_str

# --- دالة إرسال/تحديث رسالة المجموعة --- #
async def send_or_update_group_message(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
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
                await context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
                logger.info(f"Deleted message {message_id} in group {group_id_str} as it was disabled.")
                groups_data[group_id_str]["message_id"] = None
                save_json(GROUPS_FILE, groups_data)
            except Exception as e:
                logger.error(f"Failed to delete message {message_id} in group {group_id_str}: {e}")
        return  # Do not send a new message if disabled

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
            await context.bot.edit_message_text(
                chat_id=group_id_str,
                message_id=message_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            logger.info(f"Updated message {message_id} in group {group_id_str}")
        else:
            # Send a new message
            sent_message = await context.bot.send_message(
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
            groups_data[group_id_str]["message_id"] = None  # Clear invalid message ID
            save_json(GROUPS_FILE, groups_data)
            await send_or_update_group_message(context, group_id_str)  # Retry sending
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_user_attempts_data(user.id, user.first_name)
    await update.message.reply_html(
        f"أهلاً بك يا {user.mention_html()} في بوت ChatGPTPlus2FABot!\n"
        f"إذا كنت مسؤولاً، يمكنك استخدام الأمر /admin لإدارة البوت."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمسؤولين فقط.")
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
        await query.answer()
        try:
            await query.edit_message_text(msg_text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"Failed to edit admin menu message: {e}")
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text=msg_text, reply_markup=reply_markup)
            except Exception as send_e:
                logger.error(f"Failed to send admin menu message after edit failure: {send_e}")
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup)

    return ADMIN_MAIN_MENU

# --- إدارة المجموعات والأسرار (ConversationHandler) --- #
async def manage_groups_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="grp_add")],
    ]
    if groups_data:
        keyboard.append([InlineKeyboardButton("✏️ تعديل/حذف مجموعة", callback_data="grp_edit_select")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="إدارة المجموعات والأسرار:", reply_markup=reply_markup)
    return SELECTING_GROUP_ACTION

async def ask_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="يرجى إرسال معرف المجموعة (Group ID) الذي يبدأ بـ '-' (مثال: -100123456789).")
    return ASKING_GROUP_ID

async def receive_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id_str = update.message.text.strip()
    if not is_valid_group_id(group_id_str):
        await update.message.reply_text("المعرف غير صالح. يجب أن يبدأ بـ '-' ويحتوي على أرقام فقط. يرجى المحاولة مرة أخرى.")
        return ASKING_GROUP_ID
    if group_id_str in groups_data:
        await update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة التعديل.")
        # Simulate callback to go back to menu
        dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
        dummy_update = Update(update.update_id, callback_query=dummy_query)
        return await manage_groups_entry(dummy_update, context)
    context.user_data["current_group_id"] = group_id_str
    await update.message.reply_text("تم استلام معرف المجموعة. الآن يرجى إرسال مفتاح TOTP السري (TOTP Secret) لهذه المجموعة.")
    return ASKING_TOTP_SECRET

async def receive_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("current_group_id")
    if not group_id_str:
        await update.message.reply_text("خطأ. يرجى البدء من جديد.")
        await admin_command(update, context)
        return ConversationHandler.END
    if not is_valid_totp_secret(totp_secret):
        await update.message.reply_text("المفتاح السري غير صالح (يجب أن يكون بتنسيق Base32). يرجى المحاولة مرة أخرى.")
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
    await update.message.reply_text(f"✅ تم إضافة المجموعة {group_id_str} بنجاح! سيتم إرسال رسالة الزر للمجموعة الآن.")
    # Send the initial message to the group
    await send_or_update_group_message(context, group_id_str)
    # Simulate callback to go back to menu
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    return await manage_groups_entry(dummy_update, context)

async def select_group_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة.")
        return await manage_groups_entry(update, context)
    for group_id in groups_data:
        title = await get_group_title(context, "group_id")
        keyboard.append([(f"{title} ({group_id})", callback_data="callback_data=f"grp_select_{group_id}")])
    keyboard.append(["Back"])
    async def back_to_group_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return manage_groups

async def select_edit_action(update: str) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["selected_group_id"] = group_id_str
    context.user_data["selected"] = group_id
    if group_id_str not in groups_data:
        query.edit_message_text("خطأ: المجموعة لم يعد موجودة.")
        return await select_group_to_edit(update, context)
    title = await get_group_title(context, group_id_str)
    keyboard = [
        [Inline Edit("🔑 تعديل المفتاح السري (TOTP)", callback_data="callback_data=f"grp_edit_secret_{group_id}"})],
        [InlineKeyboardButton("🗑️ حذف المجموعة", callback_data=f"grp_delete_confirm_group_id_str")],
        [InlineKeyboardButton("🔙 العودة لاختيار مجموعة"", callback_data="grp_edit_select" callback="="edit_select")],
    ]
    reply_markup = Inline ReplyKeyboardMarkup(keyboard)
    await query.edit_message_text(f"إدارة المجموعة: {title} ({group_id_str})", reply_markup="reply_markup=reply_markup")
    return SELECTING_EDIT

async def ask_new_totp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = context.user_data.get("selected_group_id"')
    if not group_id_str or group_id_str not in groups_data:
        await query.edit_message_text("خطأ: لم يتم تحديد مجموعة صالحة.")
        return await select_group_to_edit(update, context)
    title = await get_group_title(context, group_id)
    group_id_str)
    await query.edit_message_text(f"يرجى إرسال مفتاح TOTP السري الجديد الجديد للمجموعة {title} ({group_id}).")
    return ASKING_NEW_TOTP

async def receive_new_totp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("selected_group_id")
    if not group_id_str or or group_id_str not in groups_data:
        await update.message.reply_text("حدث خطأ ما. يرجى البدء من جديد.")
        await admin_command(update, context)
        return ConversationHandler.END
    if not is_valid_totp_secret(new_totp_secret):
        await update.message.reply_text("المفتاح السري الجديد غيريد. حاول مرة أخرى.")
        return ASKING_NEW_TOTP
    groups_data[group_id_str]["totp_secret"] = new_totp_secret
    save_json(GROUPSS_FILE, groups_data)
    context.user_data.pop("selected_group_id", None)
    await update.message.reply_text(f"✅ تم تحديث المفتاح السري للمجموعة {group_id_str} بنجاح!")
    # Simulate callback to go back to menu
    dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
    dummy_update = Update(update.update_id, callback_query=dummy_query)
    return await manage_groups_entry(dummy_update, context)

async def confirm_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = query.data.split("_")[-1]
    context.user_data["group_to_delete"] = group_id_str
    if not group_id_str in groups_data:
        await query.edit_message_text("خطأ: المجموعة لم يعد موجودة.")
        return await select_group_to_edit(update, context)
    title = await get_group_title(context, group_id_str)
    keyboard = [
        [InlineKeyboardButton("✅ نعم، حذف", callback_data=f"grp_delete_yes_{group_id_str}")],
        [InlineKeyboardButton("❌ لا, إلغاء", callback_data=f"grp_delete_no_{group_id_str}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"⚠️ هل أنت متأكد من حذف المجموعة {title} ({group_id_str})؟", reply_markup=reply_markup)
    return CONFIRMING_DELETE

async def execute_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = context.user_data.get("group_to_delete")
    if not group_id_str or group_id_str not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        context.user_data.pop("group_to_delete", None)
        return await select_group_to_edit(update, context)

    # Try to delete the message in the group first
    message_id = groups_data[group_id_str].get("message_id")
    if message_id:
        try:
            await context.bot.delete_message(chat_id=group_id_str, message_id=message_id)
            logger.info(f"Deleted message {message_id} from group {group_id_str} before deleting group data.")
        except Exception as e:
            logger.warning(f"Could not delete message {message_id} from group {group_id_str} during group deletion: {e}")

    del groups_data[group_id_str]
    save_json(GROUPS_FILE, groups_data)
    context.user_data.pop("group_to_delete", None)
    await query.edit_message_text(f"🗑️ تم حذف المجموعة {group_id_str}.")
    return await manage_groups_entry(update, context)

async def cancel_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("group_to_delete", None)
    group_id_str = context.user_data.get("selected_group_id")
    if not group_id_str or group_id_str not in groups_data:
        await query.edit_message_text("تم إلغاء الحذف.")
        return await select_group_to_edit(update, context)
    # Reconstruct callback data to go back to edit action selection
    query.data = f"grp_select_{group_id_str}"
    return await select_edit_action(update, context)

async def back_to_group_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("selected_group_id", None)
    context.user_data.pop("group_to_delete", None)
    return await manage_groups_entry(update, context)

async def back_to_admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    admin_update = Update(update.update_id, callback_query=query)
    return await admin_command(admin_update, context)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    msg_text = "تم إلغاء العملية."
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(msg_text)
        except Exception as e:
            logger.warning(f"Failed to edit message on cancel: {e}")
            # Send new message if edit fails
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text=msg_text)
            except Exception as send_e:
                logger.error(f"Failed to send cancel message after edit failure: {send_e}")
        # Go back to admin menu after cancelling
        admin_update = Update(update.update_id, callback_query=query)
        return await admin_command(admin_update, context)
    elif update.message:
        await update.message.reply_text(msg_text)
        admin_update = Update(update.update_id, message=update.message)
        return await admin_command(admin_update, context)
    return ConversationHandler.END  # Fallback

# --- إدارة محاولات المستخدمين (ConversationHandler) --- #
async def manage_attempts_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not user_attempts:
        await query.edit_message_text(
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
    await query.edit_message_text(text="إدارة محاولات المستخدمين: اختر مستخدماً", reply_markup=reply_markup)
    return SELECTING_USER_FOR_ATTEMPTS

async def select_attempt_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id_str = query.data.split("_")[-1]
    context.user_data["selected_user_id"] = user_id_str
    if user_id_str not in user_attempts:
        await query.edit_message_text("خطأ: المستخدم لم يعد موجوداً.")
        return await manage_attempts_entry(update, context)
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
    await query.edit_message_text(f"إدارة المستخدم: {name} ({user_id_str})\nمحاولات متبقية: {attempts}", reply_markup=reply_markup)
    return SELECTING_ATTEMPTS_ACTION

async def toggle_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id_str = context.user_data.get("selected_user_id")
    action = query.data.split("_")[1]  # ban or unban
    if not user_id_str or user_id_str not in user_attempts:
        await query.edit_message_text("خطأ: لم يتم العثور على المستخدم.")
        return await manage_attempts_entry(update, context)
    should_ban = (action == "ban")
    user_attempts[user_id_str]["banned"] = should_ban
    save_json(ATTEMPTS_FILE, user_attempts)
    status_message = "محظور" if should_ban else "غير محظور"
    await query.edit_message_text(f"✅ تم تحديث حالة المستخدم {user_id_str}. الحالة الآن: {status_message}")
    query.data = f"att_select_user_{user_id_str}"
    return await select_attempt_action(update, context)

async def ask_attempts_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id_str = context.user_data.get("selected_user_id")
    action = query.data.split("_")[1]  # add or remove
    context.user_data["attempt_action"] = action
    if not user_id_str or user_id_str not in user_attempts:
        await query.edit_message_text("خطأ: لم يتم العثور على المستخدم.")
        return await manage_attempts_entry(update, context)
    prompt = "إضافة" if action == "add" else "حذف"
    await query.edit_message_text(f"كم عدد المحاولات التي تريد {prompt}ها للمستخدم {user_id_str}؟ يرجى إرسال رقم.")
    return ASKING_ATTEMPTS_NUMBER_ADD if action == "add" else ASKING_ATTEMPTS_NUMBER_REMOVE

async def receive_attempts_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        num_attempts = int(update.message.text.strip())
        if num_attempts <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح موجب.")
        action = context.user_data.get("attempt_action")
        return ASKING_ATTEMPTS_NUMBER_ADD if action == "add" else ASKING_ATTEMPTS_NUMBER_REMOVE
    user_id_str = context.user_data.get("selected_user_id")
    action = context.user_data.get("attempt_action")
    if not user_id_str or user_id_str not in user_attempts or not action:
        await update.message.reply_text("حدث خطأ ما. يرجى البدء من جديد.")
        context.user_data.clear()
        await admin_command(update, context)
        return ConversationHandler.END
    current_attempts = user_attempts[user_id_str].get("attempts_left", 0)
    if action == "add":
        user_attempts[user_id_str]["attempts_left"] = current_attempts + num_attempts
        result_verb = "إضافة"
    elif action == "remove":
        user_attempts[user_id_str]["attempts_left"] = max(0, current_attempts - num_attempts)
        result_verb = "حذف"
    else:
        await update.message.reply_text("حدث خطأ غير متوقع في تحديد الإجراء.")
        context.user_data.clear()
        await admin_command(update, context)
        return ConversationHandler.END
    save_json(ATTEMPTS)
    save_json(ATTEMPTS_FILE, user_attempts)
    try:
        new_attempts = user_attempts[user_id_str]["attempts_left"]
        await update.message.reply_text(f"✅ تم {result_verb} {num_attempts} محاولة للمستخدم {user_id_str}}. الرصيد الحالي: {new_attempts}")
    except Exception as e:
        logger.error(f"Failed to send reply for attempts update: {e}")
    context.user_data.pop("attempt_action", None)
        # Send new message if edit fails
        try:
            # Simulate callback to go back to id
    user_id_str
            dummy_query = MagicMock(); dummy_query.message = update.message; dummy_query.from_user = update.effective_user; dummy_query.data = f"att_select_user_{user_id_str}"; dummy_query.answer = lambda: None; dummy_query.edit_message_text = update.message.reply_text
            dummy_update = Update(update.update_id, callback_query=dummy_query)
            return await select_attempt_action(dummy_update, context)
        except Exception as send_e:
            logger.error(f"Failed to send message after edit failure: {send_e}")
            return ConversationHandler.END

# --- إدارة الفاصل الزمني (للعرض) والتفعيل (ConversationHandler) --- #
async def manage_interval_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = []
    if not groups_data:
        await query.edit_message_text(
            query.edit_message_text(
                "لا توجد مجموعات مضافة لإدارة إعداداتها.",
                text="لا يوجدددد مجموعات مضافة لزعداداتها.",
                reply_markup=ReplyKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="admin_back" callback="="admin_back")]])
            return ADMIN_MAIN_MENU
        )
    for group_id in groups_data:
        title = await get_group_title(context, group_id)
    except Exception as e:
        logger.warning(f"Error in manage_interval_entry: {group_id}: {e}")
    keyboard.append(f"[{title}] ({group_id}): ({callback_data=f"interval_select_grp_{group_id}"})]
        keyboard.append(["Back to main menu"])
        keyboard.append(InlineKeyboardButton("🔙", callback_data="admin_back")) callback_data))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("إدارة الفاصل الزمني/التفعيل: اختر مجموعة", reply_markup=reply_markup)

    return SELECTING_GROUP_FOR_INTERVAL

async def select_interval_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = query.data.split("_")[-1]["-1]
    context.user_data["selected_group_id"] = group_id_str
    group_id_str
    if group_id_str not in groups_data:
        await query.edit_message_text("خطأ: المجموعة لم يعد يتم العودة للمجموعة.")
        return await manage_interval_entry(update, context)

    settings = groups_data[group_id]["settings"].get("settings", {})
    groups_data[group_id]["settings"] = settings.get("group_settings", {})
    current_interval = settings.get("interval", global_settings["default_interval"])
    interval = settings.get("_interval", global_settings["default_interval"])["interval"])
    is_enabled = settings.get("enabled", True)
    enabled = settings.get("settings.get", Trueenabled)
    title = get_group_title(context, group_id_str)
    keyboard.append(["[]])
    interval_buttons = []
    for name, seconds in AVAILABLE_INTERVALS.items():
        prefix = "✅ " if seconds == current_interval else ""
        interval_buttons.append(("f"{prefix}{name}", callback_data=f"interval_set_{seconds}" callback="f"interval)))
        interval_buttons.append(InlineKeyboardButton(f"[{prefix}]{name}", callback_data=f"interval_set_{seconds}"]))
    for i in range(0, len(interval_buttons), 2)):
        keyboard.append(interval_buttons[i:i+2])
    enable_text = "🟢 تفعيل النسخ" if not is_enabled else "🔴 تعطيل الألطط"
        enable_text = "enable" if not enabled else "disable"
    enable_callback = f"interval_{enable_text}_{group_id}" callback_data=f"interval_{id_str}" enable_callback
    keyboard.append(f"[{enable_text}]" callback_data=enable_callback)
])
    keyboard.append(["Back to group selection"])
    keyboard.append(InlineKeyboardButton("🔙", callback_data="interval_manage")) callback_data=manage_interval))
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_interval_desc = next((k for k, v in AVAILABLE_INTERVALS.items() if v == current_interval), for k in v AVAILABLE_INTERVALS.items() if v == interval_current_interval), f"next {current_interval} ثانية")
    status_desc = "مفعل" if is_enabled else "."
    status = "enabled" if is_enabled else "disabled"
    await query.edit_message_text(
        (
            f"إعدادات المجموعة: {title} ({group_id_str})\n\n"
            f"الحالة الحالية: {status_desc}: {status}"
            f"الفاصل المني (للعرضللعرض): {current_interval_desc}\n\n\n"
            f"Choose new interval or change status:"
            "اختر الفاصل الزمني الجديد أو قم يتغيير حالة التفعيل:"
        ),
        reply_markup=reply_text_reply_markup
    )
    return SELECTING_INTERVAL_ACTION

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    group_id_str = context.user_data.get("selected_group_id")
    try:
        new_interval = int(query.data.split("_")[-1])
        try:
            new_group_interval = int(query.data.split("_")[1])
        except (IndexError, ValueError):
            logger.error(f"Error parsing interval data: {query.data}")
            await query.edit_message_text("خطأ في بيانات الفاصل الزمنيثة.")
            return await manage_interval_entry(update, context)
    except ValueError:
        logger.error(f"Invalid interval value: {query.data}")
        await query.edit_message_text("خطأ في بيانات الفاصلة الزمني.")
        return await manage_interval_entry(update, context)
    if not group_id_str or or group_id_str not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        return await manage_interval_entry(update, context)
    groups_data[group_id]["settings"]["interval"] = new_interval
    groups_data[group_id_str]["settings"]["interval"] = new_group_interval
    save_json(GROUPS_FILE, groups_data)
    await query

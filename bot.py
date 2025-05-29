# -*- coding: utf-8 -*- M2.6
"""
Telegram Bot (ChatGPTPlus2FABot) for managing and providing 2FA TOTP codes.

Handles admin controls for groups, secrets, message formats, user attempts,
and manual message sending (as scheduled tasks are disabled).
"""

import logging
import json
import os
import pyotp
import pytz
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    PicklePersistence # Using PicklePersistence for context
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

# --- Constants --- 
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
BOT_NAME = "ChatGPTPlus2FABot"
CONFIG_FILE = "config.json"
GROUPS_FILE = "groups.json"
USER_ATTEMPTS_FILE = "user_attempts.json"
PERSISTENCE_FILE = "bot_persistence.pickle"

# Initial Admin ID (Can be expanded via Manage Admins feature)
INITIAL_ADMIN_ID = 764559466

# Conversation states
(SELECTING_ACTION, 
 # Group Management
 MANAGE_GROUPS_MENU, ADD_GROUP_ID, ADD_GROUP_SECRET, 
 DELETE_GROUP_SELECT, DELETE_GROUP_CONFIRM, 
 EDIT_GROUP_SELECT, EDIT_GROUP_OPTION, EDIT_GROUP_NEW_ID, EDIT_GROUP_NEW_SECRET,
 # Manual Send
 MANUAL_SEND_SELECT_GROUP,
 # Format Management
 MANAGE_FORMAT_SELECT_GROUP, SET_FORMAT, SET_TIMEZONE,
 # Attempts Management
 MANAGE_ATTEMPTS_SELECT_GROUP, MANAGE_ATTEMPTS_SELECT_USER, MANAGE_ATTEMPTS_ACTION, 
 ADD_ATTEMPTS_COUNT, REMOVE_ATTEMPTS_COUNT,
 # Admin Management
 MANAGE_ADMINS_MENU, ADD_ADMIN_ID, DELETE_ADMIN_SELECT
) = range(23)

# --- Logging Setup --- 
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Data Handling Functions --- 
def load_json(filename, default_data=None):
    """Loads data from a JSON file. Creates the file with default data if it doesn't exist."""
    if not os.path.exists(filename):
        if default_data is None:
            default_data = {}
        save_json(filename, default_data)
        logger.info(f"Created default data file: {filename}")
        return default_data
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Handle empty file case
            content = f.read()
            if not content:
                return default_data if default_data is not None else {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading {filename}: {e}. Returning default data.")
        # Attempt to save default data if file was corrupted/empty
        if default_data is not None:
             save_json(filename, default_data)
        return default_data if default_data is not None else {}
    except Exception as e:
        logger.error(f"Unexpected error loading {filename}: {e}")
        return default_data if default_data is not None else {}

def save_json(filename, data):
    """Saves data to a JSON file."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Error saving {filename}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving {filename}: {e}")

# --- Load Initial Data --- 
config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
groups_data = load_json(GROUPS_FILE, {})
user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})

# --- Helper Functions --- 
def is_admin(user_id):
    """Checks if a user ID belongs to an admin."""
    # Reload config_data in case admins were added/removed
    current_config = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    return user_id in current_config.get("admins", [])

def get_totp_code(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        return None
    try:
        # Ensure secret is base32 padded correctly
        secret = secret.upper()
        padding = len(secret) % 8
        if padding != 0:
            secret += '=' * (8 - padding)
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        logger.error(f"Error generating TOTP code (Secret: {secret[:4]}...): {e}")
        return None

def format_group_message(group_id_str):
    """Formats the message to be sent to the group based on its settings."""
    group_info = groups_data.get(group_id_str)
    if not group_info:
        return "Error: Group configuration not found."

    message_format = group_info.get("message_format", 1)
    interval_minutes = group_info.get("interval") # Can be None or 0 if stopped
    timezone_str = group_info.get("timezone", "GMT")
    
    try:
        # Handle common timezone variations
        if timezone_str.upper() == "GAZA":
            tz = pytz.timezone("Asia/Gaza")
        elif timezone_str.upper() == "GMT":
             tz = pytz.timezone("Etc/GMT")
        else:
            tz = pytz.timezone(timezone_str) # Try direct name
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone 	'{timezone_str}	', defaulting to GMT.")
        tz = pytz.timezone("Etc/GMT") # Use Etc/GMT for standard GMT

    now = datetime.now(tz)
    next_code_time_str = "(غير محدد)"
    next_code_in_str = "(غير محدد)"

    if interval_minutes and interval_minutes > 0:
        try:
            # Calculate next interval boundary based on UTC for consistency
            now_utc = datetime.now(pytz.utc)
            interval_seconds = interval_minutes * 60
            timestamp_now = now_utc.timestamp()
            
            # Find the start of the current interval slot in UTC
            seconds_into_day = (timestamp_now % 86400) # Seconds since UTC midnight
            current_interval_start_offset = (seconds_into_day // interval_seconds) * interval_seconds
            
            # Calculate the start time of the next interval slot in UTC
            next_interval_start_offset = current_interval_start_offset + interval_seconds
            
            # Convert the next interval start time back to a datetime object in UTC
            today_utc_midnight = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            next_interval_start_utc = today_utc_midnight + timedelta(seconds=next_interval_start_offset)

            # If the calculated next time is in the past (e.g., just crossed midnight), add a day
            if next_interval_start_utc <= now_utc:
                 next_interval_start_utc += timedelta(days=1)
                 # Recalculate offset for the next day
                 next_interval_start_offset = (next_interval_start_utc.timestamp() % 86400)
                 next_interval_start_utc = today_utc_midnight.replace(day=now_utc.day +1) + timedelta(seconds=(next_interval_start_offset % interval_seconds))
                 # This part needs refinement for cross-day calculations, simpler approach below:
            
            # Simpler approach: Add interval to current time, then floor to interval boundary?
            # Let's stick to the display logic based on local time for simplicity, as requested.
            current_minute = now.minute
            minutes_past_interval = current_minute % interval_minutes
            minutes_to_next_interval = interval_minutes - minutes_past_interval
            next_code_time_local = now + timedelta(minutes=minutes_to_next_interval)
            next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            # Handle edge case where calculation lands exactly on the current minute
            if next_code_time_local <= now:
                 next_code_time_local += timedelta(minutes=interval_minutes)
                 next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            next_code_time_str = next_code_time_local.strftime("%I:%M:%S %p %Z") # 12-hour format with timezone
            next_code_in_str = f"{interval_minutes} دقيقة"
        except Exception as e:
            logger.error(f"Error calculating next code time for group {group_id_str}: {e}")
            next_code_time_str = "(خطأ في الحساب)"
            next_code_in_str = "(خطأ)"
    else:
        next_code_time_str = "(التكرار متوقف)"
        next_code_in_str = "(متوقف)"

    correct_time_str = now.strftime("%I:%M:%S %p %Z")

    # Use MarkdownV2 for formatting, escape special characters
    def escape_md(text):
        escape_chars = '_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

    message = f"🔐 *{escape_md('رمز التحقق الثنائي (2FA)')}*\n\n"

    if message_format == 1:
        message += f"{escape_md(':الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    elif message_format == 2:
        message += f"{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*\n"
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    elif message_format == 3:
        message += f"{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*\n"
        message += f"{escape_md('الوقت الحالي')}: *{escape_md(correct_time_str)}*\n"
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    else: # Default to format 1 if invalid
        message += f"{escape_md(':الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
        
    return message

async def send_or_edit_group_message(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Sends a new message to the group or edits the last one if possible."""
    group_info = groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"Attempted to send message to non-existent group config: {group_id_str}")
        return

    message_text = format_group_message(group_id_str)
    keyboard = [[InlineKeyboardButton("🔑 نسخ الرمز (Copy Code)", callback_data=f"copy_code_{group_id_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    last_message_id = group_info.get("last_message_id")
    
    try:
        # Try editing first if we have a last message ID
        if last_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=int(group_id_str),
                    message_id=last_message_id,
                    text=message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                logger.info(f"Edited message {last_message_id} in group {group_id_str}")
                return # Success editing
            except BadRequest as e:
                # Common errors: message not found, message can't be edited, message is identical
                logger.warning(f"Failed to edit message {last_message_id} in group {group_id_str}: {e}. Sending new message.")
                # Fall through to sending a new message
            except TelegramError as e:
                logger.error(f"Telegram error editing message {last_message_id} in group {group_id_str}: {e}")
                # Fall through to sending a new message, maybe clear last_message_id?
                group_info["last_message_id"] = None 
                
        # Send a new message if editing failed or no last_message_id
        sent_message = await context.bot.send_message(
            chat_id=int(group_id_str),
            text=message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        # Update last_message_id
        groups_data[group_id_str]["last_message_id"] = sent_message.message_id
        save_json(GROUPS_FILE, groups_data)
        logger.info(f"Sent new message {sent_message.message_id} to group {group_id_str}")

        # Reset attempts for all users in this group upon sending a new message
        if group_id_str in user_attempts_data:
            default_attempts = config_data.get("default_copy_attempts", 3)
            changed = False
            for user_id_str in user_attempts_data[group_id_str]:
                # Only reset if they are not banned
                if not user_attempts_data[group_id_str][user_id_str].get("is_banned", False):
                    if user_attempts_data[group_id_str][user_id_str].get("attempts_left") != default_attempts:
                         user_attempts_data[group_id_str][user_id_str]["attempts_left"] = default_attempts
                         changed = True
            if changed:
                save_json(USER_ATTEMPTS_FILE, user_attempts_data)
                logger.info(f"Reset attempts for users in group {group_id_str}")

    except TelegramError as e:
        logger.error(f"Failed to send/edit message in group {group_id_str}: {e}")
        # Possible errors: Bot kicked, chat not found, etc.
        # Consider removing the group or notifying the admin
    except ValueError:
         logger.error(f"Invalid group ID format for sending message: {group_id_str}")

# --- Command Handlers --- 
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        f"أهلاً بك في بوت {BOT_NAME}!\n"
        f"اضغط على زر 'Copy Code' في رسائل المجموعة للحصول على رمز 2FA الخاص بك.\n"
        f"إذا كنت مسؤولاً، استخدم الأمر /admin لإدارة الإعدادات."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /admin command and shows the main admin menu."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("⚙️ إدارة المجموعات/الأسرار", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("📨 إرسال رسالة التحديث يدوياً", callback_data="admin_manual_send")],
        [InlineKeyboardButton("📝 إدارة شكل الرسالة/التوقيت", callback_data="admin_manage_format")],
        [InlineKeyboardButton("👤 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("⏱️ إدارة فترة التكرار (للعرض فقط)", callback_data="admin_manage_interval")], # Added for setting interval display
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Check if message exists to edit, otherwise send new
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("القائمة الرئيسية للمسؤول:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("لوحة تحكم المسؤول:", reply_markup=reply_markup)
        
    return SELECTING_ACTION

# --- Callback Query Handlers --- 
async def copy_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Copy Code' button press."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user_id = query.from_user.id
    user_name = query.from_user.full_name
    try:
        group_id_str = query.data.split('_', 2)[-1]
        if not group_id_str.startswith('-'):
             raise ValueError("Invalid group ID format")
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing group_id from callback_data '{query.data}': {e}")
        # Maybe notify user in PM? 
        try:
            await context.bot.send_message(user_id, "حدث خطأ داخلي. يرجى المحاولة مرة أخرى أو إبلاغ المسؤول.")
        except TelegramError as te:
             logger.error(f"Failed to send error message to user {user_id}: {te}")
        return

    logger.info(f"User {user_name} ({user_id}) requested code for group {group_id_str}")

    # --- Checks --- 
    if group_id_str not in groups_data:
        logger.warning(f"Attempt to get code for non-configured group {group_id_str} by user {user_id}")
        await context.bot.send_message(user_id, "لم يتم العثور على إعدادات لهذه المجموعة.")
        return

    # Initialize user data if needed
    if group_id_str not in user_attempts_data:
        user_attempts_data[group_id_str] = {}
    if str(user_id) not in user_attempts_data[group_id_str]:
        user_attempts_data[group_id_str][str(user_id)] = {
            "attempts_left": config_data.get("default_copy_attempts", 3),
            "is_banned": False
        }
        save_json(USER_ATTEMPTS_FILE, user_attempts_data)
        logger.info(f"Initialized attempts for user {user_id} in group {group_id_str}")

    user_data = user_attempts_data[group_id_str][str(user_id)]

    if user_data.get("is_banned", False):
        logger.info(f"Denied code request for banned user {user_id} in group {group_id_str}")
        await context.bot.send_message(user_id, "عذراً، لقد تم حظرك من الحصول على الرمز لهذه المجموعة.")
        return

    attempts_left = user_data.get("attempts_left", 0)
    if attempts_left <= 0:
        logger.info(f"Denied code request for user {user_id} (no attempts left) in group {group_id_str}")
        await context.bot.send_message(user_id, "عذراً، لقد استنفدت محاولاتك للحصول على الرمز. يرجى التواصل مع المسؤول.")
        return

    # --- Generate and Send --- 
    secret = groups_data[group_id_str].get("totp_secret")
    if not secret:
        logger.error(f"Missing TOTP secret for group {group_id_str}")
        await context.bot.send_message(user_id, "خطأ: لم يتم تعيين المفتاح السري لهذه المجموعة. يرجى إبلاغ المسؤول.")
        return

    totp_code = get_totp_code(secret)
    if not totp_code:
        await context.bot.send_message(user_id, "حدث خطأ أثناء توليد الرمز. يرجى المحاولة مرة أخرى أو إبلاغ المسؤول.")
        return

    # Decrement attempts and save
    user_data["attempts_left"] = attempts_left - 1
    save_json(USER_ATTEMPTS_FILE, user_attempts_dat    try:
        # Use MarkdownV2 - ensure message is escaped properly
        def escape_md(text):
             escape_chars = '_*[]()~`>#+-=|{}.!'
             return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

        escaped_code = escape_md(totp_code)
        escaped_attempts = escape_md(user_data['attempts_left'])
        
        response_message_md = (
            f"🔑 {escape_md('رمز التحقق الخاص بك:')}\n`{escaped_code}`\n\n"
            f"⚠️ *{escape_md('هذا الرمز صالح لمدة 30 ثانية فقط.')}*\n"
            f"📉 {escape_md('المحاولات المتبقية:')} {escaped_attempts}"
        )

        await context.bot.send_message(user_id, response_message_md, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Sent code to user {user_id} for group {group_id_str}. Attempts left: {user_data['attempts_left']}")
    except TelegramError as e:
        logger.error(f"Failed to send code to user {user_id}: {e}")
        # Revert attempt count if sending failed?
        user_data["attempts_left"] = attempts_left
        save_json(USER_ATTEMPTS_FILE, user_attempts_data)
        logger.info(f"Reverted attempt count for user {user_id} due to send failure.")

# --- Admin Conversation Handlers --- 

# --- General Admin Callbacks --- 
async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current admin operation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية.")
    context.user_data.clear() # Clear any temporary data
    return ConversationHandler.END

async def admin_back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns to the main admin menu."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear() # Clear any temporary data
    # Re-display the main menu by calling the entry point function
    await admin_command(update, context)
    return SELECTING_ACTION # Go back to the initial state

# --- Manage Groups --- 
async def admin_manage_groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the menu for managing groups."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="groups_add")],
        [InlineKeyboardButton("✏️ تعديل مجموعة موجودة", callback_data="groups_edit")],
        [InlineKeyboardButton("➖ حذف مجموعة موجودة", callback_data="groups_delete")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("إدارة المجموعات والأسرار:", reply_markup=reply_markup)
    return MANAGE_GROUPS_MENU

async def groups_add_prompt_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the new group ID."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال رقم معرّف المجموعة الخاصة (Group ID). يجب أن يبدأ بـ '-'.")
    return ADD_GROUP_ID

async def groups_add_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the group ID and prompts for the secret."""
    group_id_str = update.message.text.strip()
    if not group_id_str.startswith('-') or not group_id_str[1:].isdigit():
        await update.message.reply_text("المعرّف غير صالح. يجب أن يكون رقماً ويبدأ بـ '-'. الرجاء المحاولة مرة أخرى أو /cancel للإلغاء.")
        return ADD_GROUP_ID # Stay in the same state

    if group_id_str in groups_data:
        await update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها أو حذفها من القائمة. /cancel للإلغاء.")
        return ADD_GROUP_ID

    context.user_data['new_group_id'] = group_id_str
    await update.message.reply_text("تم استلام معرّف المجموعة. الآن الرجاء إرسال المفتاح السري TOTP (TOTP_SECRET) لهذه المجموعة.")
    return ADD_GROUP_SECRET

async def groups_add_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the secret, saves the new group, and returns to main menu."""
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get('new_group_id')

    if not group_id_str or not totp_secret:
        await update.message.reply_text("حدث خطأ ما. الرجاء البدء من جديد عبر /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Basic validation for TOTP secret (alphanumeric, maybe length?)
    # pyotp typically uses base32 (A-Z, 2-7)
    if not re.match(r'^[A-Z2-7=]+$', totp_secret.upper()):
         logger.warning(f"Invalid TOTP secret format provided: {totp_secret}")
         # Don't necessarily reject, pyotp might handle some variations, but warn admin
         await update.message.reply_text("⚠️ تحذير: صيغة المفتاح السري قد تكون غير قياسية (عادةً أحرف كبيرة وأرقام 2-7). سيتم حفظه كما هو.")

    groups_data[group_id_str] = {
        "totp_secret": totp_secret,
        "interval": 10, # Default interval
        "message_format": 1, # Default format
        "timezone": "GMT", # Default timezone
        "job_id": None, # Not used currently
        "last_message_id": None
    }
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {update.effective_user.id} added group {group_id_str}")
    await update.message.reply_text(f"✅ تم إضافة المجموعة {group_id_str} بنجاح.")
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

async def groups_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups to delete."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لحذفها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]])) 
        return MANAGE_GROUPS_MENU
        
    for group_id in groups_data:
        # Try to get group title/name? Might require bot being in the group.
        # For now, just use the ID.
        buttons.append([InlineKeyboardButton(f"🗑️ حذف المجموعة {group_id}", callback_data=f"delgroup_{group_id}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
    return DELETE_GROUP_SELECT

async def groups_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting."""
    query = update.callback_query
    await query.answer()
    group_id_to_delete = query.data.split('_', 1)[1]
    context.user_data['group_to_delete'] = group_id_to_delete
    
    keyboard = [
        [InlineKeyboardButton(f"✅ نعم، حذف {group_id_to_delete}", callback_data="delete_confirm_yes")],
        [InlineKeyboardButton("❌ لا، إلغاء", callback_data="delete_confirm_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"هل أنت متأكد أنك تريد حذف المجموعة {group_id_to_delete} وجميع بياناتها المرتبطة (مثل محاولات المستخدمين)؟", reply_markup=reply_markup)
    return DELETE_GROUP_CONFIRM

async def groups_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes the deletion or cancels."""
    query = update.callback_query
    await query.answer()
    group_id_to_delete = context.user_data.get('group_to_delete')

    if query.data == "delete_confirm_yes":
        if group_id_to_delete and group_id_to_delete in groups_data:
            del groups_data[group_id_to_delete]
            save_json(GROUPS_FILE, groups_data)
            # Also remove from user attempts
            if group_id_to_delete in user_attempts_data:
                del user_attempts_data[group_id_to_delete]
                save_json(USER_ATTEMPTS_FILE, user_attempts_data)
            logger.info(f"Admin {query.from_user.id} deleted group {group_id_to_delete}")
            await query.edit_message_text(f"🗑️ تم حذف المجموعة {group_id_to_delete} بنجاح.")
        else:
            await query.edit_message_text("خطأ: لم يتم العثور على المجموعة أو حدث خطأ ما.")
    else:
        await query.edit_message_text("تم إلغاء الحذف.")

    context.user_data.clear()
    # Go back to group management menu
    await admin_manage_groups_menu(update, context)
    return MANAGE_GROUPS_MENU

async def groups_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups to edit."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لتعديلها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]])) 
        return MANAGE_GROUPS_MENU
        
    for group_id in groups_data:
        buttons.append([InlineKeyboardButton(f"✏️ تعديل المجموعة {group_id}", callback_data=f"editgroup_{group_id}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة التي تريد تعديلها:", reply_markup=reply_markup)
    return EDIT_GROUP_SELECT

async def groups_edit_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows options for editing a selected group."""
    query = update.callback_query
    await query.answer()
    group_id_to_edit = query.data.split('_', 1)[1]
    context.user_data['group_to_edit'] = group_id_to_edit

    if group_id_to_edit not in groups_data:
         await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]])) 
         return MANAGE_GROUPS_MENU

    keyboard = [
        # [InlineKeyboardButton("تعديل معرّف المجموعة (ID)", callback_data="edit_option_id")], # Editing ID is complex, might break things. Usually delete/re-add.
        [InlineKeyboardButton("تعديل المفتاح السري (Secret)", callback_data="edit_option_secret")],
        [InlineKeyboardButton("🔙 رجوع لقائمة المجموعات", callback_data="groups_edit")] # Go back to group selection
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر ما تريد تعديله للمجموعة {group_id_to_edit}:", reply_markup=reply_markup)
    return EDIT_GROUP_OPTION

async def groups_edit_prompt_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the new secret."""
    query = update.callback_query
    await query.answer()
    group_id_to_edit = context.user_data.get('group_to_edit')
    if not group_id_to_edit:
        # Handle error, maybe go back to main menu
        await query.edit_message_text("خطأ: لم يتم تحديد مجموعة للتعديل.")
        return ConversationHandler.END
        
    await query.edit_message_text(f"الرجاء إرسال المفتاح السري TOTP الجديد للمجموعة {group_id_to_edit}.")
    return EDIT_GROUP_NEW_SECRET

async def groups_edit_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and saves the new secret."""
    new_secret = update.message.text.strip()
    group_id_to_edit = context.user_data.get('group_to_edit')

    if not group_id_to_edit or not new_secret:
        await update.message.reply_text("حدث خطأ ما. الرجاء البدء من جديد عبر /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    if group_id_to_edit not in groups_data:
         await update.message.reply_text("خطأ: لم يتم العثور على المجموعة.")
         context.user_data.clear()
         await admin_command(update, context)
         return SELECTING_ACTION

    # Basic validation for TOTP secret
    if not re.match(r'^[A-Z2-7=]+$', new_secret.upper()):
         logger.warning(f"Invalid TOTP secret format provided for edit: {new_secret}")
         await update.message.reply_text("⚠️ تحذير: صيغة المفتاح السري قد تكون غير قياسية. سيتم حفظه كما هو.")

    groups_data[group_id_to_edit]["totp_secret"] = new_secret
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {update.effective_user.id} updated secret for group {group_id_to_edit}")
    await update.message.reply_text(f"✅ تم تحديث المفتاح السري للمجموعة {group_id_to_edit} بنجاح.")
    
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Manual Send --- 
async def manual_send_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups to send manual update message."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لإرسال رسالة لها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        return SELECTING_ACTION
        
    for group_id in groups_data:
        buttons.append([InlineKeyboardButton(f"📨 إرسال إلى {group_id}", callback_data=f"manualsend_{group_id}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة لإرسال رسالة التحديث اليدوية:", reply_markup=reply_markup)
    return MANUAL_SEND_SELECT_GROUP

async def manual_send_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the manual message to the selected group."""
    query = update.callback_query
    await query.answer()
    group_id_to_send = query.data.split('_', 1)[1]

    if group_id_to_send not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
    else:
        await query.edit_message_text(f"⏳ جارٍ إرسال الرسالة إلى {group_id_to_send}...")
        await send_or_edit_group_message(context, group_id_to_send)
        await query.edit_message_text(f"✅ تم إرسال/تحديث الرسالة بنجاح إلى {group_id_to_send}.")
        logger.info(f"Admin {query.from_user.id} manually sent update to group {group_id_to_send}")

    # Go back to main menu after a short delay or directly?
    # Let's go back directly for now.
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Manage Format/Timezone --- 
async def manage_format_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups to manage format/timezone."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لإدارة تنسيقها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        return SELECTING_ACTION
        
    for group_id, group_info in groups_data.items():
        current_format = group_info.get('message_format', 1)
        current_tz = group_info.get('timezone', 'GMT')
        buttons.append([InlineKeyboardButton(f"{group_id} (F:{current_format}, TZ:{current_tz})", callback_data=f"setformat_{group_id}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة لتعديل شكل الرسالة والتوقيت:", reply_markup=reply_markup)
    return MANAGE_FORMAT_SELECT_GROUP

async def set_format_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows format options for the selected group."""
    query = update.callback_query
    await query.answer()
    group_id_to_format = query.data.split('_', 1)[1]
    context.user_data['group_to_format'] = group_id_to_format

    if group_id_to_format not in groups_data:
         await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_format")]])) 
         return SELECTING_ACTION # Or back to format group selection?

    current_format = groups_data[group_id_to_format].get('message_format', 1)
    
    keyboard = [
        [InlineKeyboardButton(f"الشكل 1 {'✅' if current_format == 1 else ''}", callback_data="format_1")],
        [InlineKeyboardButton(f"الشكل 2 {'✅' if current_format == 2 else ''}", callback_data="format_2")],
        [InlineKeyboardButton(f"الشكل 3 {'✅' if current_format == 3 else ''}", callback_data="format_3")],
        [InlineKeyboardButton("🔙 رجوع لاختيار المجموعة", callback_data="admin_manage_format")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر شكل الرسالة للمجموعة {group_id_to_format}:\n" 
                              f"1: الرمز التالي في: TIME\n"
                              f"2: التالي خلال: X min | التالي في: TIME\n"
                              f"3: التالي خلال: X min | الحالي: TIME | التالي في: TIME", 
                              reply_markup=reply_markup)
    return SET_FORMAT

async def set_timezone_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected format and shows timezone options."""
    query = update.callback_query
    await query.answer()
    selected_format = int(query.data.split('_', 1)[1])
    group_id_to_format = context.user_data.get('group_to_format')

    if not group_id_to_format or group_id_to_format not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        context.user_data.clear()
        await admin_command(update, context)
        return SELECTING_ACTION

    # Save the format temporarily
    context.user_data['selected_format'] = selected_format
    
    current_tz = groups_data[group_id_to_format].get('timezone', 'GMT')

    keyboard = [
        [InlineKeyboardButton(f"توقيت غرينتش (GMT) {'✅' if current_tz.upper() == 'GMT' else ''}", callback_data="timezone_GMT")],
        [InlineKeyboardButton(f"توقيت غزة (Gaza) {'✅' if current_tz.upper() == 'GAZA' else ''}", callback_data="timezone_Gaza")],
        [InlineKeyboardButton("🔙 رجوع لاختيار الشكل", callback_data=f"setformat_{group_id_to_format}")] # Go back to format selection
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر المنطقة الزمنية لعرض الوقت للمجموعة {group_id_to_format}:", reply_markup=reply_markup)
    return SET_TIMEZONE

async def save_format_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected timezone and format."""
    query = update.callback_query
    await query.answer()
    selected_timezone = query.data.split('_', 1)[1]
    group_id_to_format = context.user_data.get('group_to_format')
    selected_format = context.user_data.get('selected_format')

    if not group_id_to_format or group_id_to_format not in groups_data or selected_format is None:
        await query.edit_message_text("خطأ: بيانات غير مكتملة.")
        context.user_data.clear()
        await admin_command(update, context)
        return SELECTING_ACTION

    groups_data[group_id_to_format]['message_format'] = selected_format
    groups_data[group_id_to_format]['timezone'] = selected_timezone
    save_json(GROUPS_FILE, groups_data)
    logger.info(f"Admin {query.from_user.id} updated format to {selected_format} and timezone to {selected_timezone} for group {group_id_to_format}")
    await query.edit_message_text(f"✅ تم تحديث شكل الرسالة والمنطقة الزمنية للمجموعة {group_id_to_format} بنجاح.")

    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Manage Interval (Display Only) --- 
async def manage_interval_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups to manage interval setting."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لإدارة فترة تكرارها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        return SELECTING_ACTION
        
    for group_id, group_info in groups_data.items():
        interval = group_info.get('interval')
        interval_text = f"{interval} دقيقة" if interval else "متوقف"
        buttons.append([InlineKeyboardButton(f"{group_id} ({interval_text})", callback_data=f"setinterval_{group_id}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة لتحديد فترة تكرار عرض الوقت (لا يؤثر على الإرسال الفعلي حالياً):", reply_markup=reply_markup)
    return SET_INTERVAL # Reusing state name, maybe rename?

async def set_interval_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows interval options for the selected group."""
    query = update.callback_query
    await query.answer()
    group_id_to_set = query.data.split('_', 1)[1]
    context.user_data['group_to_set_interval'] = group_id_to_set

    if group_id_to_set not in groups_data:
         await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]])) 
         return SELECTING_ACTION

    current_interval = groups_data[group_id_to_set].get('interval')
    intervals = [1, 5, 10, 15, 30, 60]
    keyboard = []
    row = []
    for i in intervals:
        button = InlineKeyboardButton(f"{i} دقيقة {'✅' if current_interval == i else ''}", callback_data=f"interval_{i}")
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: # Add remaining button if odd number
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton(f"⏹️ إيقاف التكرار {'✅' if not current_interval else ''}", callback_data="interval_0")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار المجموعة", callback_data="admin_manage_interval")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر فترة تكرار عرض الوقت للمجموعة {group_id_to_set}:", reply_markup=reply_markup)
    return SET_INTERVAL # Stay in this state to receive interval choice

async def save_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected interval."""
    query = update.callback_query
    await query.answer()
    selected_interval = int(query.data.split('_', 1)[1])
    group_id_to_set = context.user_data.get('group_to_set_interval')

    if not group_id_to_set or group_id_to_set not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة.")
        context.user_data.clear()
        await admin_command(update, context)
        return SELECTING_ACTION

    groups_data[group_id_to_set]['interval'] = selected_interval if selected_interval > 0 else None
    save_json(GROUPS_FILE, groups_data)
    interval_text = f"{selected_interval} دقيقة" if selected_interval > 0 else "متوقف"
    logger.info(f"Admin {query.from_user.id} updated interval to {interval_text} for group {group_id_to_set}")
    await query.edit_message_text(f"✅ تم تحديث فترة تكرار عرض الوقت للمجموعة {group_id_to_set} إلى {interval_text}.")

    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Manage User Attempts --- 
async def manage_attempts_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of groups where users have attempts data."""
    query = update.callback_query
    await query.answer()
    buttons = []
    if not user_attempts_data:
        await query.edit_message_text("لا يوجد مستخدمون تفاعلوا مع أي مجموعة حتى الآن.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        return SELECTING_ACTION
        
    for group_id in user_attempts_data:
        # Check if group still exists in groups_data
        if group_id in groups_data:
             user_count = len(user_attempts_data[group_id])
             buttons.append([InlineKeyboardButton(f"{group_id} ({user_count} مستخدم)", callback_data=f"attemptsgroup_{group_id}")])
        else:
            # Clean up orphaned user attempts data? Or just ignore?
            logger.warning(f"Found user attempts data for deleted group {group_id}. Ignoring.")
            
    if not buttons: # If all groups were orphaned
         await query.edit_message_text("لا يوجد مستخدمون تفاعلوا مع أي مجموعة نشطة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
         return SELECTING_ACTION
         
    buttons.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المجموعة لإدارة محاولات المستخدمين:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_SELECT_GROUP

async def manage_attempts_select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of users within the selected group."""
    query = update.callback_query
    await query.answer()
    group_id_for_attempts = query.data.split('_', 1)[1]
    context.user_data['group_for_attempts'] = group_id_for_attempts

    if group_id_for_attempts not in user_attempts_data or not user_attempts_data[group_id_for_attempts]:
        await query.edit_message_text("لا يوجد مستخدمون في هذه المجموعة أو لم يتفاعلوا بعد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار المجموعة", callback_data="admin_manage_attempts")]])) 
        return MANAGE_ATTEMPTS_SELECT_GROUP

    buttons = []
    user_list = user_attempts_data[group_id_for_attempts]
    # Try to fetch user names (can be slow/fail if bot hasn't seen user recently)
    for user_id_str, data in user_list.items():
        user_id = int(user_id_str)
        display_name = f"User ID: {user_id}"
        try:
            # This might fail if the bot can't access the user info
            chat_member = await context.bot.get_chat_member(chat_id=group_id_for_attempts, user_id=user_id) 
            display_name = chat_member.user.full_name or f"User ID: {user_id}"
        except TelegramError as e:
            logger.warning(f"Could not fetch user info for {user_id} in group {group_id_for_attempts}: {e}")
            # Fallback to ID if name fetch fails
            try:
                 user = await context.bot.get_chat(user_id) # Try getting user directly
                 display_name = user.full_name or f"User ID: {user_id}"
            except TelegramError:
                 display_name = f"User ID: {user_id}" # Final fallback

        attempts = data.get('attempts_left', 0)
        banned = data.get('is_banned', False)
        status = "(محظور)" if banned else f"({attempts} محاولات)"
        buttons.append([InlineKeyboardButton(f"{display_name} {status}", callback_data=f"attemptsuser_{user_id_str}")])
        
    buttons.append([InlineKeyboardButton("🔙 رجوع لاختيار المجموعة", callback_data="admin_manage_attempts")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(f"اختر المستخدم في المجموعة {group_id_for_attempts}:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_SELECT_USER

async def manage_attempts_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows actions for the selected user."""
    query = update.callback_query
    await query.answer()
    user_id_str_for_action = query.data.split('_', 1)[1]
    group_id_for_attempts = context.user_data.get('group_for_attempts')
    context.user_data['user_for_action'] = user_id_str_for_action

    if not group_id_for_attempts or group_id_for_attempts not in user_attempts_data or user_id_str_for_action not in user_attempts_data[group_id_for_attempts]:
        await query.edit_message_text("خطأ: لم يتم العثور على المستخدم أو المجموعة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_attempts")]])) 
        return MANAGE_ATTEMPTS_SELECT_GROUP

    user_data = user_attempts_data[group_id_for_attempts][user_id_str_for_action]
    is_banned = user_data.get('is_banned', False)
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data="attempts_action_add")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data="attempts_action_remove")],
        [InlineKeyboardButton(f"{'✅ إلغاء حظر' if is_banned else '🚫 حظر'} المستخدم", callback_data="attempts_action_ban_toggle")],
        [InlineKeyboardButton("🔙 رجوع لاختيار المستخدم", callback_data=f"attemptsgroup_{group_id_for_attempts}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر الإجراء للمستخدم {user_id_str_for_action} في المجموعة {group_id_for_attempts}:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_ACTION

async def attempts_action_ban_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the ban status for the selected user."""
    query = update.callback_query
    await query.answer()
    group_id = context.user_data.get('group_for_attempts')
    user_id_str = context.user_data.get('user_for_action')

    if not group_id or not user_id_str or group_id not in user_attempts_data or user_id_str not in user_attempts_data[group_id]:
        await query.edit_message_text("خطأ: بيانات غير مكتملة.")
        # Go back to user selection?
        await manage_attempts_select_user(update, context) # This might fail if group_id is missing
        return MANAGE_ATTEMPTS_SELECT_USER

    user_data = user_attempts_data[group_id][user_id_str]
    current_ban_status = user_data.get('is_banned', False)
    user_data['is_banned'] = not current_ban_status
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    
    action_text = "حظر" if not current_ban_status else "إلغاء حظر"
    logger.info(f"Admin {query.from_user.id} toggled ban ({action_text}) for user {user_id_str} in group {group_id}")
    await query.edit_message_text(f"✅ تم {action_text} المستخدم {user_id_str} بنجاح.")

    # Go back to the action menu for the same user
    await manage_attempts_action(update, context)
    return MANAGE_ATTEMPTS_ACTION

async def attempts_action_prompt_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the number of attempts to add."""
    query = update.callback_query
    await query.answer()
    group_id = context.user_data.get('group_for_attempts')
    user_id_str = context.user_data.get('user_for_action')
    await query.edit_message_text(f"كم عدد المحاولات التي تريد إضافتها للمستخدم {user_id_str} في المجموعة {group_id}؟ أرسل رقماً.")
    return ADD_ATTEMPTS_COUNT

async def attempts_action_receive_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the number and adds attempts."""
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            raise ValueError("Count must be positive")
    except ValueError:
        await update.message.reply_text("الرجاء إرسال رقم صحيح موجب. /cancel للإلغاء.")
        return ADD_ATTEMPTS_COUNT

    group_id = context.user_data.get('group_for_attempts')
    user_id_str = context.user_data.get('user_for_action')

    if not group_id or not user_id_str or group_id not in user_attempts_data or user_id_str not in user_attempts_data[group_id]:
        await update.message.reply_text("خطأ: بيانات غير مكتملة. ابدأ من /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    user_data = user_attempts_data[group_id][user_id_str]
    user_data['attempts_left'] = user_data.get('attempts_left', 0) + count
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    logger.info(f"Admin {update.effective_user.id} added {count} attempts for user {user_id_str} in group {group_id}. New total: {user_data['attempts_left']}")
    await update.message.reply_text(f"✅ تم إضافة {count} محاولات. الرصيد الحالي: {user_data['attempts_left']}.")

    # Go back to the action menu for the same user
    # Need to simulate a callback query to go back cleanly
    # Or just end and ask admin to start over?
    # Let's end for simplicity now.
    context.user_data.clear()
    await admin_command(update, context)
    return SELECTING_ACTION

async def attempts_action_prompt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the number of attempts to remove."""
    query = update.callback_query
    await query.answer()
    group_id = context.user_data.get('group_for_attempts')
    user_id_str = context.user_data.get('user_for_action')
    current_attempts = user_attempts_data.get(group_id, {}).get(user_id_str, {}).get('attempts_left', 0)
    await query.edit_message_text(f"كم عدد المحاولات التي تريد حذفها من المستخدم {user_id_str} في المجموعة {group_id}؟ (الحالي: {current_attempts}). أرسل رقماً.")
    return REMOVE_ATTEMPTS_COUNT

async def attempts_action_receive_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the number and removes attempts."""
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            raise ValueError("Count must be positive")
    except ValueError:
        await update.message.reply_text("الرجاء إرسال رقم صحيح موجب. /cancel للإلغاء.")
        return REMOVE_ATTEMPTS_COUNT

    group_id = context.user_data.get('group_for_attempts')
    user_id_str = context.user_data.get('user_for_action')

    if not group_id or not user_id_str or group_id not in user_attempts_data or user_id_str not in user_attempts_data[group_id]:
        await update.message.reply_text("خطأ: بيانات غير مكتملة. ابدأ من /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    user_data = user_attempts_data[group_id][user_id_str]
    current_attempts = user_data.get('attempts_left', 0)
    user_data['attempts_left'] = max(0, current_attempts - count) # Ensure it doesn't go below 0
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    logger.info(f"Admin {update.effective_user.id} removed {count} attempts from user {user_id_str} in group {group_id}. New total: {user_data['attempts_left']}")
    await update.message.reply_text(f"✅ تم حذف {count} محاولات. الرصيد الحالي: {user_data['attempts_left']}.")

    context.user_data.clear()
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Manage Admins --- 
async def manage_admins_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the menu for managing admins."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admins_add")],
        [InlineKeyboardButton("➖ حذف مسؤول", callback_data="admins_delete")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # Reload config to show current admins
    current_config = load_json(CONFIG_FILE)
    admin_list = "\n".join([f"- `{admin_id}`" for admin_id in current_config.get("admins", [])])
    await query.edit_message_text(f"إدارة المسؤولين:\n*المسؤولون الحاليون:*\n{admin_list}", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_ADMINS_MENU

async def admins_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the new admin's user ID."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال معرّف المستخدم (User ID) للمسؤول الجديد.")
    return ADD_ADMIN_ID

async def admins_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the user ID and adds the admin."""
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("المعرّف غير صالح. يجب أن يكون رقماً. الرجاء المحاولة مرة أخرى أو /cancel للإلغاء.")
        return ADD_ADMIN_ID

    # Reload config data before modifying
    current_config = load_json(CONFIG_FILE)
    if new_admin_id in current_config.get("admins", []):
        await update.message.reply_text("هذا المستخدم هو مسؤول بالفعل.")
    else:
        current_config.setdefault("admins", []).append(new_admin_id)
        save_json(CONFIG_FILE, current_config)
        # Update in-memory config_data as well
        config_data["admins"] = current_config["admins"]
        logger.info(f"Admin {update.effective_user.id} added new admin {new_admin_id}")
        await update.message.reply_text(f"✅ تم إضافة المسؤول {new_admin_id} بنجاح.")

    # Go back to admin management menu
    # Need to simulate callback query
    await admin_command(update, context) # Go back to main menu for now
    return SELECTING_ACTION

async def admins_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows list of admins to delete."""
    query = update.callback_query
    await query.answer()
    current_config = load_json(CONFIG_FILE)
    admins = current_config.get("admins", [])
    current_admin_id = query.from_user.id
    buttons = []
    
    # Filter out the initial admin and the current admin performing the action
    deletable_admins = [admin for admin in admins if admin != INITIAL_ADMIN_ID and admin != current_admin_id]

    if not deletable_admins:
        await query.edit_message_text("لا يوجد مسؤولون آخرون يمكن حذفهم.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]])) 
        return MANAGE_ADMINS_MENU
        
    for admin_id in deletable_admins:
        # Try to get admin name? Might be difficult/slow
        buttons.append([InlineKeyboardButton(f"🗑️ حذف المسؤول {admin_id}", callback_data=f"deladmin_{admin_id}")])
        
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("اختر المسؤول الذي تريد حذفه (لا يمكنك حذف المسؤول الأولي أو نفسك):", reply_markup=reply_markup)
    return DELETE_ADMIN_SELECT

async def admins_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the selected admin."""
    query = update.callback_query
    await query.answer()
    try:
        admin_id_to_delete = int(query.data.split('_', 1)[1])
    except (IndexError, ValueError):
        await query.edit_message_text("خطأ: معرّف غير صالح.")
        await manage_admins_menu(update, context)
        return MANAGE_ADMINS_MENU

    current_config = load_json(CONFIG_FILE)
    admins = current_config.get("admins", [])
    current_admin_id = query.from_user.id

    if admin_id_to_delete == INITIAL_ADMIN_ID or admin_id_to_delete == current_admin_id:
         await query.edit_message_text("لا يمكنك حذف المسؤول الأولي أو نفسك.")
    elif admin_id_to_delete in admins:
        admins.remove(admin_id_to_delete)
        current_config["admins"] = admins
        save_json(CONFIG_FILE, current_config)
        # Update in-memory config_data
        config_data["admins"] = admins
        logger.info(f"Admin {current_admin_id} deleted admin {admin_id_to_delete}")
        await query.edit_message_text(f"🗑️ تم حذف المسؤول {admin_id_to_delete} بنجاح.")
    else:
        await query.edit_message_text("خطأ: لم يتم العثور على المسؤول.")

    # Go back to admin management menu
    await manage_admins_menu(update, context)
    return MANAGE_ADMINS_MENU

# --- Fallback and Error Handlers --- 
async def text_fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles unexpected text messages during conversations."""
    user_id = update.effective_user.id
    state = context.user_data.get('state') # Need to get state if using default context
    logger.warning(f"Received unexpected text from user {user_id} in state {state}: {update.message.text}")
    await update.message.reply_text("أنا في انتظار رد محدد (مثل الضغط على زر أو إرسال معلومة مطلوبة). استخدم /cancel للخروج من العملية الحالية.")
    # Return the current state to avoid breaking the conversation
    # This requires knowing the current state, which is tricky without explicit state passing
    # For now, just returning None might break things. Best to rely on /cancel.
    return None # Or return the expected state if known

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    # Optionally inform user about the error
    if isinstance(update, Update) and update.effective_user:
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id, 
                text="حدث خطأ غير متوقع أثناء معالجة طلبك. تم تسجيل الخطأ. يرجى المحاولة مرة أخرى لاحقاً أو استخدام /cancel."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- Main Function --- 
def main():
    """Start the bot."""
    # Use persistence to store conversation states across restarts
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).job_queue(None).build()

    # --- Conversation Handler for Admin tasks --- 
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(admin_manage_groups_menu, pattern="^admin_manage_groups$"),
                CallbackQueryHandler(manual_send_select_group, pattern="^admin_manual_send$"),
                CallbackQueryHandler(manage_format_select_group, pattern="^admin_manage_format$"),
                CallbackQueryHandler(manage_attempts_select_group, pattern="^admin_manage_attempts$"),
                CallbackQueryHandler(manage_admins_menu, pattern="^admin_manage_admins$"),
                CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"), # Interval display mgmt
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"), # Go back to main menu
            ],
            # Group Management States
            MANAGE_GROUPS_MENU: [
                CallbackQueryHandler(groups_add_prompt_id, pattern="^groups_add$"),
                CallbackQueryHandler(groups_edit_select, pattern="^groups_edit$"),
                CallbackQueryHandler(groups_delete_select, pattern="^groups_delete$"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            ADD_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_add_receive_id)],
            ADD_GROUP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_add_receive_secret)],
            DELETE_GROUP_SELECT: [
                CallbackQueryHandler(groups_delete_confirm, pattern="^delgroup_"),
                CallbackQueryHandler(admin_manage_groups_menu, pattern="^admin_back_groups_menu$"),
            ],
            DELETE_GROUP_CONFIRM: [
                CallbackQueryHandler(groups_delete_execute, pattern="^delete_confirm_(yes|no)$"),
            ],
            EDIT_GROUP_SELECT: [
                CallbackQueryHandler(groups_edit_option, pattern="^editgroup_"),
                CallbackQueryHandler(admin_manage_groups_menu, pattern="^admin_back_groups_menu$"),
            ],
            EDIT_GROUP_OPTION: [
                # CallbackQueryHandler(groups_edit_prompt_id, pattern="^edit_option_id$"), # ID edit disabled
                CallbackQueryHandler(groups_edit_prompt_secret, pattern="^edit_option_secret$"),
                CallbackQueryHandler(groups_edit_select, pattern="^groups_edit$"), # Back to group selection
            ],
            # EDIT_GROUP_NEW_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_edit_receive_id)],
            EDIT_GROUP_NEW_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_edit_receive_secret)],
            # Manual Send States
            MANUAL_SEND_SELECT_GROUP: [
                CallbackQueryHandler(manual_send_execute, pattern="^manualsend_"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            # Format/Timezone States
            MANAGE_FORMAT_SELECT_GROUP: [
                CallbackQueryHandler(set_format_options, pattern="^setformat_"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            SET_FORMAT: [
                CallbackQueryHandler(set_timezone_options, pattern="^format_[1-3]$"),
                CallbackQueryHandler(manage_format_select_group, pattern="^admin_manage_format$"), # Back
            ],
            SET_TIMEZONE: [
                CallbackQueryHandler(save_format_timezone, pattern="^timezone_(GMT|Gaza)$"),
                CallbackQueryHandler(set_format_options, pattern="^setformat_"), # Back to format selection (needs group_id)
                # Need a way to go back properly here, maybe store group_id in callback?
                # For now, going back might require re-selecting group.
            ],
             # Interval States
            SET_INTERVAL: [
                 CallbackQueryHandler(save_interval, pattern="^interval_\d+$"),
                 CallbackQueryHandler(set_interval_options, pattern="^setinterval_"), # Back to interval options (needs group_id)
                 CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"), # Back to group selection
            ],
            # Attempts Management States
            MANAGE_ATTEMPTS_SELECT_GROUP: [
                CallbackQueryHandler(manage_attempts_select_user, pattern="^attemptsgroup_"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            MANAGE_ATTEMPTS_SELECT_USER: [
                CallbackQueryHandler(manage_attempts_action, pattern="^attemptsuser_"),
                CallbackQueryHandler(manage_attempts_select_group, pattern="^admin_manage_attempts$"), # Back
            ],
            MANAGE_ATTEMPTS_ACTION: [
                CallbackQueryHandler(attempts_action_prompt_add, pattern="^attempts_action_add$"),
                CallbackQueryHandler(attempts_action_prompt_remove, pattern="^attempts_action_remove$"),
                CallbackQueryHandler(attempts_action_ban_toggle, pattern="^attempts_action_ban_toggle$"),
                CallbackQueryHandler(manage_attempts_select_user, pattern="^attemptsgroup_"), # Back (needs group_id)
            ],
            ADD_ATTEMPTS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, attempts_action_receive_add)],
            REMOVE_ATTEMPTS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, attempts_action_receive_remove)],
            # Admin Management States
            MANAGE_ADMINS_MENU: [
                CallbackQueryHandler(admins_add_prompt, pattern="^admins_add$"),
                CallbackQueryHandler(admins_delete_select, pattern="^admins_delete$"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admins_add_receive)],
            DELETE_ADMIN_SELECT: [
                CallbackQueryHandler(admins_delete_execute, pattern="^deladmin_"),
                CallbackQueryHandler(manage_admins_menu, pattern="^admin_manage_admins$"), # Back
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel), # Allow /cancel command globally within conversation
            CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"), # Cancel button
            CallbackQueryHandler(admin_command, pattern="^admin_back_main$"), # Back to main menu button
            # Add fallbacks for specific back buttons if needed
            CommandHandler("admin", admin_command), # Restart admin flow if /admin is used again
            # MessageHandler(filters.COMMAND, unknown_command_handler), # Handle unknown commands?
            # MessageHandler(filters.TEXT, text_fallback_handler) # Catch unexpected text - might interfere
        ],
        per_user=True,
        per_chat=False, # Conversation is private with the admin
        persistent=True, # Use persistence
        name="admin_conversation" # Name for persistence
    )

    # --- Handlers --- 
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(admin_conv_handler)
    # Ensure copy_code handler doesn't interfere with conversation
    application.add_handler(CallbackQueryHandler(copy_code_callback, pattern="^copy_code_"))
    
    # Error Handler
    application.add_error_handler(error_handler)

    # Set bot commands
    async def post_init(app: Application):
        try:
            await app.bot.set_my_commands([
                BotCommand("start", "بدء استخدام البوت"),
                BotCommand("admin", "لوحة تحكم المسؤول (للمسؤولين فقط)")
            ])
            logger.info("Bot commands set successfully.")
        except TelegramError as e:
            logger.error(f"Failed to set bot commands: {e}")

    application.post_init = post_init

    # Run the bot
    logger.info(f"Starting bot {BOT_NAME}...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Ensure data directories exist
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(GROUPS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(USER_ATTEMPTS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(PERSISTENCE_FILE), exist_ok=True)
    main()



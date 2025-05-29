# -*- coding: utf-8 -*- M2.66
"""
Telegram Bot (ChatGPTPlus2FABot) for managing and providing 2FA TOTP codes.

Handles admin controls for groups, secrets, message formats, user attempts,
admin management, and periodic message scheduling.
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
    PicklePersistence, # Using PicklePersistence for context
    JobQueue # Import JobQueue if needed for specific configuration
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
DEFAULT_INTERVAL_MINUTES = 10 # Default interval when adding a group

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
 MANAGE_ADMINS_MENU, ADD_ADMIN_ID, DELETE_ADMIN_SELECT,
 # Interval Management
 MANAGE_INTERVAL_SELECT_GROUP, SET_INTERVAL_OPTIONS, SET_INTERVAL # Added SET_INTERVAL_OPTIONS
) = range(25) # Increased range to 25

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
            content = f.read()
            if not content:
                return default_data if default_data is not None else {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading {filename}: {e}. Returning default data.")
        if default_data is not None:
             save_json(filename, default_data)
        return default_data if default_data is not None else {}
    except Exception as e:
        logger.error(f"Unexpected error loading {filename}: {e}")
        return default_data if default_data is not None else {}

def save_json(filename, data):
    """Saves data to a JSON file."""
    try:
        dir_name = os.path.dirname(filename)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
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
    current_config = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    return user_id in current_config.get("admins", [])

def get_totp_code(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        return None
    try:
        secret = secret.upper()
        padding = len(secret) % 8
        if padding != 0:
            secret += '=' * (8 - padding)
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        logger.error(f"Error generating TOTP code (Secret: {secret[:4]}...): {e}")
        return None

def escape_md(text):
    """Escapes special characters for MarkdownV2."""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def format_group_message(group_id_str):
    """Formats the message to be sent to the group based on its settings."""
    group_info = groups_data.get(group_id_str)
    if not group_info:
        return "Error: Group configuration not found."

    message_format = group_info.get("message_format", 1)
    interval_minutes = group_info.get("interval")
    timezone_str = group_info.get("timezone", "GMT")
    
    try:
        if timezone_str.upper() == "GAZA":
            tz = pytz.timezone("Asia/Gaza")
        elif timezone_str.upper() == "GMT":
             tz = pytz.timezone("Etc/GMT")
        else:
            tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{timezone_str}', defaulting to GMT.")
        tz = pytz.timezone("Etc/GMT")

    now = datetime.now(tz)
    next_code_time_str = "(غير محدد)"
    next_code_in_str = "(غير محدد)"

    if interval_minutes and isinstance(interval_minutes, int) and interval_minutes > 0:
        try:
            current_minute = now.minute
            minutes_past_interval = current_minute % interval_minutes
            minutes_to_next_interval = interval_minutes - minutes_past_interval
            next_code_time_local = now + timedelta(minutes=minutes_to_next_interval)
            next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            if next_code_time_local <= now:
                 next_code_time_local += timedelta(minutes=interval_minutes)
                 next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            next_code_time_str = next_code_time_local.strftime("%I:%M:%S %p %Z")
            next_code_in_str = f"{interval_minutes} دقيقة"
        except Exception as e:
            logger.error(f"Error calculating next code time for group {group_id_str}: {e}")
            next_code_time_str = "(خطأ في الحساب)"
            next_code_in_str = "(خطأ)"
    else:
        next_code_time_str = "(التكرار متوقف)"
        next_code_in_str = "(متوقف)"

    correct_time_str = now.strftime("%I:%M:%S %p %Z")

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
    else:
        message += f"{escape_md(':الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
        
    return message

async def send_or_edit_group_message(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Sends a new message to the group or edits the last one if possible. Also resets attempts."""
    group_info = groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"Attempted to send message to non-existent group config: {group_id_str}")
        return

    message_text = format_group_message(group_id_str)
    keyboard = [[InlineKeyboardButton("🔑 نسخ الرمز (Copy Code)", callback_data=f"copy_code_{group_id_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    last_message_id = group_info.get("last_message_id")
    message_sent_or_edited = False
    
    try:
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
                message_sent_or_edited = True
            except BadRequest as e:
                logger.warning(f"Failed to edit message {last_message_id} in group {group_id_str}: {e}. Sending new message.")
                group_info["last_message_id"] = None # Force sending new message
            except TelegramError as e:
                logger.error(f"Telegram error editing message {last_message_id} in group {group_id_str}: {e}")
                group_info["last_message_id"] = None 
                
        if not message_sent_or_edited:
            sent_message = await context.bot.send_message(
                chat_id=int(group_id_str),
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            groups_data[group_id_str]["last_message_id"] = sent_message.message_id
            save_json(GROUPS_FILE, groups_data)
            logger.info(f"Sent new message {sent_message.message_id} to group {group_id_str}")
            message_sent_or_edited = True

        # Reset attempts only if a message was successfully sent or edited
        if message_sent_or_edited:
            global user_attempts_data
            user_attempts_data = load_json(USER_ATTEMPTS_FILE, {}) # Reload data
            if group_id_str in user_attempts_data:
                default_attempts = config_data.get("default_copy_attempts", 3)
                changed = False
                for user_id_str in list(user_attempts_data[group_id_str].keys()): # Iterate over keys copy
                    if not user_attempts_data[group_id_str][user_id_str].get("is_banned", False):
                        if user_attempts_data[group_id_str][user_id_str].get("attempts_left") != default_attempts:
                             user_attempts_data[group_id_str][user_id_str]["attempts_left"] = default_attempts
                             changed = True
                if changed:
                    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
                    logger.info(f"Reset attempts for users in group {group_id_str}")

    except TelegramError as e:
        logger.error(f"Failed to send/edit message in group {group_id_str}: {e}")
        # If bot is blocked or kicked, stop the job for this group
        if "bot was blocked" in str(e) or "chat not found" in str(e) or "bot was kicked" in str(e):
             logger.warning(f"Bot seems blocked/kicked from group {group_id_str}. Removing job.")
             remove_group_message_job(context, group_id_str)
             # Optionally remove group from config?
             if group_id_str in groups_data:
                 groups_data[group_id_str]["interval"] = 0 # Mark as inactive
                 groups_data[group_id_str]["last_message_id"] = None
                 save_json(GROUPS_FILE, groups_data)
    except ValueError:
         logger.error(f"Invalid group ID format for sending message: {group_id_str}")
    except Exception as e:
        logger.error(f"Unexpected error in send_or_edit_group_message for {group_id_str}: {e}")

# --- Job Queue Functions --- 
async def periodic_group_message_callback(context: ContextTypes.DEFAULT_TYPE):
    """Callback function for the scheduled group message job."""
    job = context.job
    group_id_str = job.data.get("group_id")
    if not group_id_str:
        logger.error(f"Job {job.name} is missing group_id in data.")
        return

    logger.info(f"Running scheduled job {job.name} for group {group_id_str}")
    # Reload group data in case it changed
    global groups_data
    groups_data = load_json(GROUPS_FILE, {}) 
    # Check if group still exists and has an interval
    group_info = groups_data.get(group_id_str)
    if not group_info or not group_info.get("interval") or group_info.get("interval") <= 0:
        logger.warning(f"Group {group_id_str} not found or interval disabled. Removing job {job.name}.")
        remove_group_message_job(context, group_id_str) # Remove the job itself
        return
        
    await send_or_edit_group_message(context, group_id_str)

def remove_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Removes the scheduled message job for a group."""
    if not context.job_queue:
        logger.warning("JobQueue not available, cannot remove jobs.")
        return
    job_name = f"group_msg_{group_id_str}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        # logger.info(f"No active job found for group {group_id_str} to remove.")
        return
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Removed scheduled job {job_name} for group {group_id_str}")

def schedule_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str, interval_minutes: int):
    """Schedules or updates the periodic message job for a group."""
    if not context.job_queue:
        logger.error("JobQueue not available, cannot schedule jobs.")
        return
        
    job_name = f"group_msg_{group_id_str}"
    # Remove existing job first
    remove_group_message_job(context, group_id_str)

    if interval_minutes > 0:
        try:
            # Use run_repeating for periodic tasks
            context.job_queue.run_repeating(
                periodic_group_message_callback,
                interval=timedelta(minutes=interval_minutes),
                # first=timedelta(seconds=5), # Start after 5 seconds
                first=0, # Start immediately
                name=job_name,
                data={"group_id": group_id_str}
            )
            logger.info(f"Scheduled job {job_name} for group {group_id_str} with interval {interval_minutes} minutes.")
        except Exception as e:
             logger.error(f"Failed to schedule job for group {group_id_str}: {e}")
    else:
         logger.info(f"Interval is 0 or less for group {group_id_str}, job removed, no new job scheduled.")

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
        # Check if it's a callback query from a non-admin
        if update.callback_query:
            await update.callback_query.answer("عذراً، هذه الأزرار للمسؤولين فقط.", show_alert=True)
            return ConversationHandler.END # End conversation for non-admins trying buttons
        else:
            await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
            return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("⚙️ إدارة المجموعات/الأسرار", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("📨 إرسال رسالة التحديث يدوياً", callback_data="admin_manual_send")],
        [InlineKeyboardButton("📝 إدارة شكل الرسالة/التوقيت", callback_data="admin_manage_format")],
        [InlineKeyboardButton("⏱️ إدارة فترة التكرار", callback_data="admin_manage_interval")], # Updated text
        [InlineKeyboardButton("👤 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "القائمة الرئيسية للمسؤول:"
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            if "message is not modified" in str(e):
                pass # Ignore if message is identical
            else:
                logger.error(f"Error editing admin menu: {e}")
                # If edit fails, maybe the original message was deleted, send new one
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        
    return SELECTING_ACTION

# --- Callback Query Handlers (Main Menu Selection) --- 
async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current admin operation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية.")
    # Clear conversation data if needed
    context.user_data.clear()
    return ConversationHandler.END

# --- Group Management Callbacks --- 
async def admin_manage_groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the group management menu."""
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
    """Prompts admin to enter the Group ID."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال رقم معرّف المجموعة (Group ID) التي تريد إضافتها.\n(يجب أن يبدأ بـ -100...)")
    return ADD_GROUP_ID

async def groups_add_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the Group ID and prompts for the TOTP Secret."""
    group_id_str = update.message.text.strip()
    # Basic validation
    if not group_id_str.startswith("-100") or not group_id_str[1:].isdigit():
        await update.message.reply_text("معرّف المجموعة غير صالح. يجب أن يبدأ بـ -100 ويحتوي على أرقام فقط بعد العلامة. الرجاء المحاولة مرة أخرى أو اضغط /cancel للإلغاء.")
        return ADD_GROUP_ID # Stay in the same state
        
    if group_id_str in groups_data:
         await update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة التعديل. /cancel للإلغاء.")
         return ADD_GROUP_ID

    context.user_data["new_group_id"] = group_id_str
    await update.message.reply_text("تم استلام معرّف المجموعة. الآن الرجاء إرسال المفتاح السري (TOTP_SECRET) الخاص بهذه المجموعة.")
    return ADD_GROUP_SECRET

async def groups_add_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the TOTP Secret and saves the new group."""
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("new_group_id")

    if not group_id_str:
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرّف المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END
        
    # Basic validation for TOTP secret (length, base32 chars) - can be improved
    if not re.match(r'^[A-Z2-7=]+$', totp_secret.upper()) or len(totp_secret) < 16:
        await update.message.reply_text("المفتاح السري (TOTP_SECRET) يبدو غير صالح. يجب أن يتكون من أحرف A-Z وأرقام 2-7. الرجاء المحاولة مرة أخرى أو اضغط /cancel للإلغاء.")
        return ADD_GROUP_SECRET

    # Save the new group data
    groups_data[group_id_str] = {
        "secret": totp_secret,
        "interval": DEFAULT_INTERVAL_MINUTES, # Set default interval
        "message_format": 1, # Default format
        "timezone": "GMT", # Default timezone
        "last_message_id": None
    }
    save_json(GROUPS_FILE, groups_data)
    
    # Schedule the job for the new group
    schedule_group_message_job(context, group_id_str, DEFAULT_INTERVAL_MINUTES)

    await update.message.reply_text(f"تم إضافة المجموعة {group_id_str} بنجاح مع فترة تكرار تلقائية {DEFAULT_INTERVAL_MINUTES} دقيقة.")
    context.user_data.clear()
    # Go back to the main admin menu automatically
    await admin_command(update, context)
    return SELECTING_ACTION

async def groups_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of groups to select for deletion."""
    query = update.callback_query
    await query.answer()
    
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]]))
        return MANAGE_GROUPS_MENU

    keyboard = []
    for group_id in groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"🗑️ {group_id}", callback_data=f"delgroup_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
    return DELETE_GROUP_SELECT

async def groups_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting a group."""
    query = update.callback_query
    group_id_to_delete = query.data.split("_", 1)[1]
    context.user_data["group_to_delete"] = group_id_to_delete
    
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("نعم، متأكد", callback_data="delete_confirm_yes")],
        [InlineKeyboardButton("لا، إلغاء", callback_data="delete_confirm_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"هل أنت متأكد من حذف المجموعة {group_id_to_delete}؟ سيتم حذف جميع إعداداتها.", reply_markup=reply_markup)
    return DELETE_GROUP_CONFIRM

async def groups_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes the group deletion or cancels it."""
    query = update.callback_query
    group_id_to_delete = context.user_data.get("group_to_delete")
    decision = query.data.split("_")[-1]

    await query.answer()

    if decision == "yes" and group_id_to_delete:
        if group_id_to_delete in groups_data:
            # Remove the scheduled job first
            remove_group_message_job(context, group_id_to_delete)
            
            del groups_data[group_id_to_delete]
            save_json(GROUPS_FILE, groups_data)
            # Also remove associated user attempts
            if group_id_to_delete in user_attempts_data:
                del user_attempts_data[group_id_to_delete]
                save_json(USER_ATTEMPTS_FILE, user_attempts_data)
            await query.edit_message_text(f"تم حذف المجموعة {group_id_to_delete} بنجاح.")
        else:
            await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
    else:
        await query.edit_message_text("تم إلغاء الحذف.")

    context.user_data.clear()
    # Go back to group management menu
    await admin_manage_groups_menu(update, context)
    return MANAGE_GROUPS_MENU

async def groups_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of groups to select for editing."""
    query = update.callback_query
    await query.answer()
    
    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]]))
        return MANAGE_GROUPS_MENU

    keyboard = []
    for group_id in groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"✏️ {group_id}", callback_data=f"editgroup_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد تعديلها:", reply_markup=reply_markup)
    return EDIT_GROUP_SELECT

async def groups_edit_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows options for editing a selected group (only secret)."""
    query = update.callback_query
    group_id_to_edit = query.data.split("_", 1)[1]
    context.user_data["group_to_edit"] = group_id_to_edit
    
    await query.answer()
    keyboard = [
        # [InlineKeyboardButton("تعديل معرّف المجموعة (ID)", callback_data="edit_option_id")], # Disabled ID editing
        [InlineKeyboardButton("تعديل المفتاح السري (Secret)", callback_data="edit_option_secret")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="groups_edit")] # Use callback to trigger previous state handler
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"تعديل المجموعة {group_id_to_edit}: اختر الحقل الذي تريد تعديله.", reply_markup=reply_markup)
    return EDIT_GROUP_OPTION

# Handler for editing ID (Currently disabled) 
# async def groups_edit_prompt_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     await query.edit_message_text("الرجاء إرسال معرّف المجموعة الجديد.")
#     return EDIT_GROUP_NEW_ID

# async def groups_edit_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     new_group_id = update.message.text.strip()
#     old_group_id = context.user_data.get("group_to_edit")
#     # Validation...
#     groups_data[new_group_id] = groups_data.pop(old_group_id)
#     save_json(GROUPS_FILE, groups_data)
#     # Update user attempts data key
#     if old_group_id in user_attempts_data:
#         user_attempts_data[new_group_id] = user_attempts_data.pop(old_group_id)
#         save_json(USER_ATTEMPTS_FILE, user_attempts_data)
#     await update.message.reply_text(f"تم تعديل معرّف المجموعة إلى {new_group_id}.")
#     context.user_data.clear()
#     await admin_manage_groups_menu(update, context)
#     return MANAGE_GROUPS_MENU

async def groups_edit_prompt_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the new TOTP Secret."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال المفتاح السري (TOTP_SECRET) الجديد.")
    return EDIT_GROUP_NEW_SECRET

async def groups_edit_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and saves the new TOTP Secret."""
    new_secret = update.message.text.strip()
    group_id_to_edit = context.user_data.get("group_to_edit")

    if not group_id_to_edit or group_id_to_edit not in groups_data:
        await update.message.reply_text("خطأ: لم يتم العثور على المجموعة المراد تعديلها. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END
        
    # Basic validation for TOTP secret
    if not re.match(r'^[A-Z2-7=]+$', new_secret.upper()) or len(new_secret) < 16:
        await update.message.reply_text("المفتاح السري (TOTP_SECRET) يبدو غير صالح. الرجاء المحاولة مرة أخرى أو اضغط /cancel للإلغاء.")
        return EDIT_GROUP_NEW_SECRET

    groups_data[group_id_to_edit]["secret"] = new_secret
    save_json(GROUPS_FILE, groups_data)
    await update.message.reply_text(f"تم تعديل المفتاح السري للمجموعة {group_id_to_edit} بنجاح.")
    context.user_data.clear()
    # Go back to group management menu
    # Need to simulate callback query for admin_manage_groups_menu
    # A bit hacky, maybe find a better way to return to menu state
    if update.callback_query:
         await admin_manage_groups_menu(update.callback_query, context)
    else: # Should not happen here as it follows a message handler
         await admin_command(update, context) 
         
    return MANAGE_GROUPS_MENU

# --- Manual Send Callbacks --- 
async def manual_send_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for manual message sending."""
    query = update.callback_query
    await query.answer()

    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لإرسال رسالة يدوية إليها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id in groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"📨 {group_id}", callback_data=f"manualsend_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد إرسال رسالة التحديث إليها يدوياً (سيؤدي هذا أيضاً إلى إعادة تعيين محاولات المستخدمين في تلك المجموعة):", reply_markup=reply_markup)
    return MANUAL_SEND_SELECT_GROUP

async def manual_send_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the update message manually to the selected group."""
    query = update.callback_query
    group_id_to_send = query.data.split("_", 1)[1]
    await query.answer(f"جارٍ إرسال الرسالة إلى {group_id_to_send}...")

    if group_id_to_send in groups_data:
        await send_or_edit_group_message(context, group_id_to_send)
        await query.edit_message_text(f"تم إرسال رسالة التحديث يدوياً إلى المجموعة {group_id_to_send}.")
    else:
        await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")

    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Format/Timezone Management Callbacks --- 
async def manage_format_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for managing format/timezone."""
    query = update.callback_query
    await query.answer()

    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لتعديل شكل رسائلها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id in groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"📝 {group_id}", callback_data=f"setformat_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد تعديل شكل الرسالة أو المنطقة الزمنية لها:", reply_markup=reply_markup)
    return MANAGE_FORMAT_SELECT_GROUP

async def set_format_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows message format options for the selected group."""
    query = update.callback_query
    group_id_str = query.data.split("_", 1)[1]
    context.user_data["format_group_id"] = group_id_str # Store for next step
    await query.answer()

    group_info = groups_data.get(group_id_str, {})
    current_format = group_info.get("message_format", 1)

    keyboard = [
        [InlineKeyboardButton(f"{'✅' if current_format == 1 else ''} شكل 1: وقت الرمز التالي فقط", callback_data="format_1")],
        [InlineKeyboardButton(f"{'✅' if current_format == 2 else ''} شكل 2: المدة المتبقية + وقت الرمز التالي", callback_data="format_2")],
        [InlineKeyboardButton(f"{'✅' if current_format == 3 else ''} شكل 3: المدة المتبقية + الوقت الحالي + وقت الرمز التالي", callback_data="format_3")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_format")] # Use callback to trigger previous state handler
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر شكل الرسالة للمجموعة {group_id_str}:", reply_markup=reply_markup)
    return SET_FORMAT

async def set_timezone_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected format and shows timezone options."""
    query = update.callback_query
    group_id_str = context.user_data.get("format_group_id")
    selected_format = int(query.data.split("_")[1])
    await query.answer()

    if not group_id_str or group_id_str not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Save the selected format
    groups_data[group_id_str]["message_format"] = selected_format
    # Don't save yet, save after timezone selection
    # save_json(GROUPS_FILE, groups_data)
    context.user_data["selected_format"] = selected_format # Store for final save

    group_info = groups_data.get(group_id_str, {})
    current_timezone = group_info.get("timezone", "GMT")

    keyboard = [
        [InlineKeyboardButton(f"{'✅' if current_timezone == 'GMT' else ''} توقيت غرينتش (GMT)", callback_data="timezone_GMT")],
        [InlineKeyboardButton(f"{'✅' if current_timezone == 'Asia/Gaza' else ''} توقيت غزة (Asia/Gaza)", callback_data="timezone_Gaza")],
        # Add more timezones if needed
        [InlineKeyboardButton("🔙 رجوع لاختيار الشكل", callback_data=f"setformat_{group_id_str}")] # Go back to format selection
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر المنطقة الزمنية للمجموعة {group_id_str} (الشكل {selected_format} تم اختياره):", reply_markup=reply_markup)
    return SET_TIMEZONE

async def save_format_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected timezone and format."""
    query = update.callback_query
    group_id_str = context.user_data.get("format_group_id")
    selected_format = context.user_data.get("selected_format")
    selected_timezone_code = query.data.split("_", 1)[1]
    await query.answer()

    if not group_id_str or group_id_str not in groups_data or selected_format is None:
        await query.edit_message_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Map code to actual timezone string
    if selected_timezone_code == "Gaza":
        selected_timezone = "Asia/Gaza"
    else: # Default to GMT
        selected_timezone = "GMT"

    # Save both format and timezone
    groups_data[group_id_str]["message_format"] = selected_format
    groups_data[group_id_str]["timezone"] = selected_timezone
    save_json(GROUPS_FILE, groups_data)

    await query.edit_message_text(f"تم حفظ الإعدادات للمجموعة {group_id_str}:\nالشكل: {selected_format}\nالمنطقة الزمنية: {selected_timezone}")
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Interval Management Callbacks --- 
async def manage_interval_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for managing interval."""
    query = update.callback_query
    await query.answer()

    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لتعديل فترة التكرار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id, group_info in groups_data.items():
        interval = group_info.get("interval", "غير محدد")
        status = f"{interval} دقيقة" if isinstance(interval, int) and interval > 0 else "متوقف"
        keyboard.append([InlineKeyboardButton(f"⏱️ {group_id} ({status})", callback_data=f"setintervalopt_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد تعديل فترة تكرار الرسائل لها:", reply_markup=reply_markup)
    return MANAGE_INTERVAL_SELECT_GROUP

async def set_interval_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows interval options for the selected group."""
    query = update.callback_query
    group_id_str = query.data.split("_", 1)[1]
    context.user_data["interval_group_id"] = group_id_str
    await query.answer()

    group_info = groups_data.get(group_id_str, {})
    current_interval = group_info.get("interval", 0)

    intervals = [5, 10, 15, 20, 30, 60, 0] # 0 means stop
    keyboard = []
    row = []
    for interval in intervals:
        text = f"{interval} دقيقة" if interval > 0 else "🚫 إيقاف التكرار"
        prefix = "✅ " if interval == current_interval else ""
        button = InlineKeyboardButton(f"{prefix}{text}", callback_data=f"interval_{interval}")
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: # Add remaining button if odd number
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_interval")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر فترة التكرار الجديدة للمجموعة {group_id_str} (الفترة الحالية: {'متوقف' if current_interval <= 0 else f'{current_interval} دقيقة'}):", reply_markup=reply_markup)
    return SET_INTERVAL_OPTIONS # New state for selecting interval value

async def save_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the selected interval and schedules/removes the job."""
    query = update.callback_query
    group_id_str = context.user_data.get("interval_group_id")
    try:
        selected_interval = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        logger.error(f"Invalid interval callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return SET_INTERVAL_OPTIONS # Stay in options state
        
    await query.answer()

    if not group_id_str or group_id_str not in groups_data:
        await query.edit_message_text("خطأ: لم يتم العثور على المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Save the interval
    groups_data[group_id_str]["interval"] = selected_interval
    save_json(GROUPS_FILE, groups_data)

    # Schedule or remove the job
    schedule_group_message_job(context, group_id_str, selected_interval)

    status_text = "متوقف" if selected_interval <= 0 else f"{selected_interval} دقيقة"
    await query.edit_message_text(f"تم ضبط فترة التكرار للمجموعة {group_id_str} إلى: {status_text}")
    
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Attempts Management Callbacks --- 
async def manage_attempts_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for managing user attempts."""
    query = update.callback_query
    await query.answer()

    if not groups_data:
        await query.edit_message_text("لا توجد مجموعات مضافة لإدارة محاولات مستخدميها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id in groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"👤 {group_id}", callback_data=f"attemptsgroup_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد إدارة محاولات المستخدمين فيها:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_SELECT_GROUP

async def manage_attempts_select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows users within the selected group to manage attempts."""
    query = update.callback_query
    group_id_str = query.data.split("_", 1)[1]
    context.user_data["attempts_group_id"] = group_id_str
    await query.answer()

    global user_attempts_data # Ensure using latest data
    user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    group_users = user_attempts_data.get(group_id_str, {})

    if not group_users:
        await query.edit_message_text(f"لا يوجد مستخدمون مسجلون في المجموعة {group_id_str} حتى الآن.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")]]))
        return MANAGE_ATTEMPTS_SELECT_GROUP

    keyboard = []
    default_attempts = config_data.get("default_copy_attempts", 3)
    for user_id_str, user_info in group_users.items():
        attempts_left = user_info.get("attempts_left", default_attempts)
        is_banned = user_info.get("is_banned", False)
        user_name = user_info.get("name", f"User {user_id_str}") # Get stored name or use ID
        status = "محظور" if is_banned else f"{attempts_left} محاولات"
        keyboard.append([InlineKeyboardButton(f"{user_name} ({status})", callback_data=f"attemptsuser_{user_id_str}")])
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر المستخدم لإدارة محاولاته في المجموعة {group_id_str}:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_SELECT_USER

async def manage_attempts_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows actions for the selected user (add/remove attempts, ban/unban)."""
    query = update.callback_query
    user_id_str = query.data.split("_", 1)[1]
    group_id_str = context.user_data.get("attempts_group_id")
    context.user_data["attempts_user_id"] = user_id_str
    await query.answer()

    if not group_id_str or group_id_str not in user_attempts_data or user_id_str not in user_attempts_data[group_id_str]:
        await query.edit_message_text("خطأ: لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء المحاولة مرة أخرى.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")]]))
        return MANAGE_ATTEMPTS_SELECT_GROUP

    user_info = user_attempts_data[group_id_str][user_id_str]
    user_name = user_info.get("name", f"User {user_id_str}")
    is_banned = user_info.get("is_banned", False)
    ban_text = "🚫 إلغاء حظر المستخدم" if is_banned else "🚫 حظر المستخدم"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data="attempts_action_add")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data="attempts_action_remove")],
        [InlineKeyboardButton(ban_text, callback_data="attempts_action_ban_toggle")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مستخدم", callback_data=f"attemptsgroup_{group_id_str}")] # Go back to user selection
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"إدارة المستخدم: {user_name} (المجموعة: {group_id_str})", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_ACTION

async def attempts_action_prompt_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the number of attempts to add."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال عدد المحاولات التي تريد إضافتها لهذا المستخدم:")
    return ADD_ATTEMPTS_COUNT

async def attempts_action_receive_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds the specified number of attempts to the user."""
    try:
        attempts_to_add = int(update.message.text.strip())
        if attempts_to_add <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح موجب لعدد المحاولات. /cancel للإلغاء.")
        return ADD_ATTEMPTS_COUNT

    group_id_str = context.user_data.get("attempts_group_id")
    user_id_str = context.user_data.get("attempts_user_id")

    if not group_id_str or not user_id_str or group_id_str not in user_attempts_data or user_id_str not in user_attempts_data[group_id_str]:
        await update.message.reply_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    default_attempts = config_data.get("default_copy_attempts", 3)
    current_attempts = user_attempts_data[group_id_str][user_id_str].get("attempts_left", default_attempts)
    user_attempts_data[group_id_str][user_id_str]["attempts_left"] = current_attempts + attempts_to_add
    # Ensure user is not banned if attempts are added
    user_attempts_data[group_id_str][user_id_str]["is_banned"] = False 
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    
    user_name = user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    new_total = user_attempts_data[group_id_str][user_id_str]["attempts_left"]
    await update.message.reply_text(f"تم إضافة {attempts_to_add} محاولة للمستخدم {user_name}. الرصيد الحالي: {new_total} محاولات.")
    
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

async def attempts_action_prompt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the number of attempts to remove."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال عدد المحاولات التي تريد حذفها من هذا المستخدم:")
    return REMOVE_ATTEMPTS_COUNT

async def attempts_action_receive_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes the specified number of attempts from the user."""
    try:
        attempts_to_remove = int(update.message.text.strip())
        if attempts_to_remove <= 0:
            raise ValueError("Number must be positive")
    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح موجب لعدد المحاولات. /cancel للإلغاء.")
        return REMOVE_ATTEMPTS_COUNT

    group_id_str = context.user_data.get("attempts_group_id")
    user_id_str = context.user_data.get("attempts_user_id")

    if not group_id_str or not user_id_str or group_id_str not in user_attempts_data or user_id_str not in user_attempts_data[group_id_str]:
        await update.message.reply_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    default_attempts = config_data.get("default_copy_attempts", 3)
    current_attempts = user_attempts_data[group_id_str][user_id_str].get("attempts_left", default_attempts)
    # Ensure attempts don't go below zero
    user_attempts_data[group_id_str][user_id_str]["attempts_left"] = max(0, current_attempts - attempts_to_remove)
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    
    user_name = user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    new_total = user_attempts_data[group_id_str][user_id_str]["attempts_left"]
    await update.message.reply_text(f"تم حذف {attempts_to_remove} محاولة من المستخدم {user_name}. الرصيد الحالي: {new_total} محاولات.")
    
    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

async def attempts_action_ban_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the ban status for the selected user."""
    query = update.callback_query
    group_id_str = context.user_data.get("attempts_group_id")
    user_id_str = context.user_data.get("attempts_user_id")
    await query.answer()

    if not group_id_str or not user_id_str or group_id_str not in user_attempts_data or user_id_str not in user_attempts_data[group_id_str]:
        await query.edit_message_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    current_ban_status = user_attempts_data[group_id_str][user_id_str].get("is_banned", False)
    new_ban_status = not current_ban_status
    user_attempts_data[group_id_str][user_id_str]["is_banned"] = new_ban_status
    # Optionally reset attempts when banning/unbanning?
    # user_attempts_data[group_id_str][user_id_str]["attempts_left"] = 0 if new_ban_status else config_data.get("default_copy_attempts", 3)
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)

    user_name = user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    status_text = "محظور" if new_ban_status else "غير محظور"
    await query.edit_message_text(f"تم تغيير حالة المستخدم {user_name} إلى: {status_text}")

    context.user_data.clear()
    # Go back to main menu
    await admin_command(update, context)
    return SELECTING_ACTION

# --- Admin Management Callbacks --- 
async def manage_admins_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the admin management menu."""
    query = update.callback_query
    await query.answer()
    
    current_admins = config_data.get("admins", [INITIAL_ADMIN_ID])
    admin_list_str = "\n".join([f"- `{admin_id}`" for admin_id in current_admins])
    if not admin_list_str:
        admin_list_str = "(لا يوجد مسؤولون حالياً - خطأ محتمل!)"
        
    text = f"إدارة المسؤولين:\n*المسؤولون الحاليون:*\n{admin_list_str}"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admins_add")],
        # Prevent deleting the initial admin or the only admin
        [InlineKeyboardButton("➖ حذف مسؤول", callback_data="admins_delete")] if len(current_admins) > 1 else [],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]
    ]
    # Remove empty lists from keyboard
    keyboard = [row for row in keyboard if row]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_ADMINS_MENU

async def admins_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the User ID of the new admin."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("الرجاء إرسال رقم معرّف المستخدم (User ID) الذي تريد إضافته كمسؤول.")
    return ADD_ADMIN_ID

async def admins_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the User ID and adds them as an admin."""
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("معرّف المستخدم غير صالح. يجب أن يكون رقماً. /cancel للإلغاء.")
        return ADD_ADMIN_ID

    current_admins = config_data.get("admins", [INITIAL_ADMIN_ID])
    if new_admin_id in current_admins:
        await update.message.reply_text("هذا المستخدم هو مسؤول بالفعل.")
    else:
        current_admins.append(new_admin_id)
        config_data["admins"] = current_admins
        save_json(CONFIG_FILE, config_data)
        await update.message.reply_text(f"تمت إضافة المستخدم `{new_admin_id}` كمسؤول بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)

    # Go back to admin management menu
    # Need to simulate callback query
    if update.callback_query:
         await manage_admins_menu(update.callback_query, context)
    else:
         # This part is tricky as we are in message handler
         # Send the menu again as a new message
         await admin_command(update, context)
         
    return MANAGE_ADMINS_MENU

async def admins_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of admins to select for deletion."""
    query = update.callback_query
    await query.answer()
    
    current_admins = config_data.get("admins", [INITIAL_ADMIN_ID])
    # Filter out the initial admin and the current user if they are the only admin left
    deletable_admins = [admin_id for admin_id in current_admins if admin_id != INITIAL_ADMIN_ID and (len(current_admins) == 1 or admin_id != query.from_user.id)]
    # Ensure we always keep at least one admin (the initial one if necessary)
    if len(current_admins) <= 1:
         deletable_admins = []

    if not deletable_admins:
        await query.edit_message_text("لا يمكن حذف المزيد من المسؤولين (يجب أن يبقى مسؤول واحد على الأقل، ولا يمكن حذف المسؤول الأولي).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]]))
        return MANAGE_ADMINS_MENU

    keyboard = []
    for admin_id in deletable_admins:
        keyboard.append([InlineKeyboardButton(f"➖ {admin_id}", callback_data=f"deladmin_{admin_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المسؤول الذي تريد حذفه (لا يمكنك حذف نفسك إذا كنت المسؤول الوحيد المتبقي):", reply_markup=reply_markup)
    return DELETE_ADMIN_SELECT

async def admins_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the selected admin."""
    query = update.callback_query
    try:
        admin_id_to_delete = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        logger.error(f"Invalid admin delete callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return MANAGE_ADMINS_MENU
        
    await query.answer()

    current_admins = config_data.get("admins", [INITIAL_ADMIN_ID])
    
    # Double check deletion conditions
    if admin_id_to_delete == INITIAL_ADMIN_ID:
         await query.edit_message_text("لا يمكن حذف المسؤول الأولي.")
    elif len(current_admins) <= 1:
         await query.edit_message_text("لا يمكن حذف المسؤول الوحيد المتبقي.")
    elif admin_id_to_delete == query.from_user.id and len([a for a in current_admins if a != INITIAL_ADMIN_ID]) <= 1:
         await query.edit_message_text("لا يمكنك حذف نفسك إذا كنت المسؤول الوحيد (غير الأولي) المتبقي.")
    elif admin_id_to_delete in current_admins:
        current_admins.remove(admin_id_to_delete)
        config_data["admins"] = current_admins
        save_json(CONFIG_FILE, config_data)
        await query.edit_message_text(f"تم حذف المسؤول `{admin_id_to_delete}` بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await query.edit_message_text("خطأ: المسؤول لم يعد موجوداً.")

    # Go back to admin management menu
    await manage_admins_menu(update, context)
    return MANAGE_ADMINS_MENU

# --- Copy Code Callback --- 
async def copy_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Copy Code' button press in the group message."""
    query = update.callback_query
    # Don't answer here yet, answer after checks

    user_id = query.from_user.id
    user_id_str = str(user_id)
    user_name = query.from_user.full_name
    try:
        group_id_str = query.data.split('_', 2)[-1]
        if not group_id_str.startswith('-'):
             raise ValueError("Invalid group ID format")
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing group_id from callback_data '{query.data}': {e}")
        await query.answer("حدث خطأ في معالجة الطلب.", show_alert=True)
        return

    # Reload data
    global groups_data, user_attempts_data, config_data
    groups_data = load_json(GROUPS_FILE, {})
    user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})

    group_info = groups_data.get(group_id_str)
    if not group_info:
        logger.warning(f"User {user_id} clicked copy for non-configured group {group_id_str}")
        await query.answer("خطأ: إعدادات هذه المجموعة غير موجودة.", show_alert=True)
        return

    # Initialize user data if first time for this group
    if group_id_str not in user_attempts_data:
        user_attempts_data[group_id_str] = {}
    if user_id_str not in user_attempts_data[group_id_str]:
        default_attempts = config_data.get("default_copy_attempts", 3)
        user_attempts_data[group_id_str][user_id_str] = {"attempts_left": default_attempts, "is_banned": False, "name": user_name}
        # No need to save yet, will save after decrementing or if banned
        
    user_data = user_attempts_data[group_id_str][user_id_str]
    
    # Update user name if changed
    if user_data.get("name") != user_name:
        user_data["name"] = user_name
        # No need to save yet

    # Check ban status
    if user_data.get("is_banned", False):
        await query.answer("عذراً، أنت محظور من استخدام هذا الزر في هذه المجموعة.", show_alert=True)
        return

    # Check attempts
    attempts_left = user_data.get("attempts_left", config_data.get("default_copy_attempts", 3))
    if attempts_left <= 0:
        await query.answer("عذراً، لقد استنفدت محاولاتك المتاحة لنسخ الرمز.", show_alert=True)
        return

    # Generate TOTP code
    totp_secret = group_info.get("secret")
    code = get_totp_code(totp_secret)

    if code is None:
        logger.error(f"Failed to generate TOTP for group {group_id_str}")
        await query.answer("حدث خطأ أثناء توليد الرمز. يرجى المحاولة لاحقاً أو إبلاغ المسؤول.", show_alert=True)
        return

    # Decrement attempts and save
    user_data["attempts_left"] = attempts_left - 1
    save_json(USER_ATTEMPTS_FILE, user_attempts_data)
    attempts_remaining_text = f"لديك {user_data['attempts_left']} محاولات متبقية."

    # Send private message
    try:
        message_text = (
            f"🔐 *{escape_md('رمز التحقق الخاص بك')}*\n\n"
            f"🔑 `{escape_md(code)}`\n\n"
            f" M {escape_md(attempts_remaining_text)}\n"
            f"⚠️ *{escape_md('هذا الرمز صالح لمدة 30 ثانية فقط.')}*"
        )
        await context.bot.send_message(
            chat_id=user_id, 
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        await query.answer("تم إرسال الرمز بنجاح إلى رسائلك الخاصة.")
    except TelegramError as e:
        logger.error(f"Failed to send private message to user {user_id}: {e}")
        # Try answering the callback query with an error message if PM fails
        await query.answer("لم أتمكن من إرسال الرمز إلى رسائلك الخاصة. هل بدأت محادثة معي؟", show_alert=True)
        # Revert attempt decrement? Maybe not, the attempt was made.
        # user_data["attempts_left"] = attempts_left
        # save_json(USER_ATTEMPTS_FILE, user_attempts_data)

# --- Error Handler --- 
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
    # Optionally notify admin about critical errors
    # Example: Check for specific error types
    if isinstance(context.error, Conflict):
         logger.critical("Conflict error detected! Multiple bot instances might be running.")
         # Try notifying the initial admin
         try:
             await context.bot.send_message(chat_id=INITIAL_ADMIN_ID, text=f"⚠️ *خطأ تعارض خطير!*
يبدو أن هناك أكثر من نسخة واحدة من البوت ({BOT_NAME}) تعمل في نفس الوقت.
الرجاء التأكد من إيقاف جميع النسخ الإضافية لتجنب المشاكل.
الخطأ: `{context.error}`", parse_mode=ParseMode.MARKDOWN_V2)
         except Exception as e:
             logger.error(f"Failed to send conflict error message to admin {INITIAL_ADMIN_ID}: {e}")

# --- Main Function --- 
def main():
    """Start the bot."""
    # Use persistence to store conversation states across restarts
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)
    
    # Build application with default JobQueue enabled
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

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
                CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
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
                CallbackQueryHandler(groups_edit_prompt_secret, pattern="^edit_option_secret$"),
                CallbackQueryHandler(groups_edit_select, pattern="^groups_edit$"),
            ],
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
                CallbackQueryHandler(manage_format_select_group, pattern="^admin_manage_format$"),
            ],
            SET_TIMEZONE: [
                CallbackQueryHandler(save_format_timezone, pattern="^timezone_(GMT|Gaza)$"),
                # Go back using context data
                CallbackQueryHandler(lambda u, c: set_format_options(u, c), pattern="^setformat_"), 
            ],
             # Interval States
            MANAGE_INTERVAL_SELECT_GROUP: [
                CallbackQueryHandler(set_interval_options, pattern="^setintervalopt_"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            SET_INTERVAL_OPTIONS: [
                 CallbackQueryHandler(save_interval, pattern="^interval_\d+$"),
                 CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"),
            ],
            # Attempts Management States
            MANAGE_ATTEMPTS_SELECT_GROUP: [
                CallbackQueryHandler(manage_attempts_select_user, pattern="^attemptsgroup_"),
                CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            ],
            MANAGE_ATTEMPTS_SELECT_USER: [
                CallbackQueryHandler(manage_attempts_action, pattern="^attemptsuser_"),
                CallbackQueryHandler(manage_attempts_select_group, pattern="^admin_manage_attempts$"),
            ],
            MANAGE_ATTEMPTS_ACTION: [
                CallbackQueryHandler(attempts_action_prompt_add, pattern="^attempts_action_add$"),
                CallbackQueryHandler(attempts_action_prompt_remove, pattern="^attempts_action_remove$"),
                CallbackQueryHandler(attempts_action_ban_toggle, pattern="^attempts_action_ban_toggle$"),
                # Go back using context data
                CallbackQueryHandler(lambda u, c: manage_attempts_select_user(u, c), pattern="^attemptsgroup_"), 
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
                CallbackQueryHandler(manage_admins_menu, pattern="^admin_manage_admins$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"),
            CallbackQueryHandler(admin_command, pattern="^admin_back_main$"),
            CommandHandler("admin", admin_command), # Restart admin flow if /admin is used again
        ],
        per_user=True,
        per_chat=False,
        persistent=True,
        name="admin_conversation"
    )

    # --- Handlers --- 
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(admin_conv_handler)
    application.add_handler(CallbackQueryHandler(copy_code_callback, pattern="^copy_code_"))
    application.add_error_handler(error_handler)

    # --- Post Init Function (Set Commands & Schedule Jobs) ---
    async def post_init(app: Application):
        # Set bot commands
        try:
            await app.bot.set_my_commands([
                BotCommand("start", "بدء استخدام البوت"),
                BotCommand("admin", "لوحة تحكم المسؤول (للمسؤولين فقط)")
            ])
            logger.info("Bot commands set successfully.")
        except TelegramError as e:
            logger.error(f"Failed to set bot commands: {e}")

        # Schedule jobs for existing groups
        logger.info("Scheduling jobs for existing groups on startup...")
        global groups_data # Ensure we use the loaded data
        groups_data = load_json(GROUPS_FILE, {}) # Reload just in case
        if app.job_queue:
            # Pass application context to the scheduling function
            # We need context to access job_queue inside schedule_group_message_job
            # A bit indirect, but should work
            dummy_context = ContextTypes.DEFAULT_TYPE(application=app, chat_id=None, user_id=None)
            
            for group_id_str, group_info in groups_data.items():
                interval = group_info.get("interval")
                if interval and isinstance(interval, int) and interval > 0:
                    # Check if job already exists (e.g., due to persistence)
                    job_name = f"group_msg_{group_id_str}"
                    existing_jobs = app.job_queue.get_jobs_by_name(job_name)
                    if not existing_jobs:
                         logger.info(f"Scheduling startup job for group {group_id_str} (Interval: {interval} mins)")
                         # Use the dummy context to call the scheduling function
                         schedule_group_message_job(dummy_context, group_id_str, interval)
                    else:
                         logger.info(f"Job {job_name} already exists, skipping startup schedule.")
        else:
            logger.warning("JobQueue not available in post_init, cannot schedule startup jobs.")

    application.post_init = post_init

    # Run the bot
    logger.info(f"Starting bot {BOT_NAME}...")
    # Consider using drop_pending_updates=True if conflict errors persist after ensuring single instance
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Data files will be created by load_json/save_json if they don't exist
    main()


# -*- coding: utf-8 -*-رM2.71
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
# !! تأكد من استبدال هذا بالرمز المميز الفعلي للبوت الخاص بك !!
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM" # استبدل هذا برمز البوت الخاص بك
BOT_NAME = "ChatGPTPlus2FABot"
CONFIG_FILE = "config.json"
GROUPS_FILE = "groups.json"
USER_ATTEMPTS_FILE = "user_attempts.json"
PERSISTENCE_FILE = "bot_persistence.pickle"

# Initial Admin ID (Can be expanded via Manage Admins feature)
# !! تأكد من أن هذا هو معرف المسؤول الأولي الصحيح !!
INITIAL_ADMIN_ID = 764559466 # استبدل هذا بمعرف المستخدم الخاص بك إذا لزم الأمر
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
logging.getLogger("httpx").setLevel(logging.WARNING) # تقليل تسجيلات httpx
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
                logger.warning(f"File {filename} is empty. Returning default data.")
                return default_data if default_data is not None else {}
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading {filename}: {e}. Returning default data.")
        # Attempt to save default data if loading fails and default is provided
        if default_data is not None:
             try:
                 save_json(filename, default_data)
                 logger.info(f"Saved default data to {filename} after load error.")
             except Exception as save_e:
                 logger.error(f"Failed to save default data to {filename} after load error: {save_e}")
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
        # logger.debug(f"Data saved to {filename}") # Log successful save if needed
    except IOError as e:
        logger.error(f"Error saving {filename}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving {filename}: {e}")

# --- Load Initial Data --- 
# Load data at the start, will be reloaded within functions where necessary to get latest state
config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
groups_data = load_json(GROUPS_FILE, {})
user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})

# --- Helper Functions --- 
def is_admin(user_id):
    """Checks if a user ID belongs to an admin. Reloads config for check."""
    # Reload config data each time to ensure check is against the latest admin list
    current_config = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    admin_list = current_config.get("admins", [])
    # Ensure all admin IDs are integers for comparison
    return int(user_id) in [int(admin_id) for admin_id in admin_list]

def get_totp_code(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        logger.warning("Attempted to generate TOTP with empty secret.")
        return None
    try:
        # Ensure secret is uppercase and properly padded for base32
        secret = secret.upper()
        padding = len(secret) % 8
        if padding != 0:
            secret += '=' * (8 - padding)
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        # Log the error but avoid logging the secret itself
        logger.error(f"Error generating TOTP code: {e}")
        return None

def escape_md(text):
    """Escapes special characters for MarkdownV2."""
    # Escape characters according to Telegram API documentation for MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Use re.sub to escape each character with a preceding backslash
    return re.sub(f'([{re.escape(escape_chars)}])', r'\
\1', str(text))

def format_group_message(group_id_str):
    """Formats the message to be sent to the group based on its settings."""
    # Reload groups_data to ensure the latest settings are used
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"format_group_message: Group config not found for {group_id_str}")
        return f"خطأ: لم يتم العثور على إعدادات المجموعة {escape_md(group_id_str)}."

    message_format = group_info.get("message_format", 1)
    interval_minutes = group_info.get("interval")
    timezone_str = group_info.get("timezone", "GMT")
    
    try:
        # Handle specific timezone aliases or use pytz directly
        if timezone_str.upper() == "GAZA":
            tz = pytz.timezone("Asia/Gaza")
        elif timezone_str.upper() == "GMT":
             tz = pytz.timezone("Etc/GMT") # Use standard GMT timezone
        else:
            tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{timezone_str}' for group {group_id_str}, defaulting to GMT.")
        tz = pytz.timezone("Etc/GMT")

    now = datetime.now(tz)
    next_code_time_str = "(غير محدد)"
    next_code_in_str = "(غير محدد)"

    # Calculate next code time only if interval is valid
    if interval_minutes and isinstance(interval_minutes, int) and interval_minutes > 0:
        try:
            # Calculate minutes to the next interval boundary
            current_minute = now.minute
            minutes_past_interval = current_minute % interval_minutes
            minutes_to_next_interval = interval_minutes - minutes_past_interval
            # Calculate the exact time of the next interval
            next_code_time_local = now + timedelta(minutes=minutes_to_next_interval)
            # Reset seconds and microseconds for clean display
            next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            # If calculated time is in the past or now (due to execution delay), advance to the next interval
            if next_code_time_local <= now:
                 next_code_time_local += timedelta(minutes=interval_minutes)
                 # Ensure seconds/microseconds are zeroed again after adding interval
                 next_code_time_local = next_code_time_local.replace(second=0, microsecond=0)

            # Format the time strings
            next_code_time_str = next_code_time_local.strftime("%I:%M:%S %p %Z") # e.g., 10:30:00 AM GMT
            next_code_in_str = f"{interval_minutes} دقيقة"
        except Exception as e:
            logger.error(f"Error calculating next code time for group {group_id_str}: {e}")
            next_code_time_str = "(خطأ في الحساب)"
            next_code_in_str = "(خطأ)"
    else:
        # Handle cases where interval is not set or invalid
        next_code_time_str = "(التكرار متوقف)"
        next_code_in_str = "(متوقف)"

    # Format current time
    correct_time_str = now.strftime("%I:%M:%S %p %Z")

    # Build the message using MarkdownV2, escaping all dynamic parts
    message = f"🔐 *{escape_md('رمز التحقق الثنائي (2FA)')}*\n\n"

    # Append parts based on the selected format
    if message_format == 1:
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    elif message_format == 2:
        message += f"{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*\n"
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    elif message_format == 3:
        message += f"{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*\n"
        message += f"{escape_md('الوقت الحالي')}: *{escape_md(correct_time_str)}*\n"
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
    else: # Default to format 1 if invalid format number
        logger.warning(f"Invalid message_format '{message_format}' for group {group_id_str}, using format 1.")
        message += f"{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*"
        
    return message

async def send_or_edit_group_message(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Sends a new message to the group or edits the last one if possible. Also resets attempts."""
    # Reload group data to ensure we have the latest info (secret, format, last_message_id)
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"send_or_edit_group_message: Group config not found for {group_id_str}. Cannot send/edit message.")
        return

    # Generate the message content using the latest group settings
    message_text = format_group_message(group_id_str)
    # Generate the TOTP code using the secret from the reloaded group_info
    totp_code = get_totp_code(group_info.get("secret"))
    
    if totp_code is None:
        logger.error(f"Failed to generate TOTP code for group {group_id_str}. Cannot send/edit message.")
        # Optionally send an error message to the group or admin?
        # For now, just return to prevent sending a message without a code.
        return

    # Prepare the inline keyboard with the actual TOTP code in the callback data
    # Note: Storing the actual code in callback_data might be a security concern if logs are compromised.
    # Consider alternative approaches if this is sensitive (e.g., generating code on button press).
    keyboard = [[InlineKeyboardButton("🔑 نسخ الرمز (Copy Code)", callback_data=f"copy_code_{group_id_str}_{totp_code}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    last_message_id = group_info.get("last_message_id")
    message_sent_or_edited = False
    new_message_id = None
    
    try:
        # Try editing the existing message first
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
                new_message_id = last_message_id # Keep the same message ID
            except BadRequest as e:
                # Handle common errors like "message is not modified" or "message to edit not found"
                if "message is not modified" in str(e):
                    logger.info(f"Message {last_message_id} in group {group_id_str} was not modified.")
                    message_sent_or_edited = True # Treat as success, no need to send new
                    new_message_id = last_message_id
                elif "message to edit not found" in str(e):
                    logger.warning(f"Message {last_message_id} to edit in group {group_id_str} not found. Sending new message.")
                    group_info["last_message_id"] = None # Clear invalid ID
                else:
                    logger.warning(f"Failed to edit message {last_message_id} in group {group_id_str}: {e}. Sending new message.")
                    group_info["last_message_id"] = None # Clear potentially problematic ID
            except TelegramError as e:
                # Handle other Telegram errors during edit
                logger.error(f"Telegram error editing message {last_message_id} in group {group_id_str}: {e}")
                group_info["last_message_id"] = None # Clear potentially problematic ID
                
        # If editing failed or no previous message ID exists, send a new message
        if not message_sent_or_edited:
            sent_message = await context.bot.send_message(
                chat_id=int(group_id_str),
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            new_message_id = sent_message.message_id
            logger.info(f"Sent new message {new_message_id} to group {group_id_str}")
            message_sent_or_edited = True

        # Update last_message_id in groups_data only if a message was successfully sent/edited
        # and the ID has changed or was newly created.
        if message_sent_or_edited and new_message_id and group_info.get("last_message_id") != new_message_id:
            # Reload groups_data again before saving to minimize race conditions
            current_groups_data_before_save = load_json(GROUPS_FILE, {})
            if group_id_str in current_groups_data_before_save:
                current_groups_data_before_save[group_id_str]["last_message_id"] = new_message_id
                save_json(GROUPS_FILE, current_groups_data_before_save)
                logger.info(f"Updated last_message_id for group {group_id_str} to {new_message_id}")
            else:
                logger.warning(f"Group {group_id_str} was removed before last_message_id could be updated.")

        # Reset attempts only if a message was successfully sent or edited
        if message_sent_or_edited:
            # Reload config and user attempts data before resetting
            current_config = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
            current_user_attempts = load_json(USER_ATTEMPTS_FILE, {})
            
            if group_id_str in current_user_attempts:
                default_attempts = current_config.get("default_copy_attempts", 3)
                changed = False
                # Iterate over a copy of user IDs for safe modification
                for user_id_str in list(current_user_attempts[group_id_str].keys()):
                    # Check if user exists and is not banned before resetting attempts
                    if user_id_str in current_user_attempts[group_id_str] and not current_user_attempts[group_id_str][user_id_str].get("is_banned", False):
                        # Reset attempts only if they are not already the default value
                        if current_user_attempts[group_id_str][user_id_str].get("attempts_left") != default_attempts:
                             current_user_attempts[group_id_str][user_id_str]["attempts_left"] = default_attempts
                             changed = True
                # Save only if changes were made
                if changed:
                    save_json(USER_ATTEMPTS_FILE, current_user_attempts)
                    logger.info(f"Reset attempts for non-banned users in group {group_id_str} to {default_attempts}")

    except TelegramError as e:
        logger.error(f"Failed to send/edit message in group {group_id_str}: {e}")
        # If bot is blocked or kicked, stop the job for this group
        error_str = str(e).lower()
        if "bot was blocked" in error_str or "chat not found" in error_str or "bot was kicked" in error_str or "group chat was deleted" in error_str:
             logger.warning(f"Bot seems blocked/kicked/chat deleted for group {group_id_str}. Removing job and marking group as inactive.")
             remove_group_message_job(context, group_id_str)
             # Mark group as inactive by setting interval to 0
             current_groups_data_on_error = load_json(GROUPS_FILE, {})
             if group_id_str in current_groups_data_on_error:
                 current_groups_data_on_error[group_id_str]["interval"] = 0 # Mark as inactive
                 current_groups_data_on_error[group_id_str]["last_message_id"] = None
                 save_json(GROUPS_FILE, current_groups_data_on_error)
                 logger.info(f"Marked group {group_id_str} as inactive due to Telegram error.")
    except ValueError:
         # This might happen if group_id_str is not a valid integer
         logger.error(f"Invalid group ID format for sending message: {group_id_str}")
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception(f"Unexpected error in send_or_edit_group_message for {group_id_str}: {e}")

# --- Job Queue Functions --- 
async def periodic_group_message_callback(context: ContextTypes.DEFAULT_TYPE):
    """Callback function for the scheduled group message job."""
    job = context.job
    if not job or not job.data or "group_id" not in job.data:
        logger.error(f"Job {job.name if job else 'N/A'} is missing group_id in data. Cannot execute.")
        if job:
            logger.warning(f"Removing job {job.name} due to missing group_id.")
            job.schedule_removal()
        return
        
    group_id_str = job.data["group_id"]
    logger.info(f"Running scheduled job {job.name} for group {group_id_str}")
    
    # Reload group data right before execution to check validity
    current_groups_data = load_json(GROUPS_FILE, {}) 
    group_info = current_groups_data.get(group_id_str)
    
    # Check if group still exists and has a valid positive interval
    if not group_info or not isinstance(group_info.get("interval"), int) or group_info.get("interval", 0) <= 0:
        logger.warning(f"Group {group_id_str} not found or interval disabled/invalid ({group_info.get('interval', 'N/A')}). Removing job {job.name}.")
        job.schedule_removal() # Remove the job itself
        return
        
    # Proceed to send/edit the message
    await send_or_edit_group_message(context, group_id_str)
    logger.info(f"Finished scheduled job {job.name} for group {group_id_str}")

def remove_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Removes the scheduled message job(s) for a specific group."""
    if not context.job_queue:
        logger.warning("JobQueue not available, cannot remove jobs.")
        return False # Indicate failure
        
    job_name = f"group_msg_{group_id_str}"
    # Get all jobs with the specific name
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        logger.info(f"No active job found with name {job_name} for group {group_id_str} to remove.")
        return False # Indicate no job was found
        
    removed_count = 0
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Scheduled removal for job {job.name} (ID: {job.id}) for group {group_id_str}")
        removed_count += 1
        
    return removed_count > 0 # Indicate if any jobs were scheduled for removal

def schedule_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str, interval_minutes: int):
    """Schedules or updates the periodic message job for a group."""
    if not context.job_queue:
        logger.error("JobQueue not available, cannot schedule jobs.")
        return
        
    job_name = f"group_msg_{group_id_str}"
    # Remove existing job(s) for this group first to prevent duplicates
    was_removed = remove_group_message_job(context, group_id_str)
    if was_removed:
        logger.info(f"Removed existing job(s) named {job_name} before scheduling new one.")

    # Schedule new job only if interval is positive
    if interval_minutes > 0:
        try:
            # Use run_repeating for periodic tasks
            # Set first=0 to run immediately, then repeat at the interval
            context.job_queue.run_repeating(
                periodic_group_message_callback,
                interval=timedelta(minutes=interval_minutes),
                first=0, # Run the first time immediately
                name=job_name,
                data={"group_id": group_id_str}
            )
            logger.info(f"Scheduled new job {job_name} for group {group_id_str} with interval {interval_minutes} minutes.")
        except Exception as e:
             # Catch potential errors during scheduling (e.g., invalid interval)
             logger.exception(f"Failed to schedule job {job_name} for group {group_id_str}: {e}")
    else:
         # Log if interval is zero or negative (job removal is handled by remove_group_message_job)
         logger.info(f"Interval is {interval_minutes} for group {group_id_str}, no new job scheduled.")

# --- Command Handlers --- 
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot.")
    await update.message.reply_text(
        f"أهلاً بك في بوت {escape_md(BOT_NAME)}!\n"
        f"اضغط على زر '🔑 نسخ الرمز \(Copy Code\)' في رسائل المجموعة للحصول على رمز 2FA الخاص بك\.\n"
        f"إذا كنت مسؤولاً، استخدم الأمر /admin لإدارة الإعدادات\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /admin command and shows the main admin menu if the user is an admin."""
    user = update.effective_user
    user_id = user.id
    logger.info(f"Admin command initiated by user {user_id} ({user.username})")
    
    # Check admin status using the helper function
    if not is_admin(user_id):
        logger.warning(f"Non-admin user {user_id} ({user.username}) tried to use /admin command.")
        # Check if it's a callback query from a non-admin trying to access admin functions
        if update.callback_query:
            await update.callback_query.answer("عذراً، هذه الأزرار للمسؤولين فقط.", show_alert=True)
            # Don't end conversation here, let the main handler decide
            return SELECTING_ACTION # Or maybe ConversationHandler.END?
        else:
            await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
            # End conversation if initiated by message command from non-admin
            return ConversationHandler.END

    # --- Admin Menu Keyboard --- 
    keyboard = [
        [InlineKeyboardButton("⚙️ إدارة المجموعات/الأسرار", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("📨 إرسال رسالة التحديث يدوياً", callback_data="admin_manual_send")],
        [InlineKeyboardButton("📝 إدارة شكل الرسالة/التوقيت", callback_data="admin_manage_format")],
        [InlineKeyboardButton("⏱️ إدارة فترة التكرار", callback_data="admin_manage_interval")],
        [InlineKeyboardButton("👤 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")], # <<< زر إدارة المسؤولين
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "القائمة الرئيسية للمسؤول:"
    
    # Handle both command initiation and callback query navigation to this menu
    if update.callback_query:
        query = update.callback_query
        await query.answer() # Acknowledge callback
        try:
            # Edit the message to show the admin menu
            await query.edit_message_text(text, reply_markup=reply_markup)
            logger.info(f"Admin menu shown to {user_id} via callback.")
        except BadRequest as e:
            if "message is not modified" in str(e):
                logger.info(f"Admin menu message for {user_id} not modified.")
                pass # Ignore if message is identical
            else:
                # Log other BadRequest errors and potentially send a new message if edit fails
                logger.error(f"Error editing admin menu for {user_id}: {e}")
                # Fallback: Send a new message if editing fails
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
                logger.info(f"Sent new admin menu message to {user_id} after edit failed.")
        except Exception as e:
            logger.exception(f"Unexpected error showing admin menu via callback for {user_id}: {e}")
            await query.message.reply_text("حدث خطأ أثناء عرض القائمة. حاول مرة أخرى.")
    else:
        # If initiated by /admin command, send a new message
        await update.message.reply_text(text, reply_markup=reply_markup)
        logger.info(f"Admin menu shown to {user_id} via command.")
        
    # Set the conversation state to expect the user to select an action
    return SELECTING_ACTION

# --- Callback Query Handlers (Main Menu Selection) --- 
async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current admin operation and ends the conversation."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    try:
        await query.edit_message_text("تم إلغاء العملية.")
        logger.info(f"Admin operation cancelled by user {user_id}.")
    except BadRequest as e:
        if "message is not modified" in str(e):
            pass
        else:
            logger.error(f"Error editing cancellation message for {user_id}: {e}")
    except Exception as e:
        logger.exception(f"Error cancelling admin operation for {user_id}: {e}")
        
    # Clear any temporary data stored in user_data for the conversation
    context.user_data.clear()
    # End the conversation
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
    try:
        await query.edit_message_text("إدارة المجموعات والأسرار:", reply_markup=reply_markup)
    except BadRequest as e:
        if "message is not modified" in str(e): pass
        else: logger.error(f"Error showing group mgmt menu: {e}")
    except Exception as e:
        logger.exception(f"Error in admin_manage_groups_menu: {e}")
    return MANAGE_GROUPS_MENU

async def groups_add_prompt_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the Group ID."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text("الرجاء إرسال رقم معرّف المجموعة (Group ID) التي تريد إضافتها.\n(يجب أن يبدأ بـ `-100` ويحتوي على أرقام فقط)\nأو استخدم /cancel للإلغاء.")
    except BadRequest as e:
        if "message is not modified" in str(e): pass
        else: logger.error(f"Error prompting for group ID: {e}")
    except Exception as e:
        logger.exception(f"Error in groups_add_prompt_id: {e}")
    return ADD_GROUP_ID

async def groups_add_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the Group ID and prompts for the TOTP Secret."""
    if not update.message or not update.message.text:
        # Ignore non-text messages in this state
        return ADD_GROUP_ID 
        
    group_id_str = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Validate Group ID format
    if not re.fullmatch(r'-100\d+', group_id_str):
        await update.message.reply_text("معرّف المجموعة غير صالح. يجب أن يبدأ بـ `-100` ويتبعه أرقام فقط. الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء.")
        return ADD_GROUP_ID # Stay in the same state
        
    # Reload groups data to check if ID already exists
    current_groups_data = load_json(GROUPS_FILE, {})
    if group_id_str in current_groups_data:
         await update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة التعديل. استخدم /cancel للإلغاء والعودة للقائمة.")
         return ADD_GROUP_ID

    # Store the valid group ID in user_data for the next step
    context.user_data["new_group_id"] = group_id_str
    logger.info(f"User {user_id} provided new group ID: {group_id_str}")
    await update.message.reply_text("تم استلام معرّف المجموعة. الآن الرجاء إرسال المفتاح السري (TOTP Secret) الخاص بهذه المجموعة.\n(يجب أن يتكون من أحرف A-Z وأرقام 2-7)\nأو استخدم /cancel للإلغاء.")
    return ADD_GROUP_SECRET

async def groups_add_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the TOTP Secret and saves the new group."""
    if not update.message or not update.message.text:
        return ADD_GROUP_SECRET
        
    totp_secret = update.message.text.strip()
    user_id = update.effective_user.id
    group_id_str = context.user_data.get("new_group_id")

    if not group_id_str:
        logger.error(f"User {user_id} reached groups_add_receive_secret without new_group_id in user_data.")
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرّف المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END
        
    # Validate TOTP secret format (Base32 characters, typical length)
    if not re.fullmatch(r'^[A-Z2-7=]+$', totp_secret.upper()) or len(totp_secret) < 16:
        await update.message.reply_text("المفتاح السري (TOTP Secret) يبدو غير صالح. يجب أن يتكون من أحرف A-Z وأرقام 2-7 فقط وأن يكون طوله مناسباً (عادة 16 حرفاً أو أكثر). الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء.")
        return ADD_GROUP_SECRET

    # Reload groups data again before saving
    current_groups_data = load_json(GROUPS_FILE, {})
    # Check again if group was added concurrently (less likely but possible)
    if group_id_str in current_groups_data:
        logger.warning(f"Group {group_id_str} was added concurrently before secret could be saved by user {user_id}.")
        await update.message.reply_text("تمت إضافة هذه المجموعة للتو بواسطة مسؤول آخر أو عملية أخرى. استخدم /cancel للعودة.")
        context.user_data.clear()
        return ADD_GROUP_SECRET # Or END?

    # Save the new group data
    current_groups_data[group_id_str] = {
        "secret": totp_secret,
        "interval": DEFAULT_INTERVAL_MINUTES, # Set default interval
        "message_format": 1, # Default format
        "timezone": "GMT", # Default timezone
        "last_message_id": None
    }
    save_json(GROUPS_FILE, current_groups_data)
    logger.info(f"User {user_id} added group {group_id_str} with default interval {DEFAULT_INTERVAL_MINUTES}.")
    
    # Schedule the job for the new group
    schedule_group_message_job(context, group_id_str, DEFAULT_INTERVAL_MINUTES)

    await update.message.reply_text(f"تم إضافة المجموعة `{escape_md(group_id_str)}` بنجاح مع فترة تكرار تلقائية {DEFAULT_INTERVAL_MINUTES} دقيقة\.", parse_mode=ParseMode.MARKDOWN_V2)
    context.user_data.clear()
    
    # Go back to the main admin menu automatically by calling the handler
    # We need an Update object for admin_command, use the current one
    await admin_command(update, context)
    # Return the state expected by admin_command
    return SELECTING_ACTION

async def groups_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of groups to select for deletion."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    
    # Reload groups data
    current_groups_data = load_json(GROUPS_FILE, {})
    
    if not current_groups_data:
        logger.info(f"User {user_id} tried to delete group, but none exist.")
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]]))
        # Return to the previous menu state
        return MANAGE_GROUPS_MENU

    keyboard = []
    # Sort groups by ID for consistent display
    for group_id in sorted(current_groups_data.keys()):
        keyboard.append([InlineKeyboardButton(f"🗑️ {group_id}", callback_data=f"delgroup_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
    except BadRequest as e:
        if "message is not modified" in str(e): pass
        else: logger.error(f"Error showing group delete selection: {e}")
    except Exception as e:
        logger.exception(f"Error in groups_delete_select: {e}")
        
    return DELETE_GROUP_SELECT

async def groups_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting a group."""
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        group_id_to_delete = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid callback data in groups_delete_confirm from user {user_id}: {query.data}")
        await query.answer("خطأ: بيانات غير صالحة.", show_alert=True)
        # Go back to selection
        await groups_delete_select(update, context)
        return DELETE_GROUP_SELECT
        
    # Store ID in context for the confirmation step
    context.user_data["group_to_delete"] = group_id_to_delete
    logger.info(f"User {user_id} selected group {group_id_to_delete} for deletion confirmation.")
    
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✅ نعم، متأكد", callback_data="delete_confirm_yes")],
        [InlineKeyboardButton("❌ لا، إلغاء", callback_data="delete_confirm_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(f"هل أنت متأكد من حذف المجموعة `{escape_md(group_id_to_delete)}`؟\nسيتم حذف جميع إعداداتها وبيانات محاولات المستخدمين المرتبطة بها وإيقاف تحديثاتها\.", 
                                  reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    except BadRequest as e:
        if "message is not modified" in str(e): pass
        else: logger.error(f"Error showing group delete confirmation: {e}")
    except Exception as e:
        logger.exception(f"Error in groups_delete_confirm: {e}")
        
    return DELETE_GROUP_CONFIRM

async def groups_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes the group deletion or cancels it based on confirmation."""
    query = update.callback_query
    user_id = update.effective_user.id
    group_id_to_delete = context.user_data.get("group_to_delete")
    decision = query.data.split("_")[-1]

    await query.answer()

    if decision == "yes" and group_id_to_delete:
        logger.info(f"User {user_id} confirmed deletion for group {group_id_to_delete}.")
        # Reload data before deleting
        current_groups_data = load_json(GROUPS_FILE, {})
        current_user_attempts = load_json(USER_ATTEMPTS_FILE, {})
        
        deleted_group = False
        if group_id_to_delete in current_groups_data:
            # Remove the scheduled job first
            remove_group_message_job(context, group_id_to_delete)
            
            # Delete group config
            del current_groups_data[group_id_to_delete]
            save_json(GROUPS_FILE, current_groups_data)
            deleted_group = True
            logger.info(f"Deleted group config for {group_id_to_delete}.")
            
            # Also remove associated user attempts
            if group_id_to_delete in current_user_attempts:
                del current_user_attempts[group_id_to_delete]
                save_json(USER_ATTEMPTS_FILE, current_user_attempts)
                logger.info(f"Deleted user attempts data for group {group_id_to_delete}.")
                
            await query.edit_message_text(f"تم حذف المجموعة `{escape_md(group_id_to_delete)}` بنجاح\.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            logger.warning(f"User {user_id} tried to delete group {group_id_to_delete}, but it was already removed.")
            await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
    elif decision == "no":
        logger.info(f"User {user_id} cancelled deletion for group {group_id_to_delete}.")
        await query.edit_message_text("تم إلغاء الحذف.")
    else:
        logger.error(f"Invalid decision '{decision}' in groups_delete_execute for user {user_id}.")
        await query.edit_message_text("حدث خطأ غير متوقع.")

    # Clear context data
    context.user_data.clear()
    # Go back to group management menu by calling its handler
    await admin_manage_groups_menu(update, context)
    return MANAGE_GROUPS_MENU

async def groups_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of groups to select for editing."""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    
    current_groups_data = load_json(GROUPS_FILE, {})
    
    if not current_groups_data:
        logger.info(f"User {user_id} tried to edit group, but none exist.")
        await query.edit_message_text("لا توجد مجموعات مضافة حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")]]))
        return MANAGE_GROUPS_MENU

    keyboard = []
    for group_id in sorted(current_groups_data.keys()):
        keyboard.append([InlineKeyboardButton(f"✏️ {group_id}", callback_data=f"editgroup_{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_groups_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text("اختر المجموعة التي تريد تعديلها:", reply_markup=reply_markup)
    except BadRequest as e:
        if "message is not modified" in str(e): pass
        else: logger.error(f"Error showing group edit selection: {e}")
    except Exception as e:
        logger.exception(f"Error in groups_edit_select: {e}")
    return EDIT_GROUP_SELECT

async def groups_edit_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows options for editing a selected group (currently only secret)."""
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        group_id_to_edit = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid callback data in groups_edit_option from user {user_id}: {query.data}")
        await query.answer("خطأ: بيانات غير صالحة.", show_alert=True)
        await groups_edit_select(update, context)
        return EDIT_GROUP_SELECT
        
    context.user_data["group_to_edit"] = group_id_to_edit
    logger.info(f"User {user_id} selected group {group_id_to_edit} for editing.")
    
    await query.answer()
    keyboard = [
        # [InlineKeyboardButton("تعديل معرّف المجموعة (ID)", callback_data="edit_option_id")], # Editing ID is complex, disabled for now
        [InlineKeyboardButton("🔑 تعديل المفتاح السري (Secret)", callback_data="edit_option_secret")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="groups_edit")] # Use callback to trigger previous state handler
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(f"تعديل المجموعة `{escape_md(group_id_to_edit)}`: اختر الحقل الذي تريد تعديله\.

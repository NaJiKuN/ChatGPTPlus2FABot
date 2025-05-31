# -*- coding: utf-8 -*-
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
    JobQueue # Explicitly imported, though default builder enables it
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, Conflict

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
 MANAGE_INTERVAL_SELECT_GROUP, SET_INTERVAL_OPTIONS, SET_INTERVAL
) = range(25) # 25 states

# --- Logging Setup --- 
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Data Handling Functions --- 
def load_json(filename, default_data=None):
    """Loads data from a JSON file. Creates the file with default data if it doesn't exist."""
    if not os.path.exists(filename):
        logger.info(f"File {filename} not found. Creating with default data.")
        if default_data is None:
            default_data = {}
        save_json(filename, default_data) # Save the default data
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
        # Recreate with default if error occurs?
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
        if dir_name: # Only create if filename includes a directory path
            os.makedirs(dir_name, exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # logger.debug(f"Data successfully saved to {filename}") # Debug level
    except IOError as e:
        logger.error(f"IOError saving {filename}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error saving {filename}: {e}")

# --- Load Initial Data --- 
# Load config first as it contains initial admin list
config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
groups_data = load_json(GROUPS_FILE, {})
user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})

# --- Helper Functions --- 
def is_admin(user_id):
    """Checks if a user ID belongs to an admin using the latest config data."""
    # Always reload config to get the latest admin list
    current_config = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    admin_list = current_config.get("admins", [])
    # logger.debug(f"Checking admin status for {user_id}. Admin list: {admin_list}")
    return user_id in admin_list

def get_totp_code(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        logger.warning("Attempted to generate TOTP with empty secret.")
        return None
    try:
        # Ensure correct padding for base32
        secret = secret.upper().replace(" ", "") # Remove spaces and uppercase
        padding = len(secret) % 8
        if padding != 0:
            secret += '=' * (8 - padding)
        totp = pyotp.TOTP(secret)
        code = totp.now()
        # logger.debug(f"Generated TOTP code {code} for secret {secret[:4]}...")
        return code
    except Exception as e:
        logger.error(f"Error generating TOTP code (Secret: {secret[:4]}...): {e}")
        return None

def escape_md(text):
    """Escapes special characters for MarkdownV2."""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def format_group_message(group_id_str):
    """Formats the message to be sent to the group based on its settings."""
    # Reload groups_data to ensure we have the latest format settings
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"format_group_message: Group configuration not found for {group_id_str}.")
        return "Error: Group configuration not found."

    message_format = group_info.get("message_format", 1)
    interval_minutes = group_info.get("interval") # Can be None or 0
    timezone_str = group_info.get("timezone", "GMT")
    logger.debug(f"Formatting message for group {group_id_str}. Format: {message_format}, Interval: {interval_minutes}, TZ: {timezone_str}")

    try:
        # Handle common timezone variations
        tz_upper = timezone_str.upper()
        if tz_upper == "GAZA":
            tz = pytz.timezone("Asia/Gaza")
        elif tz_upper == "GMT" or tz_upper == "UTC":
             tz = pytz.timezone("Etc/GMT")
        else:
            tz = pytz.timezone(timezone_str) # Try the user-provided string
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{timezone_str}' for group {group_id_str}, defaulting to GMT.")
        tz = pytz.timezone("Etc/GMT")

    now = datetime.now(tz)
    next_code_time_str = "(غير محدد)"
    next_code_in_str = "(غير محدد)"

    if interval_minutes and isinstance(interval_minutes, int) and interval_minutes > 0:
        try:
            # Calculate next interval time more reliably
            current_minute_of_hour = now.minute
            minutes_past_interval_start = current_minute_of_hour % interval_minutes
            minutes_to_next_interval = interval_minutes - minutes_past_interval_start
            
            # Calculate the absolute time of the next interval
            next_interval_time = now + timedelta(minutes=minutes_to_next_interval)
            next_interval_time = next_interval_time.replace(second=0, microsecond=0)

            # If the calculated time is in the past or exactly now (due to rounding/timing), add another interval
            if next_interval_time <= now:
                 next_interval_time += timedelta(minutes=interval_minutes)

            next_code_time_str = next_interval_time.strftime("%I:%M:%S %p %Z")
            next_code_in_str = f"{interval_minutes} دقيقة"
            logger.debug(f"Next code time calculated for group {group_id_str}: {next_code_time_str}")
        except Exception as e:
            logger.error(f"Error calculating next code time for group {group_id_str}: {e}")
            next_code_time_str = "(خطأ في الحساب)"
            next_code_in_str = "(خطأ)"
    else:
        logger.debug(f"Interval not set or <= 0 for group {group_id_str}. Setting time strings to 'stopped'.")
        next_code_time_str = "(التكرار متوقف)"
        next_code_in_str = "(متوقف)"

    correct_time_str = now.strftime("%I:%M:%S %p %Z")

    # Build the message string
    message_parts = [f"🔐 *{escape_md('رمز التحقق الثنائي (2FA)')}*\n"]

    if message_format == 1:
        message_parts.append(f"\n{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*")
    elif message_format == 2:
        message_parts.append(f"\n{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*")
        message_parts.append(f"\n{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*")
    elif message_format == 3:
        message_parts.append(f"\n{escape_md('الرمز التالي خلال')}: *{escape_md(next_code_in_str)}*" )
        message_parts.append(f"\n{escape_md('الوقت الحالي')}: *{escape_md(correct_time_str)}*" )
        message_parts.append(f"\n{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*" )
    else: # Default to format 1 if invalid format number
        logger.warning(f"Invalid message_format '{message_format}' for group {group_id_str}. Defaulting to format 1.")
        message_parts.append(f"\n{escape_md('الرمز التالي في')}: *{escape_md(next_code_time_str)}*" )
        
    final_message = "".join(message_parts)
    logger.debug(f"Formatted message for group {group_id_str}: {final_message[:100]}...")
    return final_message

async def send_or_edit_group_message(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Sends a new message to the group or edits the last one if possible. Also resets attempts."""
    logger.info(f"Attempting to send/edit message for group {group_id_str}")
    # Reload data at the start of the function
    current_groups_data = load_json(GROUPS_FILE, {})
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})

    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        logger.error(f"send_or_edit_group_message: Group configuration not found for {group_id_str}. Aborting send.")
        return

    message_text = format_group_message(group_id_str)
    if not message_text or "Error:" in message_text:
        logger.error(f"send_or_edit_group_message: Failed to format message for group {group_id_str}. Aborting send.")
        return
        
    keyboard = [[InlineKeyboardButton("🔑 نسخ الرمز (Copy Code)", callback_data=f"copy_code_{group_id_str}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    last_message_id = group_info.get("last_message_id")
    logger.debug(f"Group {group_id_str}: Last message ID from config: {last_message_id}")
    message_sent_or_edited = False
    new_message_id = None
    
    try:
        # Attempt to edit first if last_message_id exists
        if last_message_id:
            logger.debug(f"Attempting to edit message {last_message_id} in group {group_id_str}")
            try:
                await context.bot.edit_message_text(
                    chat_id=int(group_id_str),
                    message_id=last_message_id,
                    text=message_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                logger.info(f"Successfully edited message {last_message_id} in group {group_id_str}")
                message_sent_or_edited = True
                new_message_id = last_message_id # Keep the same message ID
            except BadRequest as e:
                # Common errors: message not modified, message can't be edited, message to edit not found
                logger.warning(f"BadRequest editing message {last_message_id} in group {group_id_str}: {e}. Will try sending a new message.")
                group_info["last_message_id"] = None # Clear invalid message ID
            except TelegramError as e:
                logger.error(f"TelegramError editing message {last_message_id} in group {group_id_str}: {e}. Will try sending a new message.")
                group_info["last_message_id"] = None # Clear potentially invalid message ID
                
        # If editing failed or wasn't attempted, send a new message
        if not message_sent_or_edited:
            logger.debug(f"Attempting to send new message to group {group_id_str}")
            sent_message = await context.bot.send_message(
                chat_id=int(group_id_str),
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            new_message_id = sent_message.message_id
            logger.info(f"Successfully sent new message {new_message_id} to group {group_id_str}")
            message_sent_or_edited = True

        # --- Update last_message_id and Reset attempts --- 
        if message_sent_or_edited and new_message_id:
            # Update last_message_id in our loaded data
            current_groups_data[group_id_str]["last_message_id"] = new_message_id
            save_json(GROUPS_FILE, current_groups_data) # Save the updated message ID
            logger.debug(f"Updated last_message_id for group {group_id_str} to {new_message_id}")

            # Reset attempts for users in this group
            if group_id_str in current_user_attempts_data:
                default_attempts = current_config_data.get("default_copy_attempts", 3)
                changed = False
                logger.debug(f"Resetting attempts for group {group_id_str}. Default: {default_attempts}")
                for user_id_str, user_data in current_user_attempts_data[group_id_str].items():
                    if not user_data.get("is_banned", False):
                        if user_data.get("attempts_left") != default_attempts:
                             user_data["attempts_left"] = default_attempts
                             logger.debug(f"Reset attempts for user {user_id_str} in group {group_id_str} to {default_attempts}")
                             changed = True
                if changed:
                    save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
                    logger.info(f"Finished resetting attempts for users in group {group_id_str}")
            else:
                logger.debug(f"No users found in attempts data for group {group_id_str}, skipping attempt reset.")

    except TelegramError as e:
        logger.error(f"TelegramError sending/editing message in group {group_id_str}: {e}")
        # Handle specific errors like bot blocked/kicked
        if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower() or "bot was kicked" in str(e).lower() or "group chat was deleted" in str(e).lower():
             logger.warning(f"Bot seems blocked/kicked/chat deleted for group {group_id_str}. Removing job and marking inactive.")
             remove_group_message_job(context, group_id_str)
             if group_id_str in current_groups_data:
                 current_groups_data[group_id_str]["interval"] = 0 # Mark as inactive
                 current_groups_data[group_id_str]["last_message_id"] = None
                 save_json(GROUPS_FILE, current_groups_data)
        # Handle cases where the bot might not have permission to send messages
        elif "have no rights to send a message" in str(e).lower():
             logger.error(f"Bot does not have permission to send messages in group {group_id_str}. Removing job.")
             remove_group_message_job(context, group_id_str)
             if group_id_str in current_groups_data:
                 current_groups_data[group_id_str]["interval"] = 0 # Mark as inactive
                 save_json(GROUPS_FILE, current_groups_data)
    except ValueError as e:
         # Likely int(group_id_str) failed
         logger.error(f"Invalid group ID format '{group_id_str}' for sending message: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in send_or_edit_group_message for {group_id_str}: {e}") # Use logger.exception to include traceback

# --- Job Queue Functions --- 
async def periodic_group_message_callback(context: ContextTypes.DEFAULT_TYPE):
    """Callback function for the scheduled group message job."""
    job = context.job
    if not job or not job.data or "group_id" not in job.data:
        logger.error(f"Job {job.name if job else 'N/A'} is missing group_id in data. Cannot proceed.")
        if job:
            job.schedule_removal()
            logger.info(f"Removed job {job.name} due to missing data.")
        return
        
    group_id_str = job.data["group_id"]
    logger.info(f"Executing periodic job '{job.name}' for group {group_id_str}")
    
    # Reload group data inside the callback to ensure freshness
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    
    # Check if group still exists and has a valid interval
    if not group_info:
        logger.warning(f"Group {group_id_str} not found in config during job execution. Removing job '{job.name}'.")
        job.schedule_removal()
        return
        
    interval = group_info.get("interval")
    if not interval or not isinstance(interval, int) or interval <= 0:
        logger.warning(f"Group {group_id_str} interval is {interval}. Removing job '{job.name}'.")
        job.schedule_removal()
        return
        
    # Call the send/edit function
    try:
        logger.debug(f"Calling send_or_edit_group_message for group {group_id_str} from job '{job.name}'")
        await send_or_edit_group_message(context, group_id_str)
        logger.debug(f"Finished send_or_edit_group_message call for group {group_id_str} from job '{job.name}'")
    except Exception as e:
        logger.exception(f"Error occurred within periodic_group_message_callback while processing group {group_id_str}: {e}")

def remove_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str):
    """Removes the scheduled message job(s) for a specific group."""
    if not context.job_queue:
        logger.warning("JobQueue not available, cannot remove jobs.")
        return False # Indicate failure
    job_name = f"group_msg_{group_id_str}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        logger.info(f"No active job found with name '{job_name}' for group {group_id_str} to remove.")
        return False # Indicate no job was found
    
    removed_count = 0
    for job in current_jobs:
        job.schedule_removal()
        logger.info(f"Scheduled removal for job '{job.name}' (group {group_id_str})")
        removed_count += 1
    return removed_count > 0 # Indicate if any jobs were scheduled for removal

def schedule_group_message_job(context: ContextTypes.DEFAULT_TYPE, group_id_str: str, interval_minutes: int):
    """Schedules or updates the periodic message job for a group."""
    if not context.job_queue:
        logger.error("JobQueue not available, cannot schedule jobs.")
        return
        
    job_name = f"group_msg_{group_id_str}"
    logger.info(f"Attempting to schedule/update job '{job_name}' for group {group_id_str} with interval {interval_minutes} minutes.")
    
    # Remove existing job(s) with the same name first to prevent duplicates
    remove_group_message_job(context, group_id_str)

    if interval_minutes > 0:
        try:
            # Use run_repeating for periodic tasks
            # The first run will be after the first interval passes.
            # If you want it to run immediately AND then repeat, you might need 
            # to call send_or_edit_group_message once manually after scheduling.
            context.job_queue.run_repeating(
                periodic_group_message_callback,
                interval=timedelta(minutes=interval_minutes),
                # first=0, # Start immediately (can cause rapid initial calls if bot restarts often)
                first=timedelta(minutes=interval_minutes), # Start after the first interval
                name=job_name,
                data={"group_id": group_id_str} # Pass group_id in data
            )
            logger.info(f"Successfully scheduled job '{job_name}' for group {group_id_str} with interval {interval_minutes} minutes.")
        except Exception as e:
             logger.exception(f"Failed to schedule job '{job_name}' for group {group_id_str}: {e}")
    else:
         logger.info(f"Interval is {interval_minutes} for group {group_id_str}. Job '{job_name}' removed, no new job scheduled.")

# --- Command Handlers --- 
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    logger.info(f"Received /start command from user {update.effective_user.id}")
    await update.message.reply_text(
        f"أهلاً بك في بوت {BOT_NAME}!\n"
        f"اضغط على زر 'Copy Code' في رسائل المجموعة للحصول على رمز 2FA الخاص بك.\n"
        f"إذا كنت مسؤولاً، استخدم الأمر /admin لإدارة الإعدادات."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /admin command and shows the main admin menu."""
    user = update.effective_user
    logger.info(f"Received /admin command from user {user.id} ({user.full_name})")
    
    # Check if user is admin
    if not is_admin(user.id):
        logger.warning(f"Non-admin user {user.id} tried to use /admin.")
        # Check if it's a callback query from a non-admin trying to access menu
        if update.callback_query:
            try:
                await update.callback_query.answer("عذراً، هذه الأزرار للمسؤولين فقط.", show_alert=True)
            except TelegramError as e:
                 logger.error(f"Error answering callback query for non-admin {user.id}: {e}")
            return ConversationHandler.END # End conversation for non-admins trying buttons
        else:
            await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
            return ConversationHandler.END

    # Build the main admin menu keyboard
    keyboard = [
        [InlineKeyboardButton("⚙️ إدارة المجموعات/الأسرار", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("📨 إرسال رسالة التحديث يدوياً", callback_data="admin_manual_send")],
        [InlineKeyboardButton("🎨 إدارة شكل الرسالة/المنطقة الزمنية", callback_data="admin_manage_format")],
        [InlineKeyboardButton("⏱️ إدارة فترة التكرار", callback_data="admin_manage_interval")],
        [InlineKeyboardButton("🚫 إدارة المحاولات/الحظر", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("🔑 إدارة المسؤولين", callback_data="admin_manage_admins")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    menu_text = "القائمة الرئيسية للمسؤول:"
    
    # If called from a callback query, edit the message
    if update.callback_query:
        try:
            await update.callback_query.answer() # Acknowledge the callback
            await update.callback_query.edit_message_text(menu_text, reply_markup=reply_markup)
        except BadRequest as e:
             logger.warning(f"Failed to edit message for admin menu (maybe message not changed?): {e}")
        except TelegramError as e:
             logger.error(f"Error editing message for admin menu: {e}")
    # If called from a command, send a new message
    else:
        await update.message.reply_text(menu_text, reply_markup=reply_markup)
        
    return SELECTING_ACTION # Initial state for the conversation

# --- Conversation Handler Callbacks (Admin Menu Navigation) --- 

async def back_to_main_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback to go back to the main admin menu from submenus."""
    # This function essentially calls admin_command logic again
    # Ensure user is still admin before showing menu
    if not is_admin(update.effective_user.id):
         if update.callback_query:
             await update.callback_query.answer("لم تعد لديك صلاحيات المسؤول.", show_alert=True)
         return ConversationHandler.END
         
    # Reuse admin_command to display the menu
    return await admin_command(update, context)

# --- Group Management Callbacks --- 
async def manage_groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the group management menu."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessed group management menu.")
    
    # Reload groups data
    current_groups_data = load_json(GROUPS_FILE, {})
    
    group_list_str = ""
    if current_groups_data:
        group_list_parts = []
        for gid, ginfo in current_groups_data.items():
            secret_preview = ginfo.get('secret', 'N/A')[:4] + '...' if ginfo.get('secret') else '(لا يوجد)'
            interval = ginfo.get('interval', 'N/A')
            group_list_parts.append(f"- `{gid}` (Secret: {secret_preview}, Interval: {interval} min)")
        group_list_str = "\n".join(group_list_parts)
    else:
        group_list_str = "(لا توجد مجموعات مضافة حالياً)"
        
    text = f"إدارة المجموعات والأسرار:\n*المجموعات الحالية:*\n{group_list_str}"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="groups_add")],
        [InlineKeyboardButton("✏️ تعديل مجموعة", callback_data="groups_edit")] if current_groups_data else [],
        [InlineKeyboardButton("➖ حذف مجموعة", callback_data="groups_delete")] if current_groups_data else [],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]
    ]
    keyboard = [row for row in keyboard if row] # Remove empty rows
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_GROUPS_MENU

async def groups_add_prompt_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the Group ID."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} starting to add a new group.")
    await query.edit_message_text("الرجاء إرسال رقم معرّف المجموعة (Group ID) التي تريد إضافتها.\n" 
                              "(يجب أن يبدأ بـ '-' للمجموعات والمجموعات الخارقة).")
    return ADD_GROUP_ID

async def groups_add_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the Group ID and prompts for the TOTP Secret."""
    group_id_str = update.message.text.strip()
    logger.info(f"Admin {update.effective_user.id} entered Group ID: {group_id_str}")
    
    # Validate Group ID format (basic check)
    if not group_id_str.startswith('-') or not group_id_str[1:].isdigit():
        await update.message.reply_text("معرّف المجموعة غير صالح. يجب أن يكون رقماً سالباً (يبدأ بـ '-'). حاول مرة أخرى أو /cancel للإلغاء.")
        return ADD_GROUP_ID # Stay in the same state
        
    # Check if group already exists
    current_groups_data = load_json(GROUPS_FILE, {})
    if group_id_str in current_groups_data:
        await update.message.reply_text("هذه المجموعة مضافة بالفعل. يمكنك تعديلها من قائمة إدارة المجموعات. /cancel للإلغاء.")
        return ADD_GROUP_ID

    context.user_data["new_group_id"] = group_id_str
    await update.message.reply_text("تم استلام معرّف المجموعة. الآن الرجاء إرسال مفتاح TOTP السري (TOTP Secret) لهذه المجموعة.")
    return ADD_GROUP_SECRET

async def groups_add_receive_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the TOTP Secret and saves the new group."""
    totp_secret = update.message.text.strip()
    group_id_str = context.user_data.get("new_group_id")
    logger.info(f"Admin {update.effective_user.id} entered TOTP Secret for group {group_id_str}")

    if not group_id_str:
        logger.error("Group ID missing from user_data in groups_add_receive_secret.")
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرّف المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END
        
    if not totp_secret:
        await update.message.reply_text("المفتاح السري لا يمكن أن يكون فارغاً. حاول مرة أخرى أو /cancel للإلغاء.")
        return ADD_GROUP_SECRET

    # Validate secret basic format (optional, pyotp handles padding)
    # Add basic validation if needed, e.g., check for valid base32 characters

    # Reload data before modifying
    current_groups_data = load_json(GROUPS_FILE, {})
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    
    # Add the new group
    current_groups_data[group_id_str] = {
        "secret": totp_secret,
        "message_format": 1, # Default format
        "timezone": "GMT", # Default timezone
        "interval": DEFAULT_INTERVAL_MINUTES, # Default interval
        "last_message_id": None
    }
    save_json(GROUPS_FILE, current_groups_data)
    logger.info(f"Admin {update.effective_user.id} added new group {group_id_str}")

    # Schedule the job for the new group
    schedule_group_message_job(context, group_id_str, DEFAULT_INTERVAL_MINUTES)
    
    # Send confirmation and return to group menu
    await update.message.reply_text(f"تمت إضافة المجموعة `{group_id_str}` بنجاح بالإعدادات الافتراضية (تكرار كل {DEFAULT_INTERVAL_MINUTES} دقيقة).", parse_mode=ParseMode.MARKDOWN_V2)
    context.user_data.clear()
    
    # Go back to group management menu by simulating a callback
    # We need an Update object that has a callback_query
    # A bit hacky, maybe just return MANAGE_GROUPS_MENU?
    # Let's try returning the state directly.
    # await manage_groups_menu(update, context) # This won't work as update is Message
    # Instead, send the menu again?
    # Or better: return the state and let the handler call the entry point if needed
    # For now, let's just inform the user and end here, they can use /admin again.
    # await update.message.reply_text("يمكنك العودة إلى قائمة الإدارة باستخدام /admin")
    # return ConversationHandler.END
    
    # Let's try returning the state to potentially redisplay the menu
    # Need to ensure the entry point for MANAGE_GROUPS_MENU can handle being called again
    # The manage_groups_menu function expects a callback query... this is problematic.
    
    # Simplest approach: End conversation here, user uses /admin again.
    await update.message.reply_text("للعودة لقائمة إدارة المجموعات، استخدم /admin واختر إدارة المجموعات.")
    return ConversationHandler.END

async def groups_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of groups to select for deletion."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing delete group selection.")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if not current_groups_data:
        await query.edit_message_text("لا توجد مجموعات لحذفها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))
        return MANAGE_GROUPS_MENU

    keyboard = []
    for group_id_str in current_groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"➖ {group_id_str}", callback_data=f"delgroup_{group_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
    return DELETE_GROUP_SELECT

async def groups_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting the group."""
    query = update.callback_query
    try:
        group_id_to_delete = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid delete group callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return MANAGE_GROUPS_MENU
        
    await query.answer()
    logger.info(f"Admin {query.from_user.id} selected group {group_id_to_delete} for deletion confirmation.")
    
    context.user_data["group_to_delete"] = group_id_to_delete
    
    keyboard = [
        [InlineKeyboardButton("✅ نعم، حذف المجموعة", callback_data="delete_group_yes")],
        [InlineKeyboardButton("❌ لا، إلغاء", callback_data="delete_group_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"هل أنت متأكد أنك تريد حذف المجموعة `{group_id_to_delete}` وكل بياناتها المرتبطة (المحاولات، إلخ)؟", 
                              reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return DELETE_GROUP_CONFIRM

async def groups_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes the group deletion or cancels."""
    query = update.callback_query
    action = query.data # "delete_group_yes" or "delete_group_no"
    group_id_to_delete = context.user_data.get("group_to_delete")
    await query.answer()

    if action == "delete_group_yes" and group_id_to_delete:
        logger.info(f"Admin {query.from_user.id} confirmed deletion of group {group_id_to_delete}")
        # Reload data before modifying
        current_groups_data = load_json(GROUPS_FILE, {})
        current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
        
        deleted = False
        if group_id_to_delete in current_groups_data:
            del current_groups_data[group_id_to_delete]
            save_json(GROUPS_FILE, current_groups_data)
            deleted = True
            logger.info(f"Deleted group {group_id_to_delete} from groups config.")
            
            # Remove associated scheduled job
            remove_group_message_job(context, group_id_to_delete)
            
            # Remove associated user attempts
            if group_id_to_delete in current_user_attempts_data:
                del current_user_attempts_data[group_id_to_delete]
                save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
                logger.info(f"Deleted attempts data for group {group_id_to_delete}.")
                
            await query.edit_message_text(f"تم حذف المجموعة `{group_id_to_delete}` بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            logger.warning(f"Admin {query.from_user.id} tried to delete non-existent group {group_id_to_delete}")
            await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")
            
    elif action == "delete_group_no":
        logger.info(f"Admin {query.from_user.id} cancelled deletion of group {group_id_to_delete}")
        await query.edit_message_text("تم إلغاء عملية الحذف.")
    else:
        logger.error(f"Invalid action or missing group_id in groups_delete_execute. Action: {action}, GroupID: {group_id_to_delete}")
        await query.edit_message_text("حدث خطأ غير متوقع.")

    context.user_data.clear()
    # Go back to group management menu
    return await manage_groups_menu(update, context)

# --- Edit Group Callbacks (Simplified - Add if needed) ---
async def groups_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder - Implement full edit functionality if required
    query = update.callback_query
    await query.answer("ميزة التعديل لم تنفذ بعد.", show_alert=True)
    logger.info(f"Admin {query.from_user.id} attempted to use unimplemented edit feature.")
    # Stay in the group menu
    # return MANAGE_GROUPS_MENU 
    # Or go back to main menu?
    return await manage_groups_menu(update, context) # Return to group menu

# --- Manual Send Callbacks --- 
async def manual_send_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for manual message send."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing manual send selection.")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if not current_groups_data:
        await query.edit_message_text("لا توجد مجموعات لإرسال رسالة لها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id_str in current_groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"📨 {group_id_str}", callback_data=f"manualsend_{group_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد إرسال/تحديث رسالة الرمز لها يدوياً (سيؤدي هذا أيضاً إلى إعادة تعيين محاولات المستخدمين للمجموعة المحددة):", reply_markup=reply_markup)
    return MANUAL_SEND_SELECT_GROUP

async def manual_send_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends/edits the message for the selected group manually."""
    query = update.callback_query
    try:
        group_id_str = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid manual send callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer(f"جاري إرسال/تحديث الرسالة للمجموعة {group_id_str}...")
    logger.info(f"Admin {query.from_user.id} triggered manual send for group {group_id_str}")
    
    # Call the send/edit function
    await send_or_edit_group_message(context, group_id_str)
    
    # Optionally edit the confirmation message or just go back to menu
    await query.edit_message_text(f"تم إرسال/تحديث الرسالة للمجموعة `{group_id_str}` يدوياً.", parse_mode=ParseMode.MARKDOWN_V2)
    
    # Go back to main menu after a delay?
    # For now, just stay on the confirmation message.
    # User can use /admin again.
    return ConversationHandler.END # End conversation after manual send

# --- Format Management Callbacks --- 
async def manage_format_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for format/timezone management."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing format/timezone selection.")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if not current_groups_data:
        await query.edit_message_text("لا توجد مجموعات لتعديل شكل رسالتها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id_str, group_info in current_groups_data.items():
        fmt = group_info.get("message_format", 1)
        tz = group_info.get("timezone", "GMT")
        keyboard.append([InlineKeyboardButton(f"🎨 {group_id_str} (Format: {fmt}, TZ: {tz})", callback_data=f"formatgroup_{group_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد تعديل شكل رسالتها أو منطقتها الزمنية:", reply_markup=reply_markup)
    return MANAGE_FORMAT_SELECT_GROUP

async def manage_format_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows options to change format or timezone for the selected group."""
    query = update.callback_query
    try:
        group_id_str = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid format group callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer()
    logger.info(f"Admin {query.from_user.id} selected group {group_id_str} for format/tz management.")
    context.user_data["format_group_id"] = group_id_str
    
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_format")]]))
        return MANAGE_FORMAT_SELECT_GROUP
        
    current_format = group_info.get("message_format", 1)
    current_tz = group_info.get("timezone", "GMT")

    keyboard = [
        [InlineKeyboardButton(f"🔄 تغيير شكل الرسالة (الحالي: {current_format})", callback_data="format_change_fmt")],
        [InlineKeyboardButton(f"🌍 تغيير المنطقة الزمنية (الحالية: {current_tz})", callback_data="format_change_tz")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_format")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"إدارة التنسيق للمجموعة: `{group_id_str}`", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return EDIT_GROUP_OPTION # Reusing state, maybe rename later

async def format_set_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the available message format options."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} choosing message format.")
    
    keyboard = [
        [InlineKeyboardButton("الشكل 1: وقت الرمز التالي فقط", callback_data="setformat_1")],
        [InlineKeyboardButton("الشكل 2: مدة + وقت الرمز التالي", callback_data="setformat_2")],
        [InlineKeyboardButton("الشكل 3: مدة + وقت حالي + وقت تالي", callback_data="setformat_3")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"formatgroup_{context.user_data.get('format_group_id')}")] # Go back to format options
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر شكل الرسالة المطلوب للمجموعة:", reply_markup=reply_markup)
    return SET_FORMAT

async def format_set_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the selected message format for the group."""
    query = update.callback_query
    try:
        new_format = int(query.data.split("_", 1)[1])
        if new_format not in [1, 2, 3]: raise ValueError
    except (IndexError, ValueError):
        logger.error(f"Invalid set format callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return EDIT_GROUP_OPTION # Go back to options
        
    group_id_str = context.user_data.get("format_group_id")
    if not group_id_str:
        logger.error("Group ID missing from user_data in format_set_execute.")
        await query.answer("خطأ: لم يتم العثور على المجموعة.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer()
    logger.info(f"Admin {query.from_user.id} setting format {new_format} for group {group_id_str}")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if group_id_str in current_groups_data:
        current_groups_data[group_id_str]["message_format"] = new_format
        save_json(GROUPS_FILE, current_groups_data)
        await query.edit_message_text(f"تم تحديث شكل الرسالة للمجموعة `{group_id_str}` إلى الشكل {new_format}.", parse_mode=ParseMode.MARKDOWN_V2)
        # Update the message in the group immediately to reflect the change?
        # await send_or_edit_group_message(context, group_id_str)
    else:
        await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")

    # Go back to format options menu
    # Need to simulate callback query again...
    # Let's end the conversation here for simplicity
    context.user_data.clear()
    await query.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin") # Send as new message
    return ConversationHandler.END

async def format_set_timezone_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts the admin to enter the timezone."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} choosing to set timezone.")
    group_id_str = context.user_data.get("format_group_id")
    current_groups_data = load_json(GROUPS_FILE, {})
    current_tz = "GMT"
    if group_id_str and group_id_str in current_groups_data:
        current_tz = current_groups_data[group_id_str].get("timezone", "GMT")
        
    await query.edit_message_text(f"الرجاء إرسال اسم المنطقة الزمنية المطلوبة (مثلاً: `Asia/Gaza`, `Africa/Cairo`, `Europe/London`, `GMT`, `UTC`).\nالحالية: `{current_tz}`\n(يمكنك كتابة `GAZA` كاختصار لـ Asia/Gaza). /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN_V2)
    return SET_TIMEZONE

async def format_set_timezone_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and validates the timezone, then saves it."""
    timezone_str = update.message.text.strip()
    group_id_str = context.user_data.get("format_group_id")
    logger.info(f"Admin {update.effective_user.id} entered timezone '{timezone_str}' for group {group_id_str}")

    if not group_id_str:
        logger.error("Group ID missing from user_data in format_set_timezone_receive.")
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرّف المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END
        
    # Validate timezone
    try:
        tz_upper = timezone_str.upper()
        if tz_upper == "GAZA":
            validated_tz_str = "Asia/Gaza"
            pytz.timezone(validated_tz_str)
        elif tz_upper == "GMT" or tz_upper == "UTC":
             validated_tz_str = "Etc/GMT" # Store consistently
             pytz.timezone(validated_tz_str)
        else:
            pytz.timezone(timezone_str) # Validate using pytz
            validated_tz_str = timezone_str # Store the valid user input
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Invalid timezone entered by admin: {timezone_str}")
        await update.message.reply_text("المنطقة الزمنية غير صالحة. الرجاء إدخال اسم صحيح من قائمة TZ database (مثل `Asia/Riyadh`) أو `GMT` أو `GAZA`. حاول مرة أخرى أو /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN_V2)
        return SET_TIMEZONE
    except Exception as e:
        logger.error(f"Unexpected error validating timezone '{timezone_str}': {e}")
        await update.message.reply_text("حدث خطأ غير متوقع أثناء التحقق من المنطقة الزمنية. حاول مرة أخرى أو /cancel للإلغاء.")
        return SET_TIMEZONE

    # Save the validated timezone
    current_groups_data = load_json(GROUPS_FILE, {})
    if group_id_str in current_groups_data:
        current_groups_data[group_id_str]["timezone"] = validated_tz_str
        save_json(GROUPS_FILE, current_groups_data)
        logger.info(f"Admin {update.effective_user.id} set timezone '{validated_tz_str}' for group {group_id_str}")
        await update.message.reply_text(f"تم تحديث المنطقة الزمنية للمجموعة `{group_id_str}` إلى `{validated_tz_str}`.", parse_mode=ParseMode.MARKDOWN_V2)
        # Update the message in the group immediately?
        # await send_or_edit_group_message(context, group_id_str)
    else:
        await update.message.reply_text("خطأ: المجموعة لم تعد موجودة.")

    # End conversation
    context.user_data.clear()
    await update.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin")
    return ConversationHandler.END

# --- Interval Management Callbacks --- 
async def manage_interval_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for interval management."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing interval management selection.")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if not current_groups_data:
        await query.edit_message_text("لا توجد مجموعات لتعديل فترة تكرارها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id_str, group_info in current_groups_data.items():
        interval = group_info.get("interval")
        interval_text = f"{interval} دقيقة" if interval and interval > 0 else "(متوقف)"
        keyboard.append([InlineKeyboardButton(f"⏱️ {group_id_str} ({interval_text})", callback_data=f"intervalgroup_{group_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد تعديل فترة تكرار رسالة الرمز لها:", reply_markup=reply_markup)
    return MANAGE_INTERVAL_SELECT_GROUP

async def manage_interval_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows interval options for the selected group."""
    query = update.callback_query
    try:
        group_id_str = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid interval group callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer()
    logger.info(f"Admin {query.from_user.id} selected group {group_id_str} for interval management.")
    context.user_data["interval_group_id"] = group_id_str
    
    current_groups_data = load_json(GROUPS_FILE, {})
    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]]))
        return MANAGE_INTERVAL_SELECT_GROUP
        
    current_interval = group_info.get("interval")
    interval_text = f"{current_interval} دقيقة" if current_interval and current_interval > 0 else "(متوقف)"

    # Define common interval options
    options = [5, 10, 15, 20, 30, 60, 0] # 0 means stop
    keyboard = []
    # Create two columns of buttons
    row = []
    for i, val in enumerate(options):
        text = f"{val} دقيقة" if val > 0 else "🚫 إيقاف التكرار"
        row.append(InlineKeyboardButton(text, callback_data=f"setinterval_{val}"))
        if (i + 1) % 2 == 0 or i == len(options) - 1:
            keyboard.append(row)
            row = []
            
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_interval")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(f"إدارة فترة التكرار للمجموعة: `{group_id_str}`\nالحالية: *{interval_text}*\n\nاختر الفترة الجديدة بالدقائق (0 لإيقاف التكرار التلقائي):", 
                              reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return SET_INTERVAL_OPTIONS # State to handle interval selection

async def interval_set_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the selected interval for the group and reschedules the job."""
    query = update.callback_query
    try:
        new_interval = int(query.data.split("_", 1)[1])
        if new_interval < 0: raise ValueError("Interval cannot be negative")
    except (IndexError, ValueError):
        logger.error(f"Invalid set interval callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return MANAGE_INTERVAL_SELECT_GROUP # Go back to group selection
        
    group_id_str = context.user_data.get("interval_group_id")
    if not group_id_str:
        logger.error("Group ID missing from user_data in interval_set_execute.")
        await query.answer("خطأ: لم يتم العثور على المجموعة.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer()
    interval_text = f"{new_interval} دقيقة" if new_interval > 0 else "(متوقف)"
    logger.info(f"Admin {query.from_user.id} setting interval {interval_text} for group {group_id_str}")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if group_id_str in current_groups_data:
        current_groups_data[group_id_str]["interval"] = new_interval
        save_json(GROUPS_FILE, current_groups_data)
        
        # Reschedule the job with the new interval
        schedule_group_message_job(context, group_id_str, new_interval)
        
        await query.edit_message_text(f"تم تحديث فترة التكرار للمجموعة `{group_id_str}` إلى: *{interval_text}*.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await query.edit_message_text("خطأ: المجموعة لم تعد موجودة.")

    # End conversation
    context.user_data.clear()
    await query.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin")
    return ConversationHandler.END

# --- Attempts Management Callbacks --- 
async def manage_attempts_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows groups to select for attempts/ban management."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing attempts/ban group selection.")
    
    current_groups_data = load_json(GROUPS_FILE, {})
    if not current_groups_data:
        await query.edit_message_text("لا توجد مجموعات لإدارة محاولات مستخدميها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
        return SELECTING_ACTION

    keyboard = []
    for group_id_str in current_groups_data.keys():
        keyboard.append([InlineKeyboardButton(f"👥 {group_id_str}", callback_data=f"attemptsgroup_{group_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المجموعة التي تريد إدارة محاولات المستخدمين أو حظرهم فيها:", reply_markup=reply_markup)
    return MANAGE_ATTEMPTS_SELECT_GROUP

async def manage_attempts_select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows users within the selected group to manage attempts/ban."""
    query = update.callback_query
    try:
        group_id_str = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid attempts group callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return SELECTING_ACTION
        
    await query.answer()
    logger.info(f"Admin {query.from_user.id} selected group {group_id_str} for attempts/ban management.")
    context.user_data["attempts_group_id"] = group_id_str
    
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    group_users = current_user_attempts_data.get(group_id_str)
    
    if not group_users:
        await query.edit_message_text("لا يوجد مستخدمون مسجلون لهذه المجموعة بعد (يتم تسجيلهم عند أول ضغط على زر النسخ).", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")]]))
        return MANAGE_ATTEMPTS_SELECT_GROUP

    keyboard = []
    for user_id_str, user_info in group_users.items():
        name = user_info.get("name", f"User {user_id_str}")
        attempts = user_info.get("attempts_left", "N/A")
        banned = "(محظور)" if user_info.get("is_banned", False) else ""
        keyboard.append([InlineKeyboardButton(f"👤 {name} ({attempts}) {banned}", callback_data=f"attemptsuser_{user_id_str}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"اختر المستخدم للمجموعة `{group_id_str}`:", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_ATTEMPTS_SELECT_USER

async def manage_attempts_action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows actions for the selected user (add/remove attempts, ban/unban)."""
    query = update.callback_query
    try:
        user_id_str = query.data.split("_", 1)[1]
    except IndexError:
        logger.error(f"Invalid attempts user callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return MANAGE_ATTEMPTS_SELECT_GROUP # Go back to group selection
        
    await query.answer()
    group_id_str = context.user_data.get("attempts_group_id")
    context.user_data["attempts_user_id"] = user_id_str
    logger.info(f"Admin {query.from_user.id} selected user {user_id_str} in group {group_id_str} for action menu.")

    # Reload data
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    if not group_id_str or group_id_str not in current_user_attempts_data or user_id_str not in current_user_attempts_data[group_id_str]:
        await query.edit_message_text("خطأ: لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء المحاولة مرة أخرى.", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")]]))
        return MANAGE_ATTEMPTS_SELECT_GROUP

    user_info = current_user_attempts_data[group_id_str][user_id_str]
    user_name = user_info.get("name", f"User {user_id_str}")
    attempts_left = user_info.get("attempts_left", "N/A")
    is_banned = user_info.get("is_banned", False)
    ban_text = "🔓 إلغاء حظر المستخدم" if is_banned else "🚫 حظر المستخدم"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data="attempts_action_add")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data="attempts_action_remove")],
        [InlineKeyboardButton(ban_text, callback_data="attempts_action_ban_toggle")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مستخدم", callback_data=f"attemptsgroup_{group_id_str}")] # Go back to user selection for this group
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"إدارة المستخدم: *{escape_md(user_name)}* (`{user_id_str}`)\nالمجموعة: `{group_id_str}`\nالمحاولات المتبقية: *{attempts_left}*\nالحالة: *{'محظور' if is_banned else 'نشط'}*", 
                              reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_ATTEMPTS_ACTION

async def attempts_action_prompt_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the number of attempts to add."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} choosing to add attempts.")
    await query.edit_message_text("الرجاء إرسال عدد المحاولات التي تريد إضافتها لهذا المستخدم (رقم موجب):")
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
    logger.info(f"Admin {update.effective_user.id} entered {attempts_to_add} attempts to add for user {user_id_str} in group {group_id_str}")

    if not group_id_str or not user_id_str:
        logger.error("Group/User ID missing from user_data in attempts_action_receive_add.")
        await update.message.reply_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Reload data before modifying
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    
    if group_id_str not in current_user_attempts_data or user_id_str not in current_user_attempts_data[group_id_str]:
        await update.message.reply_text("خطأ: لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    default_attempts = current_config_data.get("default_copy_attempts", 3)
    current_attempts = current_user_attempts_data[group_id_str][user_id_str].get("attempts_left", default_attempts)
    # Ensure current_attempts is an integer
    if not isinstance(current_attempts, int):
        current_attempts = default_attempts 
        
    new_total = current_attempts + attempts_to_add
    current_user_attempts_data[group_id_str][user_id_str]["attempts_left"] = new_total
    # Ensure user is not banned if attempts are added
    current_user_attempts_data[group_id_str][user_id_str]["is_banned"] = False 
    save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
    logger.info(f"Added {attempts_to_add} attempts for user {user_id_str} in group {group_id_str}. New total: {new_total}")
    
    user_name = current_user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    await update.message.reply_text(f"تم إضافة {attempts_to_add} محاولة للمستخدم *{escape_md(user_name)}*. الرصيد الحالي: *{new_total}* محاولات.", parse_mode=ParseMode.MARKDOWN_V2)
    
    # End conversation
    context.user_data.clear()
    await update.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin")
    return ConversationHandler.END

async def attempts_action_prompt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter the number of attempts to remove."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} choosing to remove attempts.")
    await query.edit_message_text("الرجاء إرسال عدد المحاولات التي تريد حذفها من هذا المستخدم (رقم موجب):")
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
    logger.info(f"Admin {update.effective_user.id} entered {attempts_to_remove} attempts to remove for user {user_id_str} in group {group_id_str}")

    if not group_id_str or not user_id_str:
        logger.error("Group/User ID missing from user_data in attempts_action_receive_remove.")
        await update.message.reply_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Reload data before modifying
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})

    if group_id_str not in current_user_attempts_data or user_id_str not in current_user_attempts_data[group_id_str]:
        await update.message.reply_text("خطأ: لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    default_attempts = current_config_data.get("default_copy_attempts", 3)
    current_attempts = current_user_attempts_data[group_id_str][user_id_str].get("attempts_left", default_attempts)
    # Ensure current_attempts is an integer
    if not isinstance(current_attempts, int):
        current_attempts = default_attempts
        
    # Ensure attempts don't go below zero
    new_total = max(0, current_attempts - attempts_to_remove)
    current_user_attempts_data[group_id_str][user_id_str]["attempts_left"] = new_total
    save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
    logger.info(f"Removed {attempts_to_remove} attempts for user {user_id_str} in group {group_id_str}. New total: {new_total}")
    
    user_name = current_user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    await update.message.reply_text(f"تم حذف {attempts_to_remove} محاولة من المستخدم *{escape_md(user_name)}*. الرصيد الحالي: *{new_total}* محاولات.", parse_mode=ParseMode.MARKDOWN_V2)
    
    # End conversation
    context.user_data.clear()
    await update.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin")
    return ConversationHandler.END

async def attempts_action_ban_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the ban status for the selected user."""
    query = update.callback_query
    group_id_str = context.user_data.get("attempts_group_id")
    user_id_str = context.user_data.get("attempts_user_id")
    await query.answer()
    logger.info(f"Admin {query.from_user.id} toggling ban status for user {user_id_str} in group {group_id_str}")

    if not group_id_str or not user_id_str:
        logger.error("Group/User ID missing from user_data in attempts_action_ban_toggle.")
        await query.edit_message_text("خطأ: بيانات غير مكتملة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Reload data before modifying
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})

    if group_id_str not in current_user_attempts_data or user_id_str not in current_user_attempts_data[group_id_str]:
        await query.edit_message_text("خطأ: لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء البدء من جديد /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    current_ban_status = current_user_attempts_data[group_id_str][user_id_str].get("is_banned", False)
    new_ban_status = not current_ban_status
    current_user_attempts_data[group_id_str][user_id_str]["is_banned"] = new_ban_status
    # Reset attempts to 0 if banned?
    if new_ban_status:
        current_user_attempts_data[group_id_str][user_id_str]["attempts_left"] = 0
        
    save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
    logger.info(f"Toggled ban status for user {user_id_str} in group {group_id_str} to {new_ban_status}")

    user_name = current_user_attempts_data[group_id_str][user_id_str].get("name", f"User {user_id_str}")
    status_text = "محظور" if new_ban_status else "نشط"
    await query.edit_message_text(f"تم تغيير حالة المستخدم *{escape_md(user_name)}* إلى: *{status_text}*.", parse_mode=ParseMode.MARKDOWN_V2)

    # End conversation
    context.user_data.clear()
    await query.message.reply_text("للعودة لقائمة الإدارة، استخدم /admin")
    return ConversationHandler.END

# --- Admin Management Callbacks --- 
async def manage_admins_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the admin management menu."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing admin management menu.")
    
    # Reload config data to show current admins
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    current_admins = current_config_data.get("admins", [INITIAL_ADMIN_ID])
    
    admin_list_parts = []
    for admin_id in current_admins:
        label = "(أولي)" if admin_id == INITIAL_ADMIN_ID else ""
        admin_list_parts.append(f"- `{admin_id}` {label}")
        
    if not admin_list_parts:
        admin_list_str = "(لا يوجد مسؤولون حالياً - خطأ محتمل!)"
    else:
        admin_list_str = "\n".join(admin_list_parts)
        
    text = f"إدارة المسؤولين:\n*المسؤولون الحاليون:*\n{admin_list_str}"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admins_add")],
        # Allow deleting if more than 1 admin exists
        [InlineKeyboardButton("➖ حذف مسؤول", callback_data="admins_delete")] if len(current_admins) > 1 else [],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]
    ]
    keyboard = [row for row in keyboard if row] # Remove empty rows
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    return MANAGE_ADMINS_MENU

async def admins_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts for the User ID of the new admin."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} choosing to add admin.")
    await query.edit_message_text("الرجاء إرسال رقم معرّف المستخدم (User ID) الذي تريد إضافته كمسؤول.")
    return ADD_ADMIN_ID

async def admins_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the User ID and adds them as an admin."""
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("معرّف المستخدم غير صالح. يجب أن يكون رقماً. حاول مرة أخرى أو /cancel للإلغاء.")
        return ADD_ADMIN_ID
        
    logger.info(f"Admin {update.effective_user.id} entered new admin ID: {new_admin_id}")

    # Reload config before modifying
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    current_admins = current_config_data.get("admins", [INITIAL_ADMIN_ID])
    
    if new_admin_id in current_admins:
        await update.message.reply_text("هذا المستخدم هو مسؤول بالفعل.")
    else:
        current_admins.append(new_admin_id)
        current_config_data["admins"] = current_admins
        save_json(CONFIG_FILE, current_config_data)
        logger.info(f"Added {new_admin_id} to admin list. New list: {current_admins}")
        await update.message.reply_text(f"تمت إضافة المستخدم `{new_admin_id}` كمسؤول بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)

    # Go back to admin management menu
    # Need to simulate callback query. Let's end conversation.
    context.user_data.clear()
    await update.message.reply_text("للعودة لقائمة إدارة المسؤولين، استخدم /admin واختر إدارة المسؤولين.")
    return ConversationHandler.END

async def admins_delete_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a list of admins to select for deletion."""
    query = update.callback_query
    await query.answer()
    logger.info(f"Admin {query.from_user.id} accessing delete admin selection.")
    
    # Reload config data
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    current_admins = current_config_data.get("admins", [INITIAL_ADMIN_ID])
    admin_requesting_delete = query.from_user.id
    
    # Admins that can be deleted: not the initial admin, and not the user themselves if they are the *only* other admin.
    deletable_admins = []
    can_delete_self = True
    if len(current_admins) <= 1:
         # Cannot delete if only one admin exists (should be initial admin)
         pass
    else:
        # Check if deleting self would leave only the initial admin
        non_initial_admins = [a for a in current_admins if a != INITIAL_ADMIN_ID]
        if admin_requesting_delete in non_initial_admins and len(non_initial_admins) == 1:
            can_delete_self = False # Cannot delete self if only non-initial admin
            
        for admin_id in current_admins:
            if admin_id == INITIAL_ADMIN_ID:
                continue # Cannot delete initial admin
            if admin_id == admin_requesting_delete and not can_delete_self:
                continue # Cannot delete self in this specific case
            deletable_admins.append(admin_id)

    if not deletable_admins:
        await query.edit_message_text("لا يمكن حذف المزيد من المسؤولين (يجب أن يبقى المسؤول الأولي على الأقل، ولا يمكنك حذف نفسك إذا كنت المسؤول الوحيد المتبقي).", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]]))
        return MANAGE_ADMINS_MENU

    keyboard = []
    for admin_id in deletable_admins:
        keyboard.append([InlineKeyboardButton(f"➖ {admin_id}", callback_data=f"deladmin_{admin_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("اختر المسؤول الذي تريد حذفه (لا يمكنك حذف المسؤول الأولي أو نفسك إذا كنت المسؤول الوحيد المتبقي):", reply_markup=reply_markup)
    return DELETE_ADMIN_SELECT

async def admins_delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the selected admin after final checks."""
    query = update.callback_query
    try:
        admin_id_to_delete = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        logger.error(f"Invalid admin delete callback data: {query.data}")
        await query.answer("خطأ في البيانات.", show_alert=True)
        return MANAGE_ADMINS_MENU
        
    await query.answer()
    admin_requesting_delete = query.from_user.id
    logger.info(f"Admin {admin_requesting_delete} attempting to delete admin {admin_id_to_delete}")

    # Reload config data for final checks
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    current_admins = current_config_data.get("admins", [INITIAL_ADMIN_ID])
    
    # --- Final Deletion Checks --- 
    can_delete = True
    error_message = None
    
    if admin_id_to_delete == INITIAL_ADMIN_ID:
        can_delete = False
        error_message = "لا يمكن حذف المسؤول الأولي."
    elif len(current_admins) <= 1:
        can_delete = False
        error_message = "لا يمكن حذف المسؤول الوحيد المتبقي."
    elif admin_id_to_delete not in current_admins:
         can_delete = False
         error_message = "خطأ: المسؤول المحدد للحذف لم يعد موجوداً."
    else:
        # Check if deleting this admin leaves only the initial admin
        non_initial_admins = [a for a in current_admins if a != INITIAL_ADMIN_ID]
        if admin_id_to_delete in non_initial_admins and len(non_initial_admins) == 1:
             # This is the only non-initial admin. Can they be deleted?
             # Yes, unless they are the one requesting the deletion.
             if admin_id_to_delete == admin_requesting_delete:
                 can_delete = False
                 error_message = "لا يمكنك حذف نفسك إذا كنت المسؤول الوحيد (غير الأولي) المتبقي."

    # --- Execute Deletion --- 
    if can_delete:
        current_admins.remove(admin_id_to_delete)
        current_config_data["admins"] = current_admins
        save_json(CONFIG_FILE, current_config_data)
        logger.info(f"Admin {admin_requesting_delete} successfully deleted admin {admin_id_to_delete}. New list: {current_admins}")
        await query.edit_message_text(f"تم حذف المسؤول `{admin_id_to_delete}` بنجاح.", parse_mode=ParseMode.MARKDOWN_V2)
    else:
        logger.warning(f"Deletion of admin {admin_id_to_delete} denied for admin {admin_requesting_delete}. Reason: {error_message}")
        await query.edit_message_text(error_message)

    # Go back to admin management menu
    # Need to simulate callback query...
    context.user_data.clear()
    await query.message.reply_text("للعودة لقائمة إدارة المسؤولين، استخدم /admin واختر إدارة المسؤولين.")
    return ConversationHandler.END

# --- Copy Code Callback --- 
async def copy_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Copy Code' button press in the group message."""
    query = update.callback_query
    user = query.from_user
    user_id_str = str(user.id)
    user_name = user.full_name # Get current name
    logger.info(f"User {user.id} ({user_name}) pressed 'Copy Code' button.")

    try:
        # Extract group_id from callback data (e.g., "copy_code_-100123456")
        group_id_str = query.data.split('_', 2)[-1]
        if not group_id_str.startswith('-') or not group_id_str[1:].isdigit():
             raise ValueError("Invalid group ID format in callback data")
        logger.debug(f"Parsed group_id {group_id_str} from callback data '{query.data}'")
    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing group_id from callback_data '{query.data}': {e}")
        await query.answer("حدث خطأ في معالجة الطلب (معرف المجموعة غير صالح).", show_alert=True)
        return

    # Reload all necessary data inside the callback for freshness
    current_groups_data = load_json(GROUPS_FILE, {})
    current_user_attempts_data = load_json(USER_ATTEMPTS_FILE, {})
    current_config_data = load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})

    group_info = current_groups_data.get(group_id_str)
    if not group_info:
        logger.warning(f"User {user.id} clicked copy for non-configured group {group_id_str}")
        await query.answer("خطأ: إعدادات هذه المجموعة غير موجودة أو تم حذفها.", show_alert=True)
        return

    # --- User Attempts and Ban Check --- 
    default_attempts = current_config_data.get("default_copy_attempts", 3)
    
    # Initialize group in attempts data if it doesn't exist
    if group_id_str not in current_user_attempts_data:
        current_user_attempts_data[group_id_str] = {}
        logger.debug(f"Initialized attempts data for new group {group_id_str}")
        
    # Initialize user in group's attempts data if they don't exist
    if user_id_str not in current_user_attempts_data[group_id_str]:
        current_user_attempts_data[group_id_str][user_id_str] = {
            "attempts_left": default_attempts,
            "is_banned": False,
            "name": user_name # Store name on first interaction
        }
        logger.info(f"Initialized attempts data for new user {user_id_str} in group {group_id_str}")
        # Save immediately after initializing user
        save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
        
    user_data = current_user_attempts_data[group_id_str][user_id_str]
    
    # Update user name if it has changed since last stored
    if user_data.get("name") != user_name:
        logger.info(f"Updating name for user {user_id_str} from '{user_data.get('name')}' to '{user_name}'")
        user_data["name"] = user_name
        # Save needed if name changes
        save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)

    # Check ban status
    if user_data.get("is_banned", False):
        logger.warning(f"Banned user {user.id} tried to copy code for group {group_id_str}")
        await query.answer("عذراً، أنت محظور من استخدام هذا الزر في هذه المجموعة.", show_alert=True)
        return

    # Check attempts
    # Ensure attempts_left is correctly loaded or defaulted
    attempts_left = user_data.get("attempts_left") 
    if attempts_left is None or not isinstance(attempts_left, int):
        logger.warning(f"Attempts data missing or invalid for user {user_id_str} in group {group_id_str}. Resetting to default {default_attempts}.")
        attempts_left = default_attempts
        user_data["attempts_left"] = attempts_left # Fix data
        # Save needed if data was fixed
        save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
        
    if attempts_left <= 0:
        logger.warning(f"User {user.id} has no attempts left for group {group_id_str}")
        await query.answer("عذراً، لقد استنفدت محاولاتك المتاحة لنسخ الرمز.", show_alert=True)
        return

    # --- Generate and Send Code --- 
    totp_secret = group_info.get("secret")
    if not totp_secret:
        logger.error(f"TOTP secret is missing for group {group_id_str}!")
        await query.answer("خطأ فادح: المفتاح السري مفقود لهذه المجموعة. يرجى إبلاغ المسؤول.", show_alert=True)
        return
        
    code = get_totp_code(totp_secret)

    if code is None:
        logger.error(f"Failed to generate TOTP for group {group_id_str} (Secret: {totp_secret[:4]}...). Check secret validity.")
        await query.answer("حدث خطأ أثناء توليد الرمز. قد يكون المفتاح السري غير صالح. يرجى إبلاغ المسؤول.", show_alert=True)
        return

    # Decrement attempts and save
    user_data["attempts_left"] = attempts_left - 1
    save_json(USER_ATTEMPTS_FILE, current_user_attempts_data)
    logger.info(f"Decremented attempts for user {user.id} in group {group_id_str}. Remaining: {user_data['attempts_left']}")
    attempts_remaining_text = f"لديك {user_data['attempts_left']} محاولات متبقية."

    # Send private message with the code
    try:
        message_text = (
            f"🔐 *{escape_md('رمز التحقق الخاص بك')}*\n\n"
            f"🔑 `{escape_md(code)}`\n\n"
            f"🔄 {escape_md(attempts_remaining_text)}\n"
            f"⚠️ *{escape_md('هذا الرمز صالح لمدة 30 ثانية فقط.')}*"
        )
        await context.bot.send_message(
            chat_id=user.id, 
            text=message_text, 
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"Sent TOTP code privately to user {user.id} for group {group_id_str}")
        # Answer the callback query *after* successfully sending the message
        await query.answer("تم إرسال الرمز بنجاح إلى رسائلك الخاصة.")
    except TelegramError as e:
        logger.error(f"Failed to send private message to user {user.id}: {e}")
        # Answer the callback query with an error message
        await query.answer("فشل إرسال الرمز إلى الخاص. قد تحتاج إلى بدء محادثة مع البوت أولاً.", show_alert=True)
        # Should we revert the attempt decrement if PM fails? Maybe not, user still tried.
    except Exception as e:
        logger.exception(f"Unexpected error sending private message to user {user.id}: {e}")
        await query.answer("حدث خطأ غير متوقع أثناء إرسال الرمز.", show_alert=True)

# --- Error Handler --- 
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs errors encountered by the Bot."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Handle specific errors like Conflict (multiple instances)
    if isinstance(context.error, Conflict):
         logger.critical("Conflict error detected! Multiple bot instances might be running.")
         # Try notifying the initial admin
         try:
             # Use triple quotes for multi-line f-string
             conflict_message = f"""⚠️ *خطأ تعارض خطير \(Conflict Error\)!*

يبدو أن هناك أكثر من نسخة واحدة من البوت \({escape_md(BOT_NAME)}\) تعمل في نفس الوقت\. 
الرجاء التأكد من إيقاف جميع النسخ الإضافية فوراً لتجنب المشاكل\.

الخطأ: `{escape_md(str(context.error))}`"""
             
             await context.bot.send_message(
                 chat_id=INITIAL_ADMIN_ID, 
                 text=conflict_message,
                 parse_mode=ParseMode.MARKDOWN_V2
             )
             logger.info(f"Sent conflict warning message to initial admin {INITIAL_ADMIN_ID}")
         except Exception as e:
             logger.error(f"Failed to send conflict error message to admin {INITIAL_ADMIN_ID}: {e}")
    
    # You could add more specific error handling here if needed

# --- Main Function --- 
def main():
    """Starts the bot."""
    logger.info(f"Starting bot {BOT_NAME}...")

    # Create persistence object
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

    # Build application with default JobQueue enabled
    # The default builder enables JobQueue
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    
    # --- Setup Conversation Handler for Admin tasks --- 
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(manage_groups_menu, pattern="^admin_manage_groups$"),
                CallbackQueryHandler(manual_send_select_group, pattern="^admin_manual_send$"),
                CallbackQueryHandler(manage_format_select_group, pattern="^admin_manage_format$"),
                CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"),
                CallbackQueryHandler(manage_attempts_select_group, pattern="^admin_manage_attempts$"),
                CallbackQueryHandler(manage_admins_menu, pattern="^admin_manage_admins$"),
                # Add handlers for any other main menu options here
            ],
            # Group Management States
            MANAGE_GROUPS_MENU: [
                CallbackQueryHandler(groups_add_prompt_id, pattern="^groups_add$"),
                CallbackQueryHandler(groups_edit_select, pattern="^groups_edit$"), # Placeholder
                CallbackQueryHandler(groups_delete_select, pattern="^groups_delete$"),
                CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            ADD_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_add_receive_id)],
            ADD_GROUP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, groups_add_receive_secret)],
            DELETE_GROUP_SELECT: [
                CallbackQueryHandler(groups_delete_confirm, pattern="^delgroup_.+$"),
                CallbackQueryHandler(manage_groups_menu, pattern="^admin_manage_groups$"), # Back button
            ],
            DELETE_GROUP_CONFIRM: [
                CallbackQueryHandler(groups_delete_execute, pattern="^delete_group_(yes|no)$"),
            ],
            # Edit Group States (Add if implementing)
            # EDIT_GROUP_SELECT: [...],
            # EDIT_GROUP_OPTION: [...],
            # EDIT_GROUP_NEW_ID: [...],
            # EDIT_GROUP_NEW_SECRET: [...],
            
            # Manual Send State
            MANUAL_SEND_SELECT_GROUP: [
                 CallbackQueryHandler(manual_send_execute, pattern="^manualsend_.+$"),
                 CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            # Format Management States
            MANAGE_FORMAT_SELECT_GROUP: [
                CallbackQueryHandler(manage_format_options, pattern="^formatgroup_.+$"),
                CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            EDIT_GROUP_OPTION: [ # Reusing state for format/tz options
                CallbackQueryHandler(format_set_options, pattern="^format_change_fmt$"),
                CallbackQueryHandler(format_set_timezone_prompt, pattern="^format_change_tz$"),
                CallbackQueryHandler(manage_format_select_group, pattern="^admin_manage_format$"), # Back button
            ],
            SET_FORMAT: [
                CallbackQueryHandler(format_set_execute, pattern="^setformat_(1|2|3)$"),
                CallbackQueryHandler(manage_format_options, pattern="^formatgroup_.+$"), # Back button needs group id
            ],
            SET_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, format_set_timezone_receive)],
            
            # Interval Management States
            MANAGE_INTERVAL_SELECT_GROUP: [
                CallbackQueryHandler(manage_interval_options, pattern="^intervalgroup_.+$"),
                CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            SET_INTERVAL_OPTIONS: [
                 CallbackQueryHandler(interval_set_execute, pattern="^setinterval_\d+$"),
                 CallbackQueryHandler(manage_interval_select_group, pattern="^admin_manage_interval$"), # Back button
            ],
            # SET_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, interval_set_receive)], # If using text input

            # Attempts Management States
            MANAGE_ATTEMPTS_SELECT_GROUP: [
                CallbackQueryHandler(manage_attempts_select_user, pattern="^attemptsgroup_.+$"),
                CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            MANAGE_ATTEMPTS_SELECT_USER: [
                CallbackQueryHandler(manage_attempts_action_menu, pattern="^attemptsuser_.+$"),
                CallbackQueryHandler(manage_attempts_select_group, pattern="^admin_manage_attempts$"), # Back button
            ],
            MANAGE_ATTEMPTS_ACTION: [
                CallbackQueryHandler(attempts_action_prompt_add, pattern="^attempts_action_add$"),
                CallbackQueryHandler(attempts_action_prompt_remove, pattern="^attempts_action_remove$"),
                CallbackQueryHandler(attempts_action_ban_toggle, pattern="^attempts_action_ban_toggle$"),
                CallbackQueryHandler(manage_attempts_select_user, pattern="^attemptsgroup_.+$"), # Back button needs group id
            ],
            ADD_ATTEMPTS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, attempts_action_receive_add)],
            REMOVE_ATTEMPTS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, attempts_action_receive_remove)],
            
            # Admin Management States
            MANAGE_ADMINS_MENU: [
                CallbackQueryHandler(admins_add_prompt, pattern="^admins_add$"),
                CallbackQueryHandler(admins_delete_select, pattern="^admins_delete$"),
                CallbackQueryHandler(back_to_main_admin_menu, pattern="^admin_back_main$"),
            ],
            ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admins_add_receive)],
            DELETE_ADMIN_SELECT: [
                CallbackQueryHandler(admins_delete_execute, pattern="^deladmin_\d+$"),
                CallbackQueryHandler(manage_admins_menu, pattern="^admin_manage_admins$"), # Back button
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("admin", admin_command), # Allow restarting admin command
            # Add a fallback for unexpected callbacks in conversation?
            CallbackQueryHandler(cancel_conversation_callback) # Generic callback cancel
            ],
        persistent=True, # Make conversation state persistent
        name="admin_conversation" # Name for persistence
    )

    application.add_handler(conv_handler)

    # --- Add other handlers --- 
    application.add_handler(CommandHandler("start", start_command))
    # Handler for the "Copy Code" button clicks (outside the conversation)
    application.add_handler(CallbackQueryHandler(copy_code_callback, pattern="^copy_code_.+$"))

    # Error handler
    application.add_error_handler(error_handler)

    # --- Schedule initial jobs --- 
    # Schedule jobs for existing groups on startup
    jq = application.job_queue
    if jq:
        logger.info("Scheduling jobs for existing groups on startup...")
        current_groups_data = load_json(GROUPS_FILE, {}) # Load fresh data
        scheduled_count = 0
        for group_id_str, group_info in current_groups_data.items():
            interval = group_info.get("interval")
            if interval and isinstance(interval, int) and interval > 0:
                # Pass application.job_queue directly
                schedule_group_message_job(application, group_id_str, interval)
                scheduled_count += 1
            else:
                logger.info(f"Skipping job scheduling for group {group_id_str} (interval: {interval})")
        logger.info(f"Scheduled {scheduled_count} jobs on startup.")
    else:
        logger.warning("JobQueue is not available. Periodic messages will not work.")
        
    # Set bot commands
    async def post_init(app: Application):
        logger.info("Setting bot commands...")
        await app.bot.set_my_commands([
            BotCommand("start", "بدء استخدام البوت"),
            BotCommand("admin", "فتح قائمة إدارة المسؤولين")
        ])
        logger.info("Bot commands set.")

    # Run post-initialization tasks
    application.post_init = post_init

    # Run the bot
    logger.info("Starting bot polling...")
    application.run_polling()

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current conversation."""
    user = update.effective_user
    logger.info(f"User {user.id} cancelled the conversation.")
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية الحالية. يمكنك البدء من جديد باستخدام /admin.")
    return ConversationHandler.END

async def cancel_conversation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current conversation initiated by a callback query."""
    query = update.callback_query
    user = query.from_user
    logger.info(f"User {user.id} cancelled the conversation via callback {query.data}.")
    context.user_data.clear()
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية الحالية. يمكنك البدء من جديد باستخدام /admin.")
    return ConversationHandler.END

if __name__ == "__main__":
    # Ensure data files exist before starting
    load_json(CONFIG_FILE, {"admins": [INITIAL_ADMIN_ID], "default_copy_attempts": 3})
    load_json(GROUPS_FILE, {})
    load_json(USER_ATTEMPTS_FILE, {})
    main()


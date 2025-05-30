# M3.00
import logging
import datetime
import pytz
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

import config
import database as db
import keyboards as kb
import totp_utils

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Conversation states
(ASK_GROUP_ID, ASK_TOTP_SECRET, ASK_INTERVAL, ASK_FORMAT_TZ, ASK_MAX_ATTEMPTS,
 ASK_USER_TO_MANAGE, ASK_ATTEMPTS_TO_ADD, ASK_ATTEMPTS_TO_REMOVE,
 ASK_ADMIN_ID_TO_ADD, ASK_ADMIN_ID_TO_REMOVE, EDIT_GROUP_SECRET,
 ASK_DEFAULT_MAX_ATTEMPTS) = range(12)

# --- Helper Functions ---
def is_admin(update: Update) -> bool:
    """Checks if the user initiating the update is an admin."""
    user_id = update.effective_user.id
    return db.is_admin(user_id)

def format_time_message(group_settings):
    """Formats the time part of the periodic message based on group settings."""
    now_utc = datetime.datetime.now(pytz.utc)
    try:
        group_tz = pytz.timezone(group_settings["timezone"])
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone {group_settings['timezone']} for group {group_settings['group_id']}. Defaulting to GMT.")
        group_tz = pytz.utc # Default to GMT/UTC if invalid

    now_local = now_utc.astimezone(group_tz)
    interval_minutes = group_settings["interval_minutes"]
    next_code_time_local = now_local + datetime.timedelta(minutes=interval_minutes)

    # Format times in 12-hour format with seconds AM/PM
    time_format = "%I:%M:%S %p"
    current_time_str = now_local.strftime(time_format)
    next_code_time_str = next_code_time_local.strftime(time_format)

    message_format = group_settings["message_format"]
    interval_str = f"{interval_minutes} دقيقة"
    # Adjust interval string for hours/days if needed (similar to keyboard logic)
    if interval_minutes == 60:
        interval_str = "ساعة"
    elif interval_minutes == 180:
        interval_str = "3 ساعات"
    elif interval_minutes == 720:
        interval_str = "12 ساعة"
    elif interval_minutes == 1440:
        interval_str = "24 ساعة"

    if message_format == 1:
        return f"\n:Next code at: {next_code_time_str}"
    elif message_format == 2:
        return f"\nNext code in: {interval_str}\nNext code at: {next_code_time_str}"
    elif message_format == 3:
        return f"\nNext code in: {interval_str}\nCorrect Time: {current_time_str}\nNext Code at: {next_code_time_str}"
    else:
        # Default to format 1 if invalid
        return f"\n:Next code at: {next_code_time_str}"

async def send_periodic_code_message(context: ContextTypes.DEFAULT_TYPE):
    """Sends the message with the 'Copy Code' button to the group."""
    job = context.job
    group_id = job.data["group_id"]
    logger.info(f"Running job for group {group_id}")

    group_settings = db.get_group_settings(group_id)
    if not group_settings or not group_settings["is_active"]:
        logger.warning(f"Job for group {group_id} found inactive or deleted group. Removing job.")
        job.schedule_removal()
        # Also clear job_id from DB if it exists
        if group_settings:
            db.update_group_job_id(group_id, None)
        return

    time_message = format_time_message(group_settings)
    message_text = f"🔐 2FA Verification Code{time_message}"
    reply_markup = kb.request_code_keyboard(group_id)

    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML # Use HTML if needed for formatting, otherwise default
        )
        logger.info(f"Sent periodic message to group {group_id}")
    except TelegramError as e:
        logger.error(f"Failed to send message to group {group_id}: {e}")
        # Consider deactivating the group or notifying admin if persistent errors occur
        if "bot was kicked" in str(e) or "chat not found" in str(e) or "group chat was deleted" in str(e):
            logger.warning(f"Bot seems to be removed from group {group_id}. Deactivating and removing job.")
            db.update_group_status(group_id, False)
            db.update_group_job_id(group_id, None)
            job.schedule_removal()
        # Handle other specific errors like flood control etc.

def schedule_group_job(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    """Schedules or reschedules the periodic message job for a group."""
    group_settings = db.get_group_settings(group_id)
    if not group_settings:
        logger.error(f"Cannot schedule job for non-existent group {group_id}")
        return

    job_name = f"group_{group_id}_code"
    interval_minutes = group_settings["interval_minutes"]
    job_queue = context.job_queue

    # Remove existing job first, if any
    current_jobs = job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        logger.info(f"Removing existing job {job_name} before rescheduling.")
        job.schedule_removal()
    db.update_group_job_id(group_id, None) # Clear old job ID from DB

    if group_settings["is_active"]:
        # Schedule the new job
        # Run immediately once, then repeat
        job = job_queue.run_repeating(
            send_periodic_code_message,
            interval=datetime.timedelta(minutes=interval_minutes),
            first=datetime.timedelta(seconds=1), # Run almost immediately first time
            name=job_name,
            data={"group_id": group_id}
        )
        # Store the job ID (using job.name as a unique identifier reference)
        # Note: python-telegram-bot's Job doesn't have a persistent unique ID easily accessible
        # We'll use the name as the reference point, assuming only one job per name.
        db.update_group_job_id(group_id, job_name) # Store the job name as reference
        logger.info(f"Scheduled job {job_name} for group {group_id} every {interval_minutes} minutes.")
    else:
        logger.info(f"Group {group_id} is inactive. Job not scheduled.")

def remove_group_job(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    """Removes the scheduled job for a group."""
    job_name = f"group_{group_id}_code"
    job_queue = context.job_queue
    current_jobs = job_queue.get_jobs_by_name(job_name)
    if not current_jobs:
        logger.warning(f"No job found with name {job_name} to remove.")
    else:
        for job in current_jobs:
            logger.info(f"Removing job {job_name} for group {group_id}.")
            job.schedule_removal()
    # Clear job ID from DB regardless
    db.update_group_job_id(group_id, None)

async def load_scheduled_jobs(application: Application):
    """Loads and schedules jobs for all active groups on bot startup."""
    logger.info("Loading scheduled jobs for active groups...")
    groups = db.get_all_groups()
    count = 0
    for group in groups:
        if group["is_active"]:
            schedule_group_job(application, group["group_id"])
            count += 1
    logger.info(f"Loaded and scheduled jobs for {count} active groups.")

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    await update.message.reply_text(
        "أهلاً بك في بوت ChatGPTPlus2FABot!\n"
        "يقوم هذا البوت بإرسال رسالة دورية تحتوي على زر لنسخ رمز المصادقة الثنائية (2FA) الخاص بالمجموعة.\n"
        "للمسؤولين: استخدم الأمر /admin لإدارة إعدادات البوت."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /admin command, showing the main admin menu."""
    if not is_admin(update):
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمسؤولين فقط.")
        return

    await update.message.reply_text(
        "🔑 لوحة تحكم المسؤول:",
        reply_markup=kb.admin_main_keyboard()
    )

# --- Callback Query Handlers ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer() # Answer callback query first
    user_id = query.from_user.id
    data = query.data
    logger.info(f"Callback query received: {data} from user {user_id}")

    # Check if user is admin for admin actions
    admin_actions = ["admin_", "group_", "interval_", "format_", "attempts_"]
    is_admin_action = any(data.startswith(prefix) for prefix in admin_actions)

    if is_admin_action and not db.is_admin(user_id):
        await query.edit_message_text(text="عذراً، ليس لديك صلاحية تنفيذ هذا الإجراء.")
        return

    # --- Admin Main Menu Navigation ---
    if data == "admin_main":
        await query.edit_message_text("🔑 لوحة تحكم المسؤول:", reply_markup=kb.admin_main_keyboard())
    elif data == "admin_close":
        await query.edit_message_text("تم إغلاق لوحة التحكم.")
    elif data == "admin_manage_groups":
        await query.edit_message_text("📊 إدارة المجموعات و TOTP Secret:", reply_markup=kb.manage_groups_keyboard())
    elif data == "admin_manage_interval":
        await query.edit_message_text("⏰ اختر مجموعة لإدارة فترة التكرار:", reply_markup=kb.select_group_for_interval_keyboard())
    elif data == "admin_manage_format":
        await query.edit_message_text("✉️ اختر مجموعة لإدارة شكل الرسالة والتوقيت:", reply_markup=kb.select_group_for_format_keyboard())
    elif data == "admin_manage_attempts":
        await query.edit_message_text("👤 اختر مجموعة لإدارة محاولات المستخدمين:", reply_markup=kb.select_group_for_attempts_keyboard())
    elif data == "admin_manage_admins":
        await query.edit_message_text("👑 إدارة المسؤولين:", reply_markup=kb.manage_admins_keyboard())

    # --- Group Management Flow ---
    elif data == "group_add":
        await query.edit_message_text("➕ إضافة مجموعة جديدة:\nالرجاء إرسال **معرف المجموعة (Group ID)** العددي (يجب أن يبدأ بـ -100 للمجموعات الخارقة). يمكنك الحصول عليه من بوتات مثل @RawDataBot أو @userinfobot.")
        return ASK_GROUP_ID
    elif data == "group_select_edit":
        await query.edit_message_text("✏️ اختر مجموعة لتعديلها:", reply_markup=kb.select_group_keyboard("group_edit_options"))
    elif data == "group_select_delete":
        await query.edit_message_text("➖ اختر مجموعة لحذفها:", reply_markup=kb.select_group_keyboard("group_delete_confirm"))
    elif data.startswith("group_edit_options:"):
        group_id = int(data.split(":")[1])
        await query.edit_message_text(f"🔧 تعديل المجموعة {group_id}:", reply_markup=kb.edit_group_options_keyboard(group_id))
    elif data.startswith("group_edit_secret:"):
        group_id = int(data.split(":")[1])
        context.user_data["current_group_id"] = group_id
        await query.edit_message_text(f"🔑 تعديل TOTP Secret للمجموعة {group_id}:\nالرجاء إرسال الـ TOTP Secret الجديد (بتنسيق Base32).")
        return EDIT_GROUP_SECRET
    elif data.startswith("group_delete_confirm:"):
        group_id = int(data.split(":")[1])
        success, message = db.remove_group(group_id)
        if success:
            remove_group_job(context, group_id) # Remove scheduled job
            logger.info(f"Group {group_id} deleted by admin {user_id}.")
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.select_group_keyboard("group_delete_confirm")) # Refresh list
        else:
            await query.answer(f"❌ فشل الحذف: {message}", show_alert=True)
            await query.edit_message_text("➖ اختر مجموعة لحذفها:", reply_markup=kb.select_group_keyboard("group_delete_confirm")) # Refresh list just in case

    # --- Interval Management Flow ---
    elif data.startswith("interval_select_group:"):
        group_id = int(data.split(":")[1])
        await query.edit_message_text(f"⏰ إدارة فترة التكرار للمجموعة {group_id}:", reply_markup=kb.interval_options_keyboard(group_id))
    elif data.startswith("interval_set:"):
        parts = data.split(":")
        group_id, interval = int(parts[1]), int(parts[2])
        success, message = db.update_group_interval(group_id, interval)
        if success:
            schedule_group_job(context, group_id) # Reschedule with new interval
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.interval_options_keyboard(group_id))
        else:
            await query.answer(f"❌ فشل التحديث: {message}", show_alert=True)
    elif data.startswith("interval_activate:"):
        group_id = int(data.split(":")[1])
        success, message = db.update_group_status(group_id, True)
        if success:
            schedule_group_job(context, group_id) # Schedule the job
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.interval_options_keyboard(group_id))
        else:
            await query.answer(f"❌ فشل التفعيل: {message}", show_alert=True)
    elif data.startswith("interval_deactivate:"):
        group_id = int(data.split(":")[1])
        success, message = db.update_group_status(group_id, False)
        if success:
            remove_group_job(context, group_id) # Remove the job
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.interval_options_keyboard(group_id))
        else:
            await query.answer(f"❌ فشل الإيقاف: {message}", show_alert=True)

    # --- Format/Timing Management Flow ---
    elif data.startswith("format_select_group:"):
        group_id = int(data.split(":")[1])
        await query.edit_message_text(f"✉️ إدارة شكل الرسالة والتوقيت للمجموعة {group_id}:", reply_markup=kb.format_options_keyboard(group_id))
    elif data.startswith("format_set:"):
        parts = data.split(":")
        group_id, format_id = int(parts[1]), int(parts[2])
        group_settings = db.get_group_settings(group_id)
        current_tz = group_settings["timezone"] if group_settings else config.DEFAULT_TIMEZONE
        success, message = db.update_group_message_format(group_id, format_id, current_tz)
        if success:
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.format_options_keyboard(group_id))
        else:
            await query.answer(f"❌ فشل التحديث: {message}", show_alert=True)
    elif data.startswith("format_set_tz:"):
        parts = data.split(":")
        group_id, timezone = int(parts[1]), parts[2]
        group_settings = db.get_group_settings(group_id)
        current_format = group_settings["message_format"] if group_settings else config.DEFAULT_MESSAGE_FORMAT
        success, message = db.update_group_message_format(group_id, current_format, timezone)
        if success:
            await query.edit_message_text(f"✅ {message}", reply_markup=kb.format_options_keyboard(group_id))
        else:
            await query.answer(f"❌ فشل التحديث: {message}", show_alert=True)

    # --- User Attempt Management Flow ---
    elif data.startswith("attempts_select_group:"):
        group_id = int(data.split(":")[1])
        context.user_data["current_group_id"] = group_id # Store for pagination/user selection
        await query.edit_message_text(f"👤 إدارة محاولات المستخدمين للمجموعة {group_id}:", reply_markup=kb.select_user_for_attempts_keyboard(group_id, page=1))
    elif data.startswith("attempts_user_page:"):
        parts = data.split(":")
        group_id, page = int(parts[1]), int(parts[2])
        context.user_data["current_group_id"] = group_id
        await query.edit_message_text(f"👤 إدارة محاولات المستخدمين للمجموعة {group_id} (صفحة {page}):", reply_markup=kb.select_user_for_attempts_keyboard(group_id, page=page))
    elif data.startswith("attempts_select_user:"):
        parts = data.split(":")
        group_id, target_user_id = int(parts[1]), int(parts[2])
        context.user_data["current_group_id"] = group_id
        context.user_data["target_user_id"] = target_user_id
        # Fetch username if possible
        user_info = f"المستخدم {target_user_id}"
        try:
            chat = await context.bot.get_chat(target_user_id)
            user_info = f"المستخدم {chat.full_name or chat.username} ({target_user_id})"
        except Exception as e:
            logger.warning(f"Could not fetch user info for {target_user_id}: {e}")
        await query.edit_message_text(f"🔧 إدارة محاولات {user_info} في المجموعة {group_id}:", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))
    elif data.startswith("attempts_add:"):
        parts = data.split(":")
        group_id, target_user_id = int(parts[1]), int(parts[2])
        context.user_data["current_group_id"] = group_id
        context.user_data["target_user_id"] = target_user_id
        await query.edit_message_text(f"➕ كم عدد المحاولات التي ترغب بإضافتها للمستخدم {target_user_id} في المجموعة {group_id}؟ الرجاء إرسال رقم.")
        return ASK_ATTEMPTS_TO_ADD
    elif data.startswith("attempts_remove:"):
        parts = data.split(":")
        group_id, target_user_id = int(parts[1]), int(parts[2])
        context.user_data["current_group_id"] = group_id
        context.user_data["target_user_id"] = target_user_id
        await query.edit_message_text(f"➖ كم عدد المحاولات التي ترغب بحذفها من المستخدم {target_user_id} في المجموعة {group_id}؟ الرجاء إرسال رقم.")
        return ASK_ATTEMPTS_TO_REMOVE
    elif data.startswith("attempts_ban:"):
        parts = data.split(":")
        group_id, target_user_id = int(parts[1]), int(parts[2])
        success = db.ban_user(target_user_id, group_id)
        if success:
            await query.answer("✅ تم حظر المستخدم بنجاح.")
            await query.edit_message_text(f"🔧 إدارة محاولات المستخدم {target_user_id} في المجموعة {group_id}:", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))
        else:
            await query.answer("❌ فشل حظر المستخدم.", show_alert=True)
    elif data.startswith("attempts_unban:"):
        parts = data.split(":")
        group_id, target_user_id = int(parts[1]), int(parts[2])
        success = db.unban_user(target_user_id, group_id)
        if success:
            await query.answer("✅ تم إلغاء حظر المستخدم بنجاح.")
            await query.edit_message_text(f"🔧 إدارة محاولات المستخدم {target_user_id} في المجموعة {group_id}:", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))
        else:
            await query.answer("❌ فشل إلغاء حظر المستخدم.", show_alert=True)
    elif data.startswith("attempts_set_default:"):
        group_id = int(data.split(":")[1])
        context.user_data["current_group_id"] = group_id
        group_settings = db.get_group_settings(group_id)
        current_default = group_settings["max_attempts"] if group_settings else config.DEFAULT_MAX_ATTEMPTS
        await query.edit_message_text(f"⚙️ تعديل الحد الافتراضي للمحاولات للمجموعة {group_id} (الحالي: {current_default}).\nالرجاء إرسال العدد الجديد للمحاولات الافتراضية (سيتم تطبيقه على المستخدمين الجدد أو عند إعادة التعيين).")
        return ASK_DEFAULT_MAX_ATTEMPTS

    # --- Admin Management Flow ---
    elif data == "admin_add":
        await query.edit_message_text("➕ إضافة مسؤول جديد:\nالرجاء إرسال **معرف المستخدم (User ID)** العددي للمسؤول الجديد.")
        return ASK_ADMIN_ID_TO_ADD
    elif data == "admin_select_remove":
        await query.edit_message_text("➖ إزالة مسؤول:\nاختر المسؤول الذي ترغب بإزالته (لا يمكن إزالة المسؤول الأولي):", reply_markup=kb.select_admin_to_remove_keyboard())
    elif data.startswith("admin_remove:"):
        admin_id_to_remove = int(data.split(":")[1])
        success, message = db.remove_admin(admin_id_to_remove)
        if success:
            logger.info(f"Admin {admin_id_to_remove} removed by admin {user_id}.")
            await query.answer(f"✅ {message}")
            await query.edit_message_text("👑 إدارة المسؤولين:", reply_markup=kb.manage_admins_keyboard()) # Refresh list
        else:
            await query.answer(f"❌ فشل الإزالة: {message}", show_alert=True)
            # Refresh keyboard in case of error
            await query.edit_message_text("➖ إزالة مسؤول:", reply_markup=kb.select_admin_to_remove_keyboard())

    # --- Copy Code Action ---
    elif data.startswith("copy_code:"):
        group_id = int(data.split(":")[1])
        requesting_user_id = query.from_user.id
        logger.info(f"User {requesting_user_id} requested code for group {group_id}")

        group_settings = db.get_group_settings(group_id)
        if not group_settings:
            await query.answer("❌ خطأ: المجموعة غير موجودة أو غير مهيأة.", show_alert=True)
            return

        attempts_left, is_banned = db.get_user_attempts(requesting_user_id, group_id)

        if is_banned:
            await query.answer("🚫 أنت محظور من استخدام هذا الزر لهذه المجموعة.", show_alert=True)
            logger.warning(f"Banned user {requesting_user_id} attempted to get code for group {group_id}.")
            return

        if attempts_left <= 0:
            await query.answer(f"⚠️ لقد استنفدت محاولاتك ({group_settings['max_attempts']}) لنسخ الرمز لهذه المجموعة.", show_alert=True)
            logger.warning(f"User {requesting_user_id} has no attempts left for group {group_id}.")
            return

        # Generate TOTP code
        totp_secret = group_settings["totp_secret"]
        code = totp_utils.generate_totp_code(totp_secret)
        time_remaining = totp_utils.get_time_remaining()

        if code is None:
            await query.answer("❌ خطأ: لم يتمكن البوت من توليد الرمز. قد يكون الـ Secret غير صحيح.", show_alert=True)
            logger.error(f"Failed to generate TOTP code for group {group_id}. Check secret.")
            return

        # Decrement attempt count
        db.decrement_user_attempt(requesting_user_id, group_id)
        attempts_left -= 1 # Update local count for the message

        # Send code via private message
        code_message = (
            f"🔑 رمز المصادقة الخاص بالمجموعة {group_id}:\n\n"
            f"`{code}`\n\n"
            f"⚠️ هذا الرمز صالح لمدة {time_remaining} ثانية فقط.\n"
            f"🔄 المحاولات المتبقية لك: {attempts_left}"
        )
        try:
            await context.bot.send_message(
                chat_id=requesting_user_id,
                text=code_message,
                parse_mode=ParseMode.MARKDOWN_V2 # Use MarkdownV2 for copyable code block
            )
            await query.answer("✅ تم إرسال الرمز إلى رسائلك الخاصة.")
            logger.info(f"Sent code to user {requesting_user_id} for group {group_id}. Attempts left: {attempts_left}")
        except TelegramError as e:
            await query.answer("❌ فشل إرسال الرمز. هل بدأت محادثة خاصة مع البوت؟", show_alert=True)
            logger.error(f"Failed to send private message to user {requesting_user_id}: {e}")
            # Rollback attempt decrement? Maybe not, the attempt was made.

    # --- No Operation ---


    elif data == "no_op":
        await query.answer() # Do nothing, just acknowledge the button press

    else:
        logger.warning(f"Unhandled callback query data: {data}")
        await query.answer("حدث خطأ غير متوقع.")

    # Return None to signal the conversation handler (if any) that we are not changing state here
    return None

# --- Conversation Handlers ---

# --- Add Group Conversation ---
async def ask_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # This state is entered from the button_callback
    # The prompt is already sent by the button_callback
    return ASK_GROUP_ID

async def ask_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_id_text = update.message.text.strip()
    try:
        # Validate Group ID format (must be integer, usually negative for groups/supergroups)
        group_id = int(group_id_text)
        if not group_id_text.startswith("-"):
             await update.message.reply_text(
                "⚠️ يبدو أن معرف المجموعة غير صحيح. عادةً ما يبدأ بـ `-` للمجموعات. الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء."
            )
             return ASK_GROUP_ID
        # Optional: Try to get chat info to verify it's a group the bot is in?
        # This might require the bot to be added first.

        context.user_data["new_group_id"] = group_id
        await update.message.reply_text(
            f"تم استلام معرف المجموعة: {group_id}\n" 
            "الآن، الرجاء إرسال **TOTP Secret** الخاص بهذه المجموعة (بتنسيق Base32)."
        )
        return ASK_TOTP_SECRET
    except ValueError:
        await update.message.reply_text(
            "❌ معرف المجموعة يجب أن يكون رقماً صحيحاً. الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء."
        )
        return ASK_GROUP_ID

async def save_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    totp_secret = update.message.text.strip()
    group_id = context.user_data.get("new_group_id")

    if not group_id:
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرف المجموعة. الرجاء البدء من جديد.", reply_markup=kb.admin_main_keyboard())
        return ConversationHandler.END

    if not totp_utils.is_valid_totp_secret(totp_secret):
        await update.message.reply_text(
            "❌ الـ TOTP Secret الذي أدخلته غير صالح (يجب أن يكون بتنسيق Base32). الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء."
        )
        return ASK_TOTP_SECRET

    # Add group with default settings
    success, message = db.add_or_update_group(
        group_id=group_id,
        totp_secret=totp_secret,
        interval_minutes=config.DEFAULT_INTERVAL_MINUTES,
        message_format=config.DEFAULT_MESSAGE_FORMAT,
        timezone=config.DEFAULT_TIMEZONE,
        max_attempts=config.DEFAULT_MAX_ATTEMPTS,
        is_active=True # Activate by default
    )

    if success:
        schedule_group_job(context, group_id) # Schedule job for the new group
        logger.info(f"New group {group_id} added by admin {update.effective_user.id}.")
        await update.message.reply_text(
            f"✅ {message} تم تفعيل المجموعة وجدولة إرسال الرموز بشكل افتراضي كل {config.DEFAULT_INTERVAL_MINUTES} دقائق.",
            reply_markup=kb.manage_groups_keyboard() # Go back to group management
        )
    else:
        await update.message.reply_text(
            f"❌ فشلت إضافة المجموعة: {message}",
            reply_markup=kb.manage_groups_keyboard()
        )

    context.user_data.pop("new_group_id", None)
    return ConversationHandler.END

# --- Edit Group Secret Conversation ---
async def ask_edit_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt sent by button_callback
    return EDIT_GROUP_SECRET

async def save_edited_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_totp_secret = update.message.text.strip()
    group_id = context.user_data.get("current_group_id")

    if not group_id:
        await update.message.reply_text("حدث خطأ، لم يتم العثور على معرف المجموعة للتعديل. الرجاء البدء من جديد.", reply_markup=kb.admin_main_keyboard())
        return ConversationHandler.END

    if not totp_utils.is_valid_totp_secret(new_totp_secret):
        await update.message.reply_text(
            "❌ الـ TOTP Secret الذي أدخلته غير صالح (يجب أن يكون بتنسيق Base32). الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء."
        )
        return EDIT_GROUP_SECRET

    group_settings = db.get_group_settings(group_id)
    if not group_settings:
         await update.message.reply_text("❌ خطأ: المجموعة لم تعد موجودة.", reply_markup=kb.manage_groups_keyboard())
         context.user_data.pop("current_group_id", None)
         return ConversationHandler.END

    # Update only the secret, keep other settings
    success, message = db.add_or_update_group(
        group_id=group_id,
        totp_secret=new_totp_secret,
        interval_minutes=group_settings["interval_minutes"],
        message_format=group_settings["message_format"],
        timezone=group_settings["timezone"],
        max_attempts=group_settings["max_attempts"],
        is_active=group_settings["is_active"],
        job_id=group_settings["job_id"]
    )

    if success:
        logger.info(f"TOTP Secret for group {group_id} updated by admin {update.effective_user.id}.")
        await update.message.reply_text(
            f"✅ تم تحديث TOTP Secret للمجموعة {group_id} بنجاح.",
            reply_markup=kb.manage_groups_keyboard() # Go back to group management
        )
    else:
        await update.message.reply_text(
            f"❌ فشل تحديث الـ Secret: {message}",
            reply_markup=kb.manage_groups_keyboard()
        )

    context.user_data.pop("current_group_id", None)
    return ConversationHandler.END

# --- Manage User Attempts Conversation ---
async def ask_attempts_to_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt sent by button_callback
    return ASK_ATTEMPTS_TO_ADD

async def save_added_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        attempts_to_add = int(update.message.text.strip())
        if attempts_to_add <= 0:
            await update.message.reply_text("❌ الرجاء إدخال رقم موجب أكبر من صفر. استخدم /cancel للإلغاء.")
            return ASK_ATTEMPTS_TO_ADD

        group_id = context.user_data.get("current_group_id")
        target_user_id = context.user_data.get("target_user_id")

        if not group_id or not target_user_id:
            await update.message.reply_text("حدث خطأ، لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء البدء من جديد.", reply_markup=kb.admin_main_keyboard())
            return ConversationHandler.END

        success, message = db.add_user_attempts(target_user_id, group_id, attempts_to_add)

        if success:
            logger.info(f"Admin {update.effective_user.id} added {attempts_to_add} attempts to user {target_user_id} in group {group_id}.")
            await update.message.reply_text(f"✅ {message}", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))
        else:
            await update.message.reply_text(f"❌ فشلت الإضافة: {message}", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))

        context.user_data.pop("current_group_id", None)
        context.user_data.pop("target_user_id", None)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ الإدخال غير صالح. الرجاء إرسال رقم صحيح. استخدم /cancel للإلغاء.")
        return ASK_ATTEMPTS_TO_ADD

async def ask_attempts_to_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt sent by button_callback
    return ASK_ATTEMPTS_TO_REMOVE

async def save_removed_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        attempts_to_remove = int(update.message.text.strip())
        if attempts_to_remove <= 0:
            await update.message.reply_text("❌ الرجاء إدخال رقم موجب أكبر من صفر. استخدم /cancel للإلغاء.")
            return ASK_ATTEMPTS_TO_REMOVE

        group_id = context.user_data.get("current_group_id")
        target_user_id = context.user_data.get("target_user_id")

        if not group_id or not target_user_id:
            await update.message.reply_text("حدث خطأ، لم يتم العثور على بيانات المستخدم/المجموعة. الرجاء البدء من جديد.", reply_markup=kb.admin_main_keyboard())
            return ConversationHandler.END

        success, message = db.remove_user_attempts(target_user_id, group_id, attempts_to_remove)

        if success:
            logger.info(f"Admin {update.effective_user.id} removed {attempts_to_remove} attempts from user {target_user_id} in group {group_id}.")
            await update.message.reply_text(f"✅ {message}", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))
        else:
            await update.message.reply_text(f"❌ فشل الحذف: {message}", reply_markup=kb.manage_user_attempts_keyboard(group_id, target_user_id))

        context.user_data.pop("current_group_id", None)
        context.user_data.pop("target_user_id", None)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ الإدخال غير صالح. الرجاء إرسال رقم صحيح. استخدم /cancel للإلغاء.")
        return ASK_ATTEMPTS_TO_REMOVE

async def ask_default_max_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt sent by button_callback
    return ASK_DEFAULT_MAX_ATTEMPTS

async def save_default_max_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        max_attempts = int(update.message.text.strip())
        if max_attempts <= 0:
            await update.message.reply_text("❌ الرجاء إدخال رقم موجب أكبر من صفر. استخدم /cancel للإلغاء.")
            return ASK_DEFAULT_MAX_ATTEMPTS

        group_id = context.user_data.get("current_group_id")

        if not group_id:
            await update.message.reply_text("حدث خطأ، لم يتم العثور على معرف المجموعة. الرجاء البدء من جديد.", reply_markup=kb.admin_main_keyboard())
            return ConversationHandler.END

        success, message = db.update_group_max_attempts(group_id, max_attempts)

        if success:
            logger.info(f"Admin {update.effective_user.id} updated default max attempts for group {group_id} to {max_attempts}.")
            await update.message.reply_text(f"✅ {message}", reply_markup=kb.select_user_for_attempts_keyboard(group_id, page=1))
        else:
            await update.message.reply_text(f"❌ فشل التحديث: {message}", reply_markup=kb.select_user_for_attempts_keyboard(group_id, page=1))

        context.user_data.pop("current_group_id", None)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ الإدخال غير صالح. الرجاء إرسال رقم صحيح. استخدم /cancel للإلغاء.")
        return ASK_DEFAULT_MAX_ATTEMPTS

# --- Manage Admins Conversation ---
async def ask_admin_id_to_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Prompt sent by button_callback
    return ASK_ADMIN_ID_TO_ADD

async def save_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        admin_id_to_add = int(update.message.text.strip())
        # Optional: Check if the ID is a valid user ID format

        success, message = db.add_admin(admin_id_to_add)

        if success:
            logger.info(f"Admin {update.effective_user.id} added new admin {admin_id_to_add}.")
            await update.message.reply_text(f"✅ {message}", reply_markup=kb.manage_admins_keyboard())
        else:
            await update.message.reply_text(f"❌ فشلت الإضافة: {message}", reply_markup=kb.manage_admins_keyboard())

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم يجب أن يكون رقماً صحيحاً. الرجاء المحاولة مرة أخرى أو استخدم /cancel للإلغاء.")
        return ASK_ADMIN_ID_TO_ADD

# --- General Conversation Fallback/Cancel ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user_data = context.user_data
    # Clear any state
    user_data.clear()

    await update.message.reply_text(
        "تم إلغاء العملية الحالية.", reply_markup=kb.admin_main_keyboard() # Show admin menu again
    )
    return ConversationHandler.END

async def post_init(application: Application) -> None:
    """Set bot commands and load scheduled jobs after initialization."""
    await application.bot.set_my_commands([
        BotCommand("start", "بدء استخدام البوت"),
        BotCommand("admin", "فتح لوحة تحكم المسؤول")
    ])
    logger.info("Bot commands set.")
    # Load jobs - Consider potential issues if job queue isn't ready immediately
    # It's generally safe with ApplicationBuilder's post_init
    await load_scheduled_jobs(application)

# --- Main Function ---
def main() -> None:
    """Start the bot."""
    # Initialize database first
    db.initialize_database()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    # --- Conversation Handlers Setup ---
    # Add Group Conversation
    add_group_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_group_id, pattern="^group_add$")],
        states={
            ASK_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_totp_secret)],
            ASK_TOTP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_group)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        map_to_parent={
            # Return to main menu or previous state if needed
            ConversationHandler.END: None # End conversation, back to button handler
        }
    )

    # Edit Group Secret Conversation
    edit_secret_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_edit_group_secret, pattern="^group_edit_secret:")],
        states={
            EDIT_GROUP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_group_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
         map_to_parent={
            ConversationHandler.END: None
        }
    )

    # Add/Remove Attempts Conversation
    manage_attempts_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_attempts_to_add, pattern="^attempts_add:"),
            CallbackQueryHandler(ask_attempts_to_remove, pattern="^attempts_remove:"),
            CallbackQueryHandler(ask_default_max_attempts, pattern="^attempts_set_default:")
        ],
        states={
            ASK_ATTEMPTS_TO_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_added_attempts)],
            ASK_ATTEMPTS_TO_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_removed_attempts)],
            ASK_DEFAULT_MAX_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_default_max_attempts)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
         map_to_parent={
            ConversationHandler.END: None
        }
    )

    # Add Admin Conversation
    add_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_admin_id_to_add, pattern="^admin_add$")],
        states={
            ASK_ADMIN_ID_TO_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_admin)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
         map_to_parent={
            ConversationHandler.END: None
        }
    )

    # --- Main Handler Registration ---
    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))

    # Register conversation handlers (nested within callback query handler)
    # The main button_callback handles navigation and enters conversations
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(?!copy_code:|no_op).*")) # Handle all non-copy/no_op callbacks first

    # Register conversations - These need to be handled *before* the general callback handler if entry points overlap
    # However, our entry points are specific callback patterns handled by button_callback first.
    # Let's add them directly.
    application.add_handler(add_group_conv)
    application.add_handler(edit_secret_conv)
    application.add_handler(manage_attempts_conv)
    application.add_handler(add_admin_conv)

    # Handler for the 'Copy Code' button (must be separate as it's not an admin action)
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^copy_code:"))
    # Handler for 'no_op' buttons
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^no_op$"))

    # Add a fallback handler for any unhandled text messages (optional)
    # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()


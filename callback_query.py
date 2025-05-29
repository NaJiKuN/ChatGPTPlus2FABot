# -*- coding: utf-8 -*-
import logging
import pyotp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from utils import (
    is_admin, load_groups, save_groups, load_users, save_users, load_config, save_config,
    generate_totp, get_user_attempts, decrement_user_attempts, block_user, set_user_attempts,
    add_or_update_group, remove_group, get_group_config, format_scheduled_message
)
from handlers.admin import (
    admin_command, cancel_admin_conversation, # Import command and cancel functions
    SELECTING_ACTION, SELECTING_GROUP_ACTION, SELECTING_GROUP_ID, ENTERING_SECRET,
    CONFIRM_DELETE_GROUP, SELECTING_INTERVAL_GROUP, SELECTING_INTERVAL,
    SELECTING_STYLE_GROUP, SELECTING_STYLE, SELECTING_TIMEZONE,
    SELECTING_ATTEMPTS_GROUP, SELECTING_USER_FOR_ATTEMPTS, SELECTING_USER_ACTION,
    ENTERING_ATTEMPTS_COUNT, CONFIRM_BLOCK_USER, SELECTING_ADMIN_ACTION,
    ENTERING_ADMIN_ID, CONFIRM_REMOVE_ADMIN
)
from handlers.scheduled_message import send_scheduled_message # Import the sending function

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Callback Query Handlers --- #

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles callbacks within the admin conversation."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Ensure user is still an admin (could be removed mid-conversation)
    if not is_admin(user_id):
        await query.edit_message_text("عذراً، لم تعد لديك صلاحيات المسؤول.")
        context.user_data.clear()
        return ConversationHandler.END

    logger.info(f"Admin callback: User {user_id}, Data: {data}, State: {context.user_data.get('state')}")

    # --- Top Level Admin Menu --- #
    if data == "admin_manage_groups":
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="admin_add_group")],
            [InlineKeyboardButton("✏️ تعديل سر مجموعة", callback_data="admin_edit_group_secret")],
            [InlineKeyboardButton("🗑️ حذف مجموعة", callback_data="admin_delete_group")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("إدارة المجموعات/السر:", reply_markup=reply_markup)
        return SELECTING_GROUP_ACTION

    elif data == "admin_manage_interval":
        groups = load_groups()
        if not groups:
            await query.edit_message_text("لا توجد مجموعات مضافة حالياً. يرجى إضافة مجموعة أولاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
            return SELECTING_ACTION
        keyboard = []
        for group_id, config in groups.items():
            keyboard.append([InlineKeyboardButton(f"مجموعة {group_id} (الحالي: {config.get('interval_minutes', 10)}د)", callback_data=f"admin_select_interval_group_{group_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("إدارة فترة التكرار: اختر المجموعة:", reply_markup=reply_markup)
        return SELECTING_INTERVAL_GROUP

    elif data == "admin_manage_style":
        groups = load_groups()
        if not groups:
            await query.edit_message_text("لا توجد مجموعات مضافة حالياً. يرجى إضافة مجموعة أولاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
            return SELECTING_ACTION
        keyboard = []
        for group_id, config in groups.items():
             keyboard.append([InlineKeyboardButton(f"مجموعة {group_id} (الشكل: {config.get('message_style', 1)}, التوقيت: {config.get('timezone', 'UTC').upper()})", callback_data=f"admin_select_style_group_{group_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("إدارة شكل/توقيت الرسالة: اختر المجموعة:", reply_markup=reply_markup)
        return SELECTING_STYLE_GROUP

    elif data == "admin_manage_attempts":
        groups = load_groups()
        if not groups:
            await query.edit_message_text("لا توجد مجموعات مضافة حالياً. يرجى إضافة مجموعة أولاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")]]))
            return SELECTING_ACTION
        keyboard = []
        for group_id in groups.keys():
            keyboard.append([InlineKeyboardButton(f"مجموعة {group_id}", callback_data=f"admin_select_attempts_group_{group_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("إدارة محاولات المستخدمين: اختر المجموعة:", reply_markup=reply_markup)
        return SELECTING_ATTEMPTS_GROUP

    elif data == "admin_manage_admins":
        config = load_config()
        admins = config.get("admins", [])
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admin_add_admin")],
        ]
        if len(admins) > 1: # Cannot remove the last admin
             keyboard.append([InlineKeyboardButton("➖ إزالة مسؤول", callback_data="admin_remove_admin_select")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_back_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("إدارة المسؤولين:", reply_markup=reply_markup)
        return SELECTING_ADMIN_ACTION

    elif data == "admin_cancel":
        await query.edit_message_text("تم إلغاء العملية.")
        context.user_data.clear()
        return ConversationHandler.END

    elif data == "admin_back_main":
        # Go back to the main admin menu
        keyboard = [
            [InlineKeyboardButton("⚙️ إدارة المجموعات/السر", callback_data="admin_manage_groups")],
            [InlineKeyboardButton("⏰ إدارة فترة التكرار", callback_data="admin_manage_interval")],
            [InlineKeyboardButton("🎨 إدارة شكل/توقيت الرسالة", callback_data="admin_manage_style")],
            [InlineKeyboardButton("🔢 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
            [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لوحة تحكم المسؤول - ChatGPTPlus2FABot:", reply_markup=reply_markup)
        return SELECTING_ACTION

    # --- Group Management --- #
    elif data == "admin_add_group" or data == "admin_edit_group_secret":
        context.user_data["group_action"] = data # Store if adding or editing
        if data == "admin_add_group":
            await query.edit_message_text("أرسل معرف المجموعة الرقمي (يجب أن يبدأ بـ -100 للمجموعات الخارقة):")
        else: # Editing secret
            groups = load_groups()
            if not groups:
                 await query.edit_message_text("لا توجد مجموعات لتعديلها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))
                 return SELECTING_GROUP_ACTION
            keyboard = []
            for group_id in groups.keys():
                keyboard.append([InlineKeyboardButton(f"مجموعة {group_id}", callback_data=f"admin_select_edit_group_{group_id}")])
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")])
            await query.edit_message_text("اختر المجموعة لتعديل سرها:", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_GROUP_ID # Expecting group ID message or callback

    elif data.startswith("admin_select_edit_group_"):
        group_id = data.split("_")[-1]
        context.user_data["group_id"] = group_id
        await query.edit_message_text(f"أرسل الـ TOTP Secret الجديد للمجموعة {group_id}:")
        return ENTERING_SECRET # Expecting secret message

    elif data == "admin_delete_group":
        groups = load_groups()
        if not groups:
            await query.edit_message_text("لا توجد مجموعات لحذفها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))
            return SELECTING_GROUP_ACTION
        keyboard = []
        for group_id in groups.keys():
            keyboard.append([InlineKeyboardButton(f"مجموعة {group_id}", callback_data=f"admin_confirm_delete_group_{group_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("اختر المجموعة التي تريد حذفها:", reply_markup=reply_markup)
        return CONFIRM_DELETE_GROUP

    elif data.startswith("admin_confirm_delete_group_"):
        group_id = data.split("_")[-1]
        context.user_data["group_id_to_delete"] = group_id
        keyboard = [
            [InlineKeyboardButton("✅ نعم، حذف", callback_data="admin_do_delete_group"),
             InlineKeyboardButton("❌ لا، إلغاء", callback_data="admin_manage_groups")]
        ]
        await query.edit_message_text(f"هل أنت متأكد من حذف المجموعة {group_id} وجميع بياناتها المرتبطة؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM_DELETE_GROUP

    elif data == "admin_do_delete_group":
        group_id = context.user_data.get("group_id_to_delete")
        if not group_id:
            await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))
            return SELECTING_GROUP_ACTION

        scheduler: AsyncIOScheduler = context.bot_data["scheduler"]
        groups_data = load_groups()
        job_id = groups_data.get(str(group_id), {}).get("job_id")

        # Remove job from scheduler
        if job_id:
            try:
                scheduler.remove_job(job_id)
                logger.info(f"Removed scheduled job {job_id} for group {group_id}")
            except Exception as e:
                logger.error(f"Error removing job {job_id} for group {group_id}: {e}")

        # Remove group from groups.json
        if remove_group(group_id):
            # Optionally remove user data for this group from users.json
            users_data = load_users()
            if str(group_id) in users_data:
                del users_data[str(group_id)]
                save_users(users_data)

            await query.edit_message_text(f"تم حذف المجموعة {group_id} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))
        else:
            await query.edit_message_text("فشل حذف المجموعة. قد تكون غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")]]))

        context.user_data.clear()
        return SELECTING_GROUP_ACTION

    # --- Interval Management --- #
    elif data.startswith("admin_select_interval_group_"):
        group_id = data.split("_")[-1]
        context.user_data["group_id"] = group_id
        intervals = [1, 5, 10, 15, 30, 60, 180, 720, 1440] # In minutes
        keyboard = []
        row = []
        for i, interval in enumerate(intervals):
            label = f"{interval} دقيقة" if interval < 60 else f"{interval // 60} ساعة"
            row.append(InlineKeyboardButton(label, callback_data=f"admin_set_interval_{interval}"))
            if (i + 1) % 3 == 0:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)

        groups_data = load_groups()
        group_config = groups_data.get(str(group_id))
        current_status = "نشط" if group_config and group_config.get("active", True) else "متوقف"
        toggle_label = "⏹️ إيقاف التكرار" if current_status == "نشط" else "▶️ بدء التكرار"
        toggle_action = "stop" if current_status == "نشط" else "start"

        keyboard.append([InlineKeyboardButton(toggle_label, callback_data=f"admin_toggle_interval_{toggle_action}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_interval")])
        await query.edit_message_text(f"اختر فترة التكرار الجديدة للمجموعة {group_id} (الحالية: {group_config.get('interval_minutes', 10)}د, الحالة: {current_status}):", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_INTERVAL

    elif data.startswith("admin_set_interval_"):
        interval = int(data.split("_")[-1])
        group_id = context.user_data.get("group_id")
        if not group_id:
            await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]]))
            return SELECTING_INTERVAL_GROUP

        groups_data = load_groups()
        group_id_str = str(group_id)
        if group_id_str not in groups_data:
             await query.edit_message_text("المجموعة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]]))
             return SELECTING_INTERVAL_GROUP

        groups_data[group_id_str]["interval_minutes"] = interval
        groups_data[group_id_str]["active"] = True # Ensure it's active when interval is set
        save_groups(groups_data)

        # Reschedule job
        scheduler: AsyncIOScheduler = context.bot_data["scheduler"]
        job_id = groups_data[group_id_str].get("job_id", f"job_{group_id}")
        try:
            scheduler.reschedule_job(job_id, trigger=IntervalTrigger(minutes=interval))
            logger.info(f"Rescheduled job {job_id} for group {group_id} with interval {interval} minutes.")
            await query.edit_message_text(f"تم تحديث فترة التكرار للمجموعة {group_id} إلى {interval} دقيقة وتم تفعيلها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        except Exception as e: # Job might not exist if it was inactive
            logger.warning(f"Could not reschedule job {job_id}, attempting to add it. Error: {e}")
            try:
                scheduler.add_job(
                    send_scheduled_message,
                    trigger=IntervalTrigger(minutes=interval),
                    args=[context.application, group_id],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=60 # Allow 1 minute grace time
                )
                logger.info(f"Added scheduled job {job_id} for group {group_id} with interval {interval} minutes.")
                await query.edit_message_text(f"تم تحديث فترة التكرار للمجموعة {group_id} إلى {interval} دقيقة وتم تفعيلها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
            except Exception as add_e:
                 logger.error(f"Failed to add job {job_id} after reschedule failed: {add_e}")
                 await query.edit_message_text(f"تم تحديث فترة التكرار للمجموعة {group_id} إلى {interval} دقيقة، لكن حدث خطأ في إعادة الجدولة. يرجى المحاولة مرة أخرى أو إعادة تشغيل البوت.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

        context.user_data.clear()
        return SELECTING_ACTION

    elif data.startswith("admin_toggle_interval_"):
        action = data.split("_")[-1] # "start" or "stop"
        group_id = context.user_data.get("group_id")
        if not group_id:
            await query.edit_message_text("حدث خطأ. يرجى المحاولة مرة أخرى.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]]))
            return SELECTING_INTERVAL_GROUP

        groups_data = load_groups()
        group_id_str = str(group_id)
        if group_id_str not in groups_data:
             await query.edit_message_text("المجموعة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")]]))
             return SELECTING_INTERVAL_GROUP

        scheduler: AsyncIOScheduler = context.bot_data["scheduler"]
        job_id = groups_data[group_id_str].get("job_id", f"job_{group_id}")
        interval = groups_data[group_id_str].get("interval_minutes", 10)

        if action == "stop":
            groups_data[group_id_str]["active"] = False
            try:
                scheduler.pause_job(job_id)
                logger.info(f"Paused job {job_id} for group {group_id}")
                await query.edit_message_text(f"تم إيقاف التكرار للمجموعة {group_id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
            except Exception as e:
                logger.error(f"Error pausing job {job_id}: {e}")
                await query.edit_message_text(f"حدث خطأ أثناء إيقاف التكرار للمجموعة {group_id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        else: # action == "start"
            groups_data[group_id_str]["active"] = True
            try:
                # Try resuming first, if it fails, add the job
                try:
                    scheduler.resume_job(job_id)
                    logger.info(f"Resumed job {job_id} for group {group_id}")
                except Exception:
                    logger.info(f"Job {job_id} not found or couldn't be resumed, adding it.")
                    scheduler.add_job(
                        send_scheduled_message,
                        trigger=IntervalTrigger(minutes=interval),
                        args=[context.application, group_id],
                        id=job_id,
                        replace_existing=True,
                        misfire_grace_time=60
                    )
                    logger.info(f"Added scheduled job {job_id} for group {group_id} with interval {interval} minutes.")
                await query.edit_message_text(f"تم بدء التكرار للمجموعة {group_id} كل {interval} دقيقة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
            except Exception as e:
                logger.error(f"Error starting/adding job {job_id}: {e}")
                await query.edit_message_text(f"حدث خطأ أثناء بدء التكرار للمجموعة {group_id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

        save_groups(groups_data)
        context.user_data.clear()
        return SELECTING_ACTION

    # --- Style/Timezone Management --- #
    elif data.startswith("admin_select_style_group_"):
        group_id = data.split("_")[-1]
        context.user_data["group_id"] = group_id
        keyboard = [
            [InlineKeyboardButton("الشكل 1", callback_data="admin_set_style_1")],
            [InlineKeyboardButton("الشكل 2", callback_data="admin_set_style_2")],
            [InlineKeyboardButton("الشكل 3", callback_data="admin_set_style_3")],
            [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_style")]
        ]
        await query.edit_message_text(f"اختر شكل الرسالة للمجموعة {group_id}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_STYLE

    elif data.startswith("admin_set_style_"):
        style = int(data.split("_")[-1])
        group_id = context.user_data.get("group_id")
        if not group_id:
            # Handle error or go back
            return SELECTING_STYLE_GROUP

        groups_data = load_groups()
        group_id_str = str(group_id)
        if group_id_str in groups_data:
            groups_data[group_id_str]["message_style"] = style
            save_groups(groups_data)
            # Now ask for timezone
            keyboard = [
                [InlineKeyboardButton("توقيت غرينتش (GMT)", callback_data="admin_set_tz_gmt")],
                [InlineKeyboardButton("توقيت غزة (Asia/Gaza)", callback_data="admin_set_tz_gaza")],
                [InlineKeyboardButton("توقيت عالمي (UTC)", callback_data="admin_set_tz_utc")], # Added UTC as an option
                [InlineKeyboardButton("🔙 رجوع لاختيار الشكل", callback_data=f"admin_select_style_group_{group_id}")]
            ]
            await query.edit_message_text(f"تم تحديد الشكل {style}. الآن اختر المنطقة الزمنية للمجموعة {group_id}:", reply_markup=InlineKeyboardMarkup(keyboard))
            return SELECTING_TIMEZONE
        else:
            # Handle error: group not found
            await query.edit_message_text("المجموعة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_style")]]))
            return SELECTING_STYLE_GROUP

    elif data.startswith("admin_set_tz_"):
        tz_suffix = data.split("_")[-1]
        timezone_map = {"gmt": "GMT", "gaza": "Asia/Gaza", "utc": "UTC"}
        timezone = timezone_map.get(tz_suffix, "UTC") # Default to UTC if suffix is unknown

        group_id = context.user_data.get("group_id")
        if not group_id:
            # Handle error
            return SELECTING_STYLE_GROUP

        groups_data = load_groups()
        group_id_str = str(group_id)
        if group_id_str in groups_data:
            groups_data[group_id_str]["timezone"] = timezone
            save_groups(groups_data)
            style = groups_data[group_id_str].get("message_style", 1)
            await query.edit_message_text(f"تم تحديث إعدادات الرسالة للمجموعة {group_id} (الشكل: {style}, التوقيت: {timezone}).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
            context.user_data.clear()
            return SELECTING_ACTION
        else:
            # Handle error: group not found
            await query.edit_message_text("المجموعة غير موجودة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_style")]]))
            context.user_data.clear()
            return SELECTING_STYLE_GROUP

    # --- User Attempts Management --- #
    elif data.startswith("admin_select_attempts_group_"):
        group_id = data.split("_")[-1]
        context.user_data["group_id"] = group_id
        users_data = load_users()
        group_users = users_data.get(str(group_id), {})

        if not group_users:
            await query.edit_message_text(f"لا يوجد مستخدمون مسجلون للمجموعة {group_id} بعد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")]])) 
            return SELECTING_ATTEMPTS_GROUP

        keyboard = []
        for user_id_str, user_info in group_users.items():
            try:
                user = await context.bot.get_chat(int(user_id_str))
                user_name = user.full_name or user.username or f"User {user_id_str}"
            except Exception:
                user_name = f"User {user_id_str}" # Fallback if user info cannot be fetched
            attempts = user_info.get("attempts", "N/A")
            status = "محظور" if user_info.get("blocked") else f"{attempts} محاولات"
            keyboard.append([InlineKeyboardButton(f"{user_name} ({status})", callback_data=f"admin_select_user_attempts_{user_id_str}")])

        keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")])
        await query.edit_message_text(f"اختر المستخدم لإدارة محاولاته في المجموعة {group_id}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_USER_FOR_ATTEMPTS

    elif data.startswith("admin_select_user_attempts_"):
        user_id_to_manage = data.split("_")[-1]
        context.user_data["user_id_to_manage"] = user_id_to_manage
        group_id = context.user_data.get("group_id")
        users_data = load_users()
        user_info = users_data.get(str(group_id), {}).get(user_id_to_manage, {})
        is_blocked = user_info.get("blocked", False)

        keyboard = [
            [InlineKeyboardButton("➕ إضافة محاولات", callback_data="admin_user_add_attempts")],
            [InlineKeyboardButton("➖ حذف محاولات", callback_data="admin_user_remove_attempts")],
            [InlineKeyboardButton("🚫 حظر المستخدم" if not is_blocked else "✅ إلغاء حظر المستخدم", callback_data="admin_user_toggle_block")],
            [InlineKeyboardButton("🔙 رجوع لاختيار مستخدم", callback_data=f"admin_select_attempts_group_{group_id}")]
        ]
        await query.edit_message_text(f"اختر الإجراء للمستخدم {user_id_to_manage} في المجموعة {group_id}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECTING_USER_ACTION

    elif data == "admin_user_add_attempts" or data == "admin_user_remove_attempts":
        context.user_data["user_action"] = data # Store action type
        action_text = "إضافتها" if data == "admin_user_add_attempts" else "حذفها"
        await query.edit_message_text(f"أرسل عدد المحاولات التي تريد {action_text}:")
        return ENTERING_ATTEMPTS_COUNT

    elif data == "admin_user_toggle_block":
        group_id = context.user_data.get("group_id")
        user_id_to_manage = context.user_data.get("user_id_to_manage")
        if not group_id or not user_id_to_manage:
            # Handle error
            return SELECTING_ATTEMPTS_GROUP

        users_data = load_users()
        user_info = users_data.get(str(group_id), {}).get(user_id_to_manage, {})
        is_currently_blocked = user_info.get("blocked", False)
        new_block_status = not is_currently_blocked

        block_user(int(user_id_to_manage), int(group_id), new_block_status)
        status_text = "محظور" if new_block_status else "غير محظور"
        await query.edit_message_text(f"تم تحديث حالة المستخدم {user_id_to_manage} إلى: {status_text}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        context.user_data.clear()
        return SELECTING_ACTION

    # --- Admin Management --- #
    elif data == "admin_add_admin":
        await query.edit_message_text("أرسل المعرف الرقمي للمسؤول الجديد:")
        return ENTERING_ADMIN_ID

    elif data == "admin_remove_admin_select":
        config = load_config()
        admins = config.get("admins", [])
        keyboard = []
        current_admin_id = query.from_user.id
        for admin_id in admins:
            # Prevent admin from removing themselves if they are the only one left
            if len(admins) <= 1 and admin_id == current_admin_id:
                continue
            # Fetch admin info if possible
            try:
                user = await context.bot.get_chat(admin_id)
                admin_name = user.full_name or user.username or f"Admin {admin_id}"
            except Exception:
                admin_name = f"Admin {admin_id}"
            keyboard.append([InlineKeyboardButton(f"{admin_name}", callback_data=f"admin_confirm_remove_admin_{admin_id}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")])
        await query.edit_message_text("اختر المسؤول لإزالته:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM_REMOVE_ADMIN

    elif data.startswith("admin_confirm_remove_admin_"):
        admin_id_to_remove = int(data.split("_")[-1])
        context.user_data["admin_id_to_remove"] = admin_id_to_remove
        keyboard = [
            [InlineKeyboardButton("✅ نعم، إزالة", callback_data="admin_do_remove_admin"),
             InlineKeyboardButton("❌ لا، إلغاء", callback_data="admin_manage_admins")]
        ]
        await query.edit_message_text(f"هل أنت متأكد من إزالة المسؤول {admin_id_to_remove}؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM_REMOVE_ADMIN

    elif data == "admin_do_remove_admin":
        admin_id_to_remove = context.user_data.get("admin_id_to_remove")
        if not admin_id_to_remove:
            # Handle error
            return SELECTING_ADMIN_ACTION

        config = load_config()
        admins = config.get("admins", [])
        if admin_id_to_remove in admins:
            if len(admins) > 1: # Ensure we don't remove the last admin
                admins.remove(admin_id_to_remove)
                config["admins"] = admins
                save_config(config)
                await query.edit_message_text(f"تمت إزالة المسؤول {admin_id_to_remove} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
            else:
                await query.edit_message_text("لا يمكن إزالة المسؤول الأخير.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]])) 
        else:
            await query.edit_message_text("المسؤول غير موجود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]])) 

        context.user_data.clear()
        return SELECTING_ACTION

    else:
        # Fallback for unexpected callback data within the conversation
        await query.edit_message_text("إجراء غير معروف أو غير متوقع.")
        logger.warning(f"Unhandled admin callback data: {data}")
        # Go back to main menu might be safer
        keyboard = [
            [InlineKeyboardButton("⚙️ إدارة المجموعات/السر", callback_data="admin_manage_groups")],
            [InlineKeyboardButton("⏰ إدارة فترة التكرار", callback_data="admin_manage_interval")],
            [InlineKeyboardButton("🎨 إدارة شكل/توقيت الرسالة", callback_data="admin_manage_style")],
            [InlineKeyboardButton("🔢 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
            [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("لوحة تحكم المسؤول - ChatGPTPlus2FABot:", reply_markup=reply_markup)
        return SELECTING_ACTION

# --- Handlers for Receiving Text Input in Conversation --- #

async def received_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving the group ID message."""
    user_input = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return ConversationHandler.END # Should not happen normally

    try:
        group_id = int(user_input)
        # Basic validation for group IDs (supergroups/channels start with -100)
        if not (user_input.startswith("-") and len(user_input) > 4):
             await update.message.reply_text("معرف المجموعة غير صالح. يجب أن يكون رقماً صحيحاً سالباً (عادة يبدأ بـ -100 للمجموعات الخارقة).")
             # Stay in the same state to re-prompt
             return SELECTING_GROUP_ID

        context.user_data["group_id"] = group_id
        await update.message.reply_text(f"تم استلام معرف المجموعة: {group_id}. الآن أرسل الـ TOTP Secret الخاص بها:")
        return ENTERING_SECRET
    except ValueError:
        await update.message.reply_text("الرجاء إرسال معرف رقمي صحيح للمجموعة.")
        return SELECTING_GROUP_ID # Stay in the same state

async def received_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving the TOTP secret message."""
    secret = update.message.text.strip().replace(" ", "") # Remove spaces
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    group_id = context.user_data.get("group_id")
    action = context.user_data.get("group_action", "admin_add_group") # Default to add if not set

    if not is_admin(user_id) or not group_id:
        await update.message.reply_text("حدث خطأ أو انتهت صلاحية الجلسة. يرجى البدء من جديد باستخدام /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    # Validate secret (basic check: not empty and seems like base32)
    if not secret or not all(c in pyotp.DEFAULT_INTERVAL * "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=" for c in secret.upper()):
        # A more robust check might be needed depending on typical secret formats
        # pyotp doesn't expose a direct validator, trying to generate a code is an option
        try:
            pyotp.TOTP(secret).now()
        except Exception:
             await update.message.reply_text("الـ TOTP Secret يبدو غير صالح. يرجى التأكد من أنه بالتنسيق الصحيح (عادةً Base32).")
             return ENTERING_SECRET # Stay in the same state to re-prompt

    groups_data = load_groups()
    group_id_str = str(group_id)
    is_new_group = group_id_str not in groups_data
    default_interval = 10

    # Add or update the group in groups.json
    group_config = add_or_update_group(
        group_id=group_id,
        secret=secret,
        interval=groups_data.get(group_id_str, {}).get("interval_minutes", default_interval),
        style=groups_data.get(group_id_str, {}).get("message_style", 1),
        timezone=groups_data.get(group_id_str, {}).get("timezone", "UTC"),
        active=groups_data.get(group_id_str, {}).get("active", True) # Keep existing status or default to True
    )

    # Add or update the job in the scheduler
    scheduler: AsyncIOScheduler = context.bot_data["scheduler"]
    job_id = group_config["job_id"]
    interval = group_config["interval_minutes"]
    is_active = group_config["active"]

    try:
        if is_active:
            scheduler.add_job(
                send_scheduled_message,
                trigger=IntervalTrigger(minutes=interval),
                args=[context.application, group_id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=60 # Allow 1 minute grace time
            )
            logger.info(f"Scheduled/Updated job {job_id} for group {group_id} with interval {interval} minutes.")
            status_msg = f"كل {interval} دقائق" if interval else "(متوقف)"
        else:
            # If the group exists but is inactive, ensure the job is paused or removed
            try: scheduler.pause_job(job_id)
            except: pass # Job might not exist, ignore error
            logger.info(f"Group {group_id} is inactive. Job {job_id} ensured paused/removed.")
            status_msg = "(متوقف)"

        action_verb = "إضافة" if action == "admin_add_group" else "تعديل"
        await update.message.reply_text(f"تم {action_verb} المجموعة {group_id} بنجاح. سيتم إرسال الرمز {status_msg}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

    except Exception as e:
        logger.error(f"Error scheduling job {job_id} for group {group_id}: {e}")
        await update.message.reply_text(f"تم {action_verb} بيانات المجموعة {group_id}، لكن حدث خطأ أثناء جدولة إرسال الرسائل. يرجى المحاولة مرة أخرى أو التحقق من إعدادات التكرار.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

    context.user_data.clear()
    return SELECTING_ACTION # Go back to main menu state

async def received_attempts_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving the number of attempts to add/remove."""
    user_input = update.message.text
    chat_id = update.effective_chat.id
    admin_user_id = update.effective_user.id

    group_id = context.user_data.get("group_id")
    user_id_to_manage = context.user_data.get("user_id_to_manage")
    action = context.user_data.get("user_action") # "admin_user_add_attempts" or "admin_user_remove_attempts"

    if not is_admin(admin_user_id) or not group_id or not user_id_to_manage or not action:
        await update.message.reply_text("حدث خطأ أو انتهت صلاحية الجلسة. يرجى البدء من جديد باستخدام /admin.")
        context.user_data.clear()
        return ConversationHandler.END

    try:
        count = int(user_input)
        if count < 0:
            await update.message.reply_text("الرجاء إدخال رقم موجب لعدد المحاولات.")
            return ENTERING_ATTEMPTS_COUNT # Stay in state

        users_data = load_users()
        group_id_str = str(group_id)
        user_id_str = str(user_id_to_manage)
        config = load_config()
        default_attempts = config.get("default_attempts", 5)

        if group_id_str not in users_data:
            users_data[group_id_str] = {}
        if user_id_str not in users_data[group_id_str]:
            users_data[group_id_str][user_id_str] = {"attempts": default_attempts, "blocked": False}

        current_attempts = users_data[group_id_str][user_id_str].get("attempts", default_attempts)
        is_blocked = users_data[group_id_str][user_id_str].get("blocked", False)

        if is_blocked:
             await update.message.reply_text(f"المستخدم {user_id_to_manage} محظور حالياً. لا يمكن تعديل المحاولات.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 
        else:
            if action == "admin_user_add_attempts":
                new_attempts = current_attempts + count
                action_text = "إضافة"
            else: # remove attempts
                new_attempts = max(0, current_attempts - count) # Ensure attempts don't go below 0
                action_text = "حذف"

            set_user_attempts(int(user_id_to_manage), int(group_id), new_attempts)
            await update.message.reply_text(f"تم {action_text} {count} محاولات للمستخدم {user_id_to_manage}. المحاولات الحالية: {new_attempts}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

        context.user_data.clear()
        return SELECTING_ACTION

    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح لعدد المحاولات.")
        return ENTERING_ATTEMPTS_COUNT # Stay in state

async def received_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving the new admin ID message."""
    user_input = update.message.text
    chat_id = update.effective_chat.id
    requesting_admin_id = update.effective_user.id

    if not is_admin(requesting_admin_id):
        return ConversationHandler.END

    try:
        new_admin_id = int(user_input)
        # Optional: Add more validation for user ID format if needed

        config = load_config()
        admins = config.get("admins", [])
        if new_admin_id in admins:
            await update.message.reply_text(f"المستخدم {new_admin_id} هو مسؤول بالفعل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")]])) 
        else:
            # Optional: Check if the user ID exists on Telegram before adding
            # try:
            #     await context.bot.get_chat(new_admin_id)
            # except Exception:
            #     await update.message.reply_text(f"لم يتم العثور على مستخدم بالمعرف {new_admin_id}. يرجى التأكد من صحة المعرف.")
            #     return ENTERING_ADMIN_ID

            admins.append(new_admin_id)
            config["admins"] = admins
            save_config(config)
            await update.message.reply_text(f"تمت إضافة المسؤول {new_admin_id} بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_back_main")]])) 

        context.user_data.clear()
        return SELECTING_ACTION

    except ValueError:
        await update.message.reply_text("الرجاء إرسال معرف رقمي صحيح للمسؤول.")
        return ENTERING_ADMIN_ID # Stay in state

# --- "Copy Code" Button Handler (Not part of admin conversation) --- #

async def handle_copy_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Copy Code' button press by users."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press immediately

    user_id = query.from_user.id
    user_name = query.from_user.full_name or query.from_user.username
    callback_data = query.data

    try:
        _, _, group_id_str = callback_data.split("_")
        group_id = int(group_id_str)
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data received: {callback_data}")
        # Optionally notify the user or admin about the error
        # await query.message.reply_text("حدث خطأ غير متوقع.") # Replying in group might be noisy
        return

    logger.info(f"User {user_id} ({user_name}) pressed Copy Code for group {group_id}")

    # 1. Check if user is blocked or has attempts remaining
    remaining_attempts = get_user_attempts(user_id, group_id)
    if remaining_attempts <= 0:
        users_data = load_users()
        is_blocked = users_data.get(str(group_id), {}).get(str(user_id), {}).get("blocked", False)
        message = "أنت محظور من استخدام هذا الزر في هذه المجموعة." if is_blocked else "لقد استنفدت محاولاتك المسموحة لنسخ الرمز."
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            logger.info(f"Denied Copy Code for user {user_id} in group {group_id} (Reason: {'Blocked' if is_blocked else 'No attempts'}). Notified user.")
        except Exception as e:
            logger.error(f"Failed to send denial message to user {user_id}: {e}")
            # Maybe notify admin if direct message fails?
        return

    # 2. Get group config and generate TOTP
    group_config = get_group_config(group_id)
    if not group_config or not group_config.get("secret"):
        logger.error(f"Group config or secret not found for group {group_id} when user {user_id} pressed Copy Code.")
        # Notify admin?
        try:
            await context.bot.send_message(chat_id=user_id, text="حدث خطأ أثناء محاولة توليد الرمز. يرجى إبلاغ المسؤول.")
        except Exception as e:
            logger.error(f"Failed to send error message to user {user_id}: {e}")
        return

    totp_code = generate_totp(group_config["secret"])
    if totp_code is None:
        logger.error(f"Failed to generate TOTP for group {group_id} (Secret: {group_config.get('secret')[:5]}...). User: {user_id}")
        try:
            await context.bot.send_message(chat_id=user_id, text="حدث خطأ أثناء توليد الرمز. يرجى إبلاغ المسؤول.")
        except Exception as e:
            logger.error(f"Failed to send TOTP generation error message to user {user_id}: {e}")
        return

    # 3. Decrement attempts
    decrement_success = decrement_user_attempts(user_id, group_id)
    if not decrement_success:
        # This case should ideally be caught by the initial check, but as a safeguard:
        logger.warning(f"Failed to decrement attempts for user {user_id} in group {group_id} after passing initial check.")
        try:
            await context.bot.send_message(chat_id=user_id, text="حدث خطأ في تسجيل محاولتك. لم يتم إرسال الرمز.")
        except Exception as e:
            logger.error(f"Failed to send decrement error message to user {user_id}: {e}")
        return

    # 4. Send code to user via private message
    new_remaining_attempts = get_user_attempts(user_id, group_id) # Get the updated count
    message_text = f"""🔑 رمز المصادقة الثنائية للمجموعة {group_id}:

`{totp_code}`

\u26A0\ufe0f هذا الرمز صالح لمدة 30 ثانية فقط\\.
🔄 المحاولات المتبقية لك: {new_remaining_attempts}"""
    try:
        await context.bot.send_message(chat_id=user_id, text=message_text, parse_mode='MarkdownV2')
        logger.info(f"Sent TOTP code {totp_code} to user {user_id} for group {group_id}. Attempts remaining: {new_remaining_attempts}")
    except Exception as e:
        logger.error(f"Failed to send TOTP code via private message to user {user_id}: {e}")
        # Attempt to notify via answerCallbackQuery as a fallback, though less ideal
        try:
            await query.answer(text=f"Code: {totp_code}. Attempts left: {new_remaining_attempts}. Check PM Error.", show_alert=True)
        except Exception as alert_e:
            logger.error(f"Failed to send fallback alert to user {user_id}: {alert_e}")
        # Consider refunding the attempt if PM fails?
        # set_user_attempts(user_id, group_id, new_remaining_attempts + 1)

# --- Helper to build the ConversationHandler --- #

def get_admin_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            SELECTING_ACTION: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_")],
            SELECTING_GROUP_ACTION: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_(add|edit|delete|back|manage)_group.*|^admin_back_main$")],
            SELECTING_GROUP_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_group_id),
                CallbackQueryHandler(handle_admin_callback, pattern="^admin_select_edit_group_\d+|^admin_manage_groups$") # Handle selecting group for edit or going back
            ],
            ENTERING_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_secret)],
            CONFIRM_DELETE_GROUP: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_(confirm_delete|do_delete|manage)_group.*")],
            SELECTING_INTERVAL_GROUP: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_select_interval_group_\d+|^admin_back_main$")],
            SELECTING_INTERVAL: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_set_interval_\d+|^admin_toggle_interval_(start|stop)|^admin_manage_interval$")],
            SELECTING_STYLE_GROUP: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_select_style_group_\d+|^admin_back_main$")],
            SELECTING_STYLE: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_set_style_\d+|^admin_select_style_group_\d+|^admin_manage_style$")], # Allow going back
            SELECTING_TIMEZONE: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_set_tz_\w+|^admin_select_style_group_\d+")], # Allow going back
            SELECTING_ATTEMPTS_GROUP: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_select_attempts_group_\d+|^admin_back_main$")],
            SELECTING_USER_FOR_ATTEMPTS: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_select_user_attempts_\d+|^admin_manage_attempts$")],
            SELECTING_USER_ACTION: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_user_(add|remove)_attempts|^admin_user_toggle_block|^admin_select_attempts_group_\d+")], # Allow going back
            ENTERING_ATTEMPTS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_attempts_count)],
            # CONFIRM_BLOCK_USER state removed as toggle is immediate
            SELECTING_ADMIN_ACTION: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_(add|remove)_admin.*|^admin_back_main$")],
            ENTERING_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_admin_id)],
            CONFIRM_REMOVE_ADMIN: [CallbackQueryHandler(handle_admin_callback, pattern="^admin_(confirm_remove|do_remove)_admin.*|^admin_manage_admins$")]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_admin_conversation, pattern="^admin_cancel$"),
            CommandHandler("admin", admin_command) # Allow restarting with /admin
            # Consider adding a timeout?
            # TypeHandler(Update, fallback_handler) # Catch any other update type?
        ],
        conversation_timeout=600 # Timeout after 10 minutes of inactivity
    )

def get_copy_code_handler():
    return CallbackQueryHandler(handle_copy_code_callback, pattern="^copy_code_")



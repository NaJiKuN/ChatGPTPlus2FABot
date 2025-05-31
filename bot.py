# /home/ec2-user/projects/ChatGPTPlus2FABot/bot.py
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
import totp_utils as totp

# تكوين السجل (logging)
logging.basicConfig(level=logging.INFO, format=\"%(asctime)s - %(name)s - %(levelname)s - %(message)s\")
logger = logging.getLogger(__name__)

# حالات المحادثة
(
    WAITING_FOR_GROUP_ID,
    WAITING_FOR_TOTP_SECRET,
    WAITING_FOR_NEW_SECRET,
    WAITING_FOR_ADMIN_ID,
    WAITING_FOR_MAX_ATTEMPTS,
    WAITING_FOR_ADD_ATTEMPTS,
    WAITING_FOR_REMOVE_ATTEMPTS,
) = range(7)

# وظائف مساعدة
async def send_periodic_message(context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة دورية إلى المجموعة المحددة."""
    job = context.job
    group_id = job.data["group_id"]
    
    # الحصول على إعدادات المجموعة
    group_settings = db.get_group_settings(group_id)
    if not group_settings:
        logger.error(f"لم يتم العثور على إعدادات للمجموعة {group_id}. إلغاء المهمة.")
        return
    
    # التحقق من حالة التفعيل
    if not group_settings["is_active"]:
        logger.info(f"المجموعة {group_id} غير مفعلة. تخطي إرسال الرسالة.")
        return
    
    # الحصول على المفتاح السري وتنسيق الرسالة
    totp_secret = group_settings["totp_secret"]
    message_format = group_settings["message_format"]
    timezone_str = group_settings["timezone"]
    
    try:
        # محاولة الحصول على المنطقة الزمنية
        timezone = pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning(f"منطقة زمنية غير معروفة {group_settings["timezone"]} للمجموعة {group_settings["group_id"]}. استخدام GMT كافتراضي.")
        timezone = pytz.timezone("GMT")
    
    # الحصول على الوقت الحالي والوقت المتبقي
    now = datetime.datetime.now(timezone)
    remaining_seconds = totp.get_remaining_seconds()
    next_code_time = (now + datetime.timedelta(seconds=remaining_seconds)).strftime("%H:%M:%S")
    
    # إنشاء نص الرسالة حسب التنسيق المختار
    if message_format == 1:
        message_text = f"🔐 *رمز المصادقة التالي في الساعة:* `{next_code_time}`"
    elif message_format == 2:
        message_text = f"🔐 *رمز المصادقة التالي في الساعة:* `{next_code_time}`\n⏱ *المدة المتبقية للرمز الحالي:* `{remaining_seconds} ثانية`"
    elif message_format == 3:
        current_time = now.strftime("%H:%M:%S")
        message_text = f"🔐 *رمز المصادقة التالي في الساعة:* `{next_code_time}`\n🕒 *الوقت الحالي:* `{current_time}`"
    else:
        message_text = f"🔐 *رمز المصادقة متاح الآن*"
    
    # إضافة تعليمات
    message_text += "\n\nاضغط على زر \'نسخ الرمز\' أدناه للحصول على رمز المصادقة في رسالة خاصة."
    
    # إنشاء لوحة المفاتيح
    keyboard = kb.request_code_keyboard(group_id)
    
    try:
        # إرسال الرسالة إلى المجموعة
        await context.bot.send_message(
            chat_id=group_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        logger.info(f"تم إرسال رسالة دورية إلى المجموعة {group_id}")
    except TelegramError as e:
        logger.error(f"خطأ في إرسال رسالة دورية إلى المجموعة {group_id}: {e}")
        # إذا كان الخطأ بسبب عدم وجود البوت في المجموعة، يمكن إلغاء تفعيل المجموعة هنا
        if "bot is not a member" in str(e).lower() or "chat not found" in str(e).lower():
            logger.warning(f"البوت ليس عضواً في المجموعة {group_id}. إلغاء تفعيل المجموعة.")
            db.update_group_status(group_id, False)

def schedule_periodic_message(application, group_id):
    """جدولة إرسال رسائل دورية للمجموعة المحددة."""
    group_settings = db.get_group_settings(group_id)
    if not group_settings:
        logger.error(f"لم يتم العثور على إعدادات للمجموعة {group_id}. لا يمكن جدولة الرسائل.")
        return False
    
    # إلغاء أي مهمة سابقة لهذه المجموعة
    current_job_id = group_settings["job_id"]
    if current_job_id:
        application.job_queue.scheduler.remove_job(current_job_id)
        logger.info(f"تم إلغاء المهمة السابقة للمجموعة {group_id}")
    
    # إذا كانت المجموعة غير مفعلة، لا نقوم بجدولة مهمة جديدة
    if not group_settings["is_active"]:
        logger.info(f"المجموعة {group_id} غير مفعلة. لم يتم جدولة مهمة جديدة.")
        db.update_group_job_id(group_id, None)
        return True
    
    # جدولة مهمة جديدة
    interval_minutes = group_settings["interval_minutes"]
    job = application.job_queue.run_repeating(
        send_periodic_message,
        interval=datetime.timedelta(minutes=interval_minutes),
        first=5,  # بدء بعد 5 ثوانٍ
        data={"group_id": group_id}
    )
    
    # تحديث معرف المهمة في قاعدة البيانات
    job_id = job.job.id
    db.update_group_job_id(group_id, job_id)
    logger.info(f"تمت جدولة مهمة جديدة للمجموعة {group_id} بمعرف {job_id} وفترة {interval_minutes} دقيقة")
    return True

# معالجات الأوامر
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start."""
    user_id = update.effective_user.id
    is_admin = db.is_admin(user_id)
    
    if is_admin:
        await update.message.reply_text(
            "مرحباً بك في بوت ChatGPTPlus2FABot! 👋\n\n"
            "أنت مسؤول في هذا البوت ويمكنك استخدام الأمر /admin للوصول إلى لوحة التحكم."
        )
    else:
        await update.message.reply_text(
            "مرحباً بك في بوت ChatGPTPlus2FABot! 👋\n\n"
            "هذا البوت مخصص لإرسال رموز المصادقة الثنائية (2FA) للمجموعات المسجلة.\n"
            "يمكنك الحصول على الرمز عبر الضغط على زر \'نسخ الرمز\' في الرسائل المرسلة إلى المجموعة."
        )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /admin."""
    user_id = update.effective_user.id
    is_admin = db.is_admin(user_id)
    
    if not is_admin:
        await update.message.reply_text("عذراً، هذا الأمر متاح للمسؤولين فقط.")
        return
    
    await update.message.reply_text(
        "مرحباً بك في لوحة تحكم المسؤول! 👑\n"
        "يرجى اختيار الإجراء الذي تريد القيام به:",
        reply_markup=kb.admin_main_keyboard()
    )

# معالجات الاستجابة للأزرار
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # التحقق من صلاحية المسؤول للأزرار الإدارية
    if data.startswith("admin_") or data.startswith("group_") or data.startswith("interval_") or data.startswith("format_") or data.startswith("attempts_"):
        is_admin = db.is_admin(user_id)
        if not is_admin:
            await query.message.reply_text("عذراً، هذه الوظيفة متاحة للمسؤولين فقط.")
            return
    
    # معالجة الأزرار الرئيسية للمسؤول
    if data == "admin_main":
        await query.edit_message_text(
            "مرحباً بك في لوحة تحكم المسؤول! 👑\n"
            "يرجى اختيار الإجراء الذي تريد القيام به:",
            reply_markup=kb.admin_main_keyboard()
        )
    
    elif data == "admin_manage_groups":
        await query.edit_message_text(
            "إدارة المجموعات وإعدادات TOTP 📊\n"
            "يرجى اختيار الإجراء الذي تريد القيام به:",
            reply_markup=kb.manage_groups_keyboard()
        )
    
    elif data == "admin_manage_interval":
        await query.edit_message_text(
            "إدارة فترة التكرار ⏰\n"
            "يرجى اختيار المجموعة التي تريد إدارة فترة التكرار لها:",
            reply_markup=kb.select_group_for_interval_keyboard()
        )
    
    elif data == "admin_manage_format":
        await query.edit_message_text(
            "إدارة شكل وتوقيت الرسالة ✉️\n"
            "يرجى اختيار المجموعة التي تريد إدارة شكل الرسالة لها:",
            reply_markup=kb.select_group_for_format_keyboard()
        )
    
    elif data == "admin_manage_attempts":
        await query.edit_message_text(
            "إدارة محاولات المستخدمين 👤\n"
            "يرجى اختيار المجموعة التي تريد إدارة محاولات المستخدمين فيها:",
            reply_markup=kb.select_group_for_attempts_keyboard()
        )
    
    elif data == "admin_manage_admins":
        await query.edit_message_text(
            "إدارة المسؤولين 👑\n"
            "يرجى اختيار الإجراء الذي تريد القيام به:",
            reply_markup=kb.manage_admins_keyboard()
        )
    
    elif data == "admin_close":
        await query.edit_message_text("تم إغلاق لوحة التحكم. استخدم الأمر /admin لفتحها مرة أخرى.")
    
    # معالجة أزرار إدارة المجموعات
    elif data == "group_add":
        context.user_data["admin_action"] = "add_group"
        await query.edit_message_text(
            "إضافة مجموعة جديدة 📝\n"
            "يرجى إدخال معرف المجموعة (Group ID).\n"
            "يمكنك الحصول على معرف المجموعة عبر إضافة البوت @username_to_id_bot إلى المجموعة ثم إرسال أي رسالة.",
            reply_markup=kb.back_keyboard("admin_manage_groups")
        )
        return WAITING_FOR_GROUP_ID
    
    elif data == "group_select_edit":
        await query.edit_message_text(
            "تعديل مجموعة حالية ✏️\n"
            "يرجى اختيار المجموعة التي تريد تعديلها:",
            reply_markup=kb.select_group_keyboard("group_edit")
        )
    
    elif data == "group_select_delete":
        await query.edit_message_text(
            "حذف مجموعة ➖\n"
            "يرجى اختيار المجموعة التي تريد حذفها:",
            reply_markup=kb.select_group_keyboard("group_delete")
        )
    
    elif data.startswith("group_edit:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"تعديل المجموعة: {group_id} ✏️\n"
            "يرجى اختيار الإجراء الذي تريد القيام به:",
            reply_markup=kb.edit_group_options_keyboard(group_id)
        )
    
    elif data.startswith("group_edit_secret:"):
        group_id = data.split(":")[1]
        context.user_data["admin_action"] = "edit_secret"
        context.user_data["group_id"] = group_id
        await query.edit_message_text(
            f"تعديل TOTP Secret للمجموعة: {group_id} 🔑\n"
            "يرجى إدخال المفتاح السري الجديد (TOTP Secret):",
            reply_markup=kb.back_keyboard(f"group_edit:{group_id}")
        )
        return WAITING_FOR_NEW_SECRET
    
    elif data.startswith("group_delete:"):
        group_id = data.split(":")[1]
        success, message = db.remove_group(group_id)
        if success:
            # إلغاء المهمة المجدولة إذا كانت موجودة
            group_settings = db.get_group_settings(group_id)
            if group_settings and group_settings["job_id"]:
                try:
                    context.application.job_queue.scheduler.remove_job(group_settings["job_id"])
                    logger.info(f"تم إلغاء المهمة المجدولة للمجموعة {group_id}")
                except Exception as e:
                    logger.error(f"خطأ في إلغاء المهمة المجدولة للمجموعة {group_id}: {e}")
            
            await query.edit_message_text(
                f"✅ {message}\n\n"
                "يرجى اختيار الإجراء التالي:",
                reply_markup=kb.manage_groups_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ {message}\n\n"
                "يرجى اختيار مجموعة أخرى:",
                reply_markup=kb.select_group_keyboard("group_delete")
            )
    
    # معالجة أزرار إدارة فترة التكرار
    elif data.startswith("interval_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة فترة التكرار للمجموعة: {group_id} ⏰\n"
            "يرجى اختيار الفترة الزمنية بين الرسائل:",
            reply_markup=kb.interval_options_keyboard(group_id)
        )
    
    elif data.startswith("interval_set:"):
        parts = data.split(":")
        group_id = parts[1]
        interval = int(parts[2])
        
        success, message = db.update_group_interval(group_id, interval)
        if success:
            # إعادة جدولة المهمة بالفترة الجديدة
            schedule_periodic_message(context.application, group_id)
            await query.edit_message_text(
                f"✅ {message}\n\n"
                "يرجى اختيار إجراء آخر:",
                reply_markup=kb.interval_options_keyboard(group_id)
            )
        else:
            await query.edit_message_text(
                f"❌ {message}\n\n"
                "يرجى المحاولة مرة أخرى:",
                reply_markup=kb.interval_options_keyboard(group_id)
            )
    
    elif data.startswith("interval_activate:") or data.startswith("interval_deactivate:"):
        group_id = data.split(":")[1]
        is_active = data.startswith("interval_activate")
        
        success, message = db.update_group_status(group_id, is_active)
        if success:
            # إعادة جدولة أو إلغاء المهمة حسب الحالة الجديدة
            schedule_periodic_message(context.application, group_id)
            await query.edit_message_text(
                f"✅ {message}\n\n"
                "يرجى اختيار إجراء آخر:",
                reply_markup=kb.interval_options_keyboard(group_id)
            )
        else:
            await query.edit_message_text(
                f"❌ {message}\n\n"
                "يرجى المحاولة مرة أخرى:",
                reply_markup=kb.interval_options_keyboard(group_id)
            )
    
    # معالجة أزرار إدارة شكل الرسالة
    elif data.startswith("format_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة شكل وتوقيت الرسالة للمجموعة: {group_id} ✉️\n"
            "يرجى اختيار شكل الرسالة والمنطقة الزمنية:",
            reply_markup=kb.format_options_keyboard(group_id)
        )
    
    elif data.startswith("format_set:"):
        parts = data.split(":")
        group_id = parts[1]
        format_id = int(parts[2])
        
        group_settings = db.get_group_settings(group_id)
        if group_settings:
            timezone = group_settings["timezone"]
            success, message = db.update_group_message_format(group_id, format_id, timezone)
            if success:
                await query.edit_message_text(
                    f"✅ {message}\n\n"
                    "يرجى اختيار إجراء آخر:",
                    reply_markup=kb.format_options_keyboard(group_id)
                )
            else:
                await query.edit_message_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى:",
                    reply_markup=kb.format_options_keyboard(group_id)
                )
    
    elif data.startswith("format_set_tz:"):
        parts = data.split(":")
        group_id = parts[1]
        timezone = parts[2]
        
        group_settings = db.get_group_settings(group_id)
        if group_settings:
            format_id = group_settings["message_format"]
            success, message = db.update_group_message_format(group_id, format_id, timezone)
            if success:
                await query.edit_message_text(
                    f"✅ {message}\n\n"
                    "يرجى اختيار إجراء آخر:",
                    reply_markup=kb.format_options_keyboard(group_id)
                )
            else:
                await query.edit_message_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى:",
                    reply_markup=kb.format_options_keyboard(group_id)
                )
    
    # معالجة أزرار إدارة محاولات المستخدمين
    elif data.startswith("attempts_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة محاولات المستخدمين للمجموعة: {group_id} 👤\n"
            "يرجى اختيار المستخدم الذي تريد إدارة محاولاته:",
            reply_markup=kb.select_user_for_attempts_keyboard(group_id)
        )
    
    elif data.startswith("attempts_user_page:"):
        parts = data.split(":")
        group_id = parts[1]
        page = int(parts[2])
        await query.edit_message_text(
            f"إدارة محاولات المستخدمين للمجموعة: {group_id} 👤 (صفحة {page})\n"
            "يرجى اختيار المستخدم الذي تريد إدارة محاولاته:",
            reply_markup=kb.select_user_for_attempts_keyboard(group_id, page)
        )
    
    elif data.startswith("attempts_select_user:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        await query.edit_message_text(
            f"إدارة محاولات المستخدم: {user_id} في المجموعة: {group_id} 👤\n"
            "يرجى اختيار الإجراء الذي تريد القيام به:",
            reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
        )
    
    elif data.startswith("attempts_add:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        context.user_data["admin_action"] = "add_attempts"
        context.user_data["group_id"] = group_id
        context.user_data["user_id"] = user_id
        await query.edit_message_text(
            f"إضافة محاولات للمستخدم: {user_id} في المجموعة: {group_id} ➕\n"
            "يرجى إدخال عدد المحاولات التي تريد إضافتها:",
            reply_markup=kb.back_keyboard(f"attempts_select_user:{group_id}:{user_id}")
        )
        return WAITING_FOR_ADD_ATTEMPTS
    
    elif data.startswith("attempts_remove:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        context.user_data["admin_action"] = "remove_attempts"
        context.user_data["group_id"] = group_id
        context.user_data["user_id"] = user_id
        await query.edit_message_text(
            f"حذف محاولات من المستخدم: {user_id} في المجموعة: {group_id} ➖\n"
            "يرجى إدخال عدد المحاولات التي تريد حذفها:",
            reply_markup=kb.back_keyboard(f"attempts_select_user:{group_id}:{user_id}")
        )
        return WAITING_FOR_REMOVE_ATTEMPTS
    
    elif data.startswith("attempts_ban:") or data.startswith("attempts_unban:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        is_ban = data.startswith("attempts_ban")
        
        if is_ban:
            success = db.ban_user(user_id, group_id)
            action_text = "حظر"
        else:
            success = db.unban_user(user_id, group_id)
            action_text = "إلغاء حظر"
        
        if success:
            await query.edit_message_text(
                f"✅ تم {action_text} المستخدم بنجاح.\n\n"
                "يرجى اختيار إجراء آخر:",
                reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
            )
        else:
            await query.edit_message_text(
                f"❌ حدث خطأ أثناء {action_text} المستخدم.\n\n"
                "يرجى المحاولة مرة أخرى:",
                reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
            )
    
    elif data.startswith("attempts_set_default:"):
        group_id = data.split(":")[1]
        context.user_data["admin_action"] = "set_default_attempts"
        context.user_data["group_id"] = group_id
        await query.edit_message_text(
            f"تعديل الحد الافتراضي للمحاولات للمجموعة: {group_id} ⚙️\n"
            "يرجى إدخال العدد الأقصى للمحاولات الذي سيحصل عليه أي مستخدم جديد:",
            reply_markup=kb.back_keyboard(f"attempts_select_group:{group_id}")
        )
        return WAITING_FOR_MAX_ATTEMPTS
    
    # معالجة أزرار إدارة المسؤولين
    elif data == "admin_add":
        context.user_data["admin_action"] = "add_admin"
        await query.edit_message_text(
            "إضافة مسؤول جديد 👑\n"
            "يرجى إدخال معرف المستخدم (User ID) للمسؤول الجديد:",
            reply_markup=kb.back_keyboard("admin_manage_admins")
        )
        return WAITING_FOR_ADMIN_ID
    
    elif data == "admin_select_remove":
        await query.edit_message_text(
            "إزالة مسؤول 👑\n"
            "يرجى اختيار المسؤول الذي تريد إزالته:",
            reply_markup=kb.select_admin_to_remove_keyboard()
        )
    
    elif data.startswith("admin_remove:"):
        admin_id = int(data.split(":")[1])
        success, message = db.remove_admin(admin_id)
        if success:
            await query.edit_message_text(
                f"✅ {message}\n\n"
                "يرجى اختيار الإجراء التالي:",
                reply_markup=kb.manage_admins_keyboard()
            )
        else:
            await query.edit_message_text(
                f"❌ {message}\n\n"
                "يرجى اختيار مسؤول آخر:",
                reply_markup=kb.select_admin_to_remove_keyboard()
            )
    
    # معالجة زر نسخ الرمز
    elif data.startswith("copy_code:"):
        group_id = data.split(":")[1]
        
        # الحصول على إعدادات المجموعة
        group_settings = db.get_group_settings(group_id)
        if not group_settings:
            await query.answer("❌ حدث خطأ: المجموعة غير موجودة.", show_alert=True)
            return
        
        # التحقق من عدد المحاولات المتبقية للمستخدم
        attempts_left, is_banned = db.get_user_attempts(user_id, group_id)
        
        if is_banned:
            await query.answer("⚠️ أنت محظور من استخدام هذه الخدمة في هذه المجموعة.", show_alert=True)
            return
        
        if attempts_left <= 0:
            await query.answer(f"⚠️ لقد استنفدت محاولاتك ({group_settings["max_attempts"]}) لنسخ الرمز لهذه المجموعة.", show_alert=True)
            return
        
        # توليد رمز TOTP
        totp_secret = group_settings["totp_secret"]
        code = totp.generate_totp(totp_secret)
        remaining_seconds = totp.get_remaining_seconds()
        
        # تقليل عدد المحاولات المتبقية
        db.decrement_user_attempt(user_id, group_id)
        attempts_left -= 1
        
        # إرسال الرمز في رسالة خاصة
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔐 *رمز المصادقة الخاص بك:* `{code}`\n\n"
                     f"⏱ هذا الرمز صالح لمدة *{remaining_seconds} ثانية* فقط.\n"
                     f"👤 المحاولات المتبقية لك: *{attempts_left}*",
                parse_mode=ParseMode.MARKDOWN
            )
            await query.answer("✅ تم إرسال رمز المصادقة إليك في رسالة خاصة.")
        except TelegramError as e:
            logger.error(f"خطأ في إرسال رمز المصادقة إلى المستخدم {user_id}: {e}")
            await query.answer("❌ حدث خطأ في إرسال الرمز. يرجى التأكد من أنك بدأت محادثة مع البوت أولاً.", show_alert=True)
    
    elif data == "no_op":
        # لا شيء، فقط لإزالة علامة التحميل
        pass

# معالجات الرسائل
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل النصية."""
    user_id = update.effective_user.id
    text = update.message.text
    
    # التحقق من وجود إجراء إداري قيد التنفيذ
    if "admin_action" not in context.user_data:
        # لا يوجد إجراء إداري، تجاهل الرسالة
        return ConversationHandler.END
    
    admin_action = context.user_data["admin_action"]
    
    # إضافة مجموعة جديدة
    if admin_action == "add_group" and context.user_data.get("waiting_for") == "group_id":
        try:
            group_id = int(text)
            context.user_data["group_id"] = group_id
            context.user_data["waiting_for"] = "totp_secret"
            await update.message.reply_text(
                f"تم تحديد معرف المجموعة: {group_id}\n"
                "الآن يرجى إدخال المفتاح السري TOTP (TOTP Secret):"
            )
            return WAITING_FOR_TOTP_SECRET
        except ValueError:
            await update.message.reply_text(
                "❌ معرف المجموعة يجب أن يكون رقماً صحيحاً.\n"
                "يرجى إدخال معرف المجموعة مرة أخرى:"
            )
            return WAITING_FOR_GROUP_ID
    
    # إدخال TOTP Secret لمجموعة جديدة
    elif admin_action == "add_group" and context.user_data.get("waiting_for") == "totp_secret":
        totp_secret = text.strip().upper()
        group_id = context.user_data["group_id"]
        
        # التحقق من صحة المفتاح السري
        if not totp.validate_totp_secret(totp_secret):
            await update.message.reply_text(
                "❌ المفتاح السري TOTP غير صالح.\n"
                "يرجى إدخال مفتاح صالح (يجب أن يكون بتنسيق Base32):"
            )
            return WAITING_FOR_TOTP_SECRET
        
        # إضافة المجموعة إلى قاعدة البيانات
        success, message = db.add_or_update_group(group_id, totp_secret)
        if success:
            # جدولة إرسال الرسائل الدورية
            schedule_periodic_message(context.application, group_id)
            await update.message.reply_text(
                f"✅ {message}\n\n"
                "تمت إضافة المجموعة بنجاح وتفعيل إرسال الرسائل الدورية.",
                reply_markup=kb.admin_main_keyboard()
            )
        else:
            await update.message.reply_text(
                f"❌ {message}\n\n"
                "يرجى المحاولة مرة أخرى لاحقاً.",
                reply_markup=kb.admin_main_keyboard()
            )
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # تعديل TOTP Secret لمجموعة حالية
    elif admin_action == "edit_secret":
        totp_secret = text.strip().upper()
        group_id = context.user_data["group_id"]
        
        # التحقق من صحة المفتاح السري
        if not totp.validate_totp_secret(totp_secret):
            await update.message.reply_text(
                "❌ المفتاح السري TOTP غير صالح.\n"
                "يرجى إدخال مفتاح صالح (يجب أن يكون بتنسيق Base32):"
            )
            return WAITING_FOR_NEW_SECRET
        
        # الحصول على إعدادات المجموعة الحالية
        group_settings = db.get_group_settings(group_id)
        if not group_settings:
            await update.message.reply_text(
                "❌ المجموعة غير موجودة.\n\n"
                "يرجى العودة إلى القائمة الرئيسية:",
                reply_markup=kb.admin_main_keyboard()
            )
            context.user_data.clear()
            return ConversationHandler.END
        
        # تحديث المفتاح السري
        success, message = db.add_or_update_group(
            group_id,
            totp_secret,
            group_settings["interval_minutes"],
            group_settings["message_format"],
            group_settings["timezone"],
            group_settings["max_attempts"],
            group_settings["is_active"],
            group_settings["job_id"]
        )
        
        if success:
            await update.message.reply_text(
                f"✅ {message}\n\n"
                "تم تحديث المفتاح السري TOTP بنجاح.",
                reply_markup=kb.admin_main_keyboard()
            )
        else:
            await update.message.reply_text(
                f"❌ {message}\n\n"
                "يرجى المحاولة مرة أخرى لاحقاً.",
                reply_markup=kb.admin_main_keyboard()
            )
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # إضافة مسؤول جديد
    elif admin_action == "add_admin":
        try:
            admin_id = int(text)
            success, message = db.add_admin(admin_id)
            if success:
                await update.message.reply_text(
                    f"✅ {message}\n\n"
                    "تمت إضافة المسؤول بنجاح.",
                    reply_markup=kb.admin_main_keyboard()
                )
            else:
                await update.message.reply_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى لاحقاً.",
                    reply_markup=kb.admin_main_keyboard()
                )
        except ValueError:
            await update.message.reply_text(
                "❌ معرف المستخدم يجب أن يكون رقماً صحيحاً.\n"
                "يرجى إدخال معرف المستخدم مرة أخرى:"
            )
            return WAITING_FOR_ADMIN_ID
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # تعديل الحد الافتراضي للمحاولات للمجموعة
    elif admin_action == "set_default_attempts":
        try:
            max_attempts = int(text)
            if max_attempts <= 0:
                await update.message.reply_text(
                    "❌ يجب أن يكون عدد المحاولات أكبر من صفر.\n"
                    "يرجى إدخال عدد المحاولات مرة أخرى:"
                )
                return WAITING_FOR_MAX_ATTEMPTS
            
            group_id = context.user_data["group_id"]
            success, message = db.update_group_max_attempts(group_id, max_attempts)
            
            if success:
                await update.message.reply_text(
                    f"✅ {message}\n\n"
                    "تم تحديث الحد الافتراضي للمحاولات بنجاح.",
                    reply_markup=kb.select_user_for_attempts_keyboard(group_id)
                )
            else:
                await update.message.reply_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى لاحقاً.",
                    reply_markup=kb.select_user_for_attempts_keyboard(group_id)
                )
        except ValueError:
            await update.message.reply_text(
                "❌ عدد المحاولات يجب أن يكون رقماً صحيحاً.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_MAX_ATTEMPTS
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # إضافة محاولات لمستخدم
    elif admin_action == "add_attempts":
        try:
            attempts_to_add = int(text)
            if attempts_to_add <= 0:
                await update.message.reply_text(
                    "❌ يجب أن يكون عدد المحاولات المضافة أكبر من صفر.\n"
                    "يرجى إدخال عدد المحاولات مرة أخرى:"
                )
                return WAITING_FOR_ADD_ATTEMPTS
            
            group_id = context.user_data["group_id"]
            user_id = context.user_data["user_id"]
            success, message = db.add_user_attempts(user_id, group_id, attempts_to_add)
            
            if success:
                await update.message.reply_text(
                    f"✅ {message}",
                    reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
                )
            else:
                await update.message.reply_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى لاحقاً.",
                    reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
                )
        except ValueError:
            await update.message.reply_text(
                "❌ عدد المحاولات يجب أن يكون رقماً صحيحاً.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_ADD_ATTEMPTS
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # حذف محاولات من مستخدم
    elif admin_action == "remove_attempts":
        try:
            attempts_to_remove = int(text)
            if attempts_to_remove <= 0:
                await update.message.reply_text(
                    "❌ يجب أن يكون عدد المحاولات المحذوفة أكبر من صفر.\n"
                    "يرجى إدخال عدد المحاولات مرة أخرى:"
                )
                return WAITING_FOR_REMOVE_ATTEMPTS
            
            group_id = context.user_data["group_id"]
            user_id = context.user_data["user_id"]
            success, message = db.remove_user_attempts(user_id, group_id, attempts_to_remove)
            
            if success:
                await update.message.reply_text(
                    f"✅ {message}",
                    reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
                )
            else:
                await update.message.reply_text(
                    f"❌ {message}\n\n"
                    "يرجى المحاولة مرة أخرى لاحقاً.",
                    reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
                )
        except ValueError:
            await update.message.reply_text(
                "❌ عدد المحاولات يجب أن يكون رقماً صحيحاً.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_REMOVE_ATTEMPTS
        
        # إنهاء المحادثة
        context.user_data.clear()
        return ConversationHandler.END
    
    # إذا وصلنا إلى هنا، فهناك خطأ في حالة المحادثة
    context.user_data.clear()
    await update.message.reply_text(
        "❌ حدث خطأ في معالجة طلبك.\n"
        "يرجى المحاولة مرة أخرى من خلال الأمر /admin.",
        reply_markup=kb.admin_main_keyboard()
    )
    return ConversationHandler.END

async def handle_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال معرف المجموعة."""
    context.user_data["waiting_for"] = "group_id"
    return await handle_text(update, context)

async def handle_totp_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال TOTP Secret."""
    context.user_data["waiting_for"] = "totp_secret"
    return await handle_text(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة الحالية."""
    context.user_data.clear()
    await update.message.reply_text(
        "تم إلغاء العملية الحالية.\n"
        "يمكنك استخدام الأمر /admin للعودة إلى لوحة التحكم.",
        reply_markup=kb.admin_main_keyboard()
    )
    return ConversationHandler.END

def main():
    """النقطة الرئيسية لتشغيل البوت."""
    # تهيئة قاعدة البيانات
    db.initialize_database()
    
    # إنشاء تطبيق البوت
    application = Application.builder().token(config.TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    
    # إنشاء محادثة للأمر /admin
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            WAITING_FOR_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_id)],
            WAITING_FOR_TOTP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_totp_secret)],
            WAITING_FOR_NEW_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            WAITING_FOR_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            WAITING_FOR_MAX_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            WAITING_FOR_ADD_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            WAITING_FOR_REMOVE_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    
    # إضافة معالج الأزرار
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # تعيين أوامر البوت
    commands = [
        BotCommand("start", "بدء استخدام البوت"),
        BotCommand("admin", "الوصول إلى لوحة تحكم المسؤول"),
        BotCommand("cancel", "إلغاء العملية الحالية"),
    ]
    application.bot.set_my_commands(commands)
    
    # جدولة المهام الدورية لجميع المجموعات المفعلة
    groups = db.get_all_groups()
    for group in groups:
        if group["is_active"]:
            schedule_periodic_message(application, group["group_id"])
            logger.info(f"تمت جدولة المهام الدورية للمجموعة {group[\"group_id\"]}")
    
    # بدء تشغيل البوت
    application.run_polling()

if __name__ == "__main__":
    main()

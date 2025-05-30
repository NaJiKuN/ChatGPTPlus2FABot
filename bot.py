# /home/ec2-user/projects/ChatGPTPlus2FABot/bot.py M3.01
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
        logger.warning(f"منطقة زمنية غير معروفة {group_settings['timezone']} للمجموعة {group_settings['group_id']}. استخدام GMT كافتراضي.")
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
    message_text += "\n\nاضغط على زر 'نسخ الرمز' أدناه للحصول على رمز المصادقة في رسالة خاصة."
    
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
            "يمكنك الحصول على الرمز عبر الضغط على زر 'نسخ الرمز' في الرسائل المرسلة إلى المجموعة."
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
            "اختر المجموعة التي تريد إدارة فترة التكرار لها:",
            reply_markup=kb.select_group_for_interval_keyboard()
        )
    
    elif data == "admin_manage_format":
        await query.edit_message_text(
            "إدارة شكل وتوقيت الرسالة ✉️\n"
            "اختر المجموعة التي تريد إدارة شكل الرسالة لها:",
            reply_markup=kb.select_group_for_format_keyboard()
        )
    
    elif data == "admin_manage_attempts":
        await query.edit_message_text(
            "إدارة محاولات المستخدمين 👤\n"
            "اختر المجموعة التي تريد إدارة محاولات المستخدمين فيها:",
            reply_markup=kb.select_group_for_attempts_keyboard()
        )
    
    elif data == "admin_manage_admins":
        await query.edit_message_text(
            "إدارة المسؤولين 👑\n"
            "يمكنك إضافة أو إزالة مسؤولين من هنا:",
            reply_markup=kb.manage_admins_keyboard()
        )
    
    elif data == "admin_close":
        await query.edit_message_text("تم إغلاق لوحة التحكم. استخدم الأمر /admin لفتحها مرة أخرى.")
    
    # معالجة أزرار إدارة المجموعات
    elif data == "group_select_edit":
        await query.edit_message_text(
            "تعديل مجموعة حالية ✏️\n"
            "اختر المجموعة التي تريد تعديلها:",
            reply_markup=kb.select_group_keyboard("group_edit")
        )
    
    elif data == "group_select_delete":
        await query.edit_message_text(
            "حذف مجموعة ➖\n"
            "اختر المجموعة التي تريد حذفها:",
            reply_markup=kb.select_group_keyboard("group_delete")
        )
    
    elif data.startswith("group_edit:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"تعديل المجموعة: {group_id} ✏️\n"
            "اختر الإجراء الذي تريد القيام به:",
            reply_markup=kb.edit_group_options_keyboard(group_id)
        )
    
    elif data.startswith("group_delete:"):
        group_id = data.split(":")[1]
        success, message = db.remove_group(group_id)
        
        # إلغاء المهمة المجدولة إذا كانت موجودة
        group_settings = db.get_group_settings(group_id)
        if group_settings and group_settings["job_id"]:
            try:
                context.application.job_queue.scheduler.remove_job(group_settings["job_id"])
                logger.info(f"تم إلغاء المهمة المجدولة للمجموعة {group_id}")
            except Exception as e:
                logger.error(f"خطأ في إلغاء المهمة المجدولة للمجموعة {group_id}: {e}")
        
        await query.edit_message_text(
            f"نتيجة حذف المجموعة: {message}\n"
            "العودة إلى إدارة المجموعات:",
            reply_markup=kb.back_keyboard("admin_manage_groups")
        )
    
    # معالجة أزرار إدارة فترة التكرار
    elif data.startswith("interval_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة فترة التكرار للمجموعة: {group_id} ⏰\n"
            "اختر الفترة الزمنية المطلوبة (بالدقائق) أو قم بتفعيل/إيقاف الإرسال الدوري:",
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
            f"نتيجة تحديث فترة التكرار: {message}\n"
            f"الفترة الجديدة: {interval} دقيقة\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.interval_options_keyboard(group_id)
        )
    
    elif data.startswith("interval_activate:"):
        group_id = data.split(":")[1]
        success, message = db.update_group_status(group_id, True)
        if success:
            # جدولة المهمة بعد التفعيل
            schedule_periodic_message(context.application, group_id)
        
        await query.edit_message_text(
            f"نتيجة تفعيل الإرسال الدوري: {message}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.interval_options_keyboard(group_id)
        )
    
    elif data.startswith("interval_deactivate:"):
        group_id = data.split(":")[1]
        success, message = db.update_group_status(group_id, False)
        if success:
            # إلغاء المهمة بعد إيقاف التفعيل
            group_settings = db.get_group_settings(group_id)
            if group_settings and group_settings["job_id"]:
                try:
                    context.application.job_queue.scheduler.remove_job(group_settings["job_id"])
                    db.update_group_job_id(group_id, None)
                    logger.info(f"تم إلغاء المهمة المجدولة للمجموعة {group_id}")
                except Exception as e:
                    logger.error(f"خطأ في إلغاء المهمة المجدولة للمجموعة {group_id}: {e}")
        
        await query.edit_message_text(
            f"نتيجة إيقاف الإرسال الدوري: {message}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.interval_options_keyboard(group_id)
        )
    
    # معالجة أزرار إدارة شكل الرسالة
    elif data.startswith("format_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة شكل وتوقيت الرسالة للمجموعة: {group_id} ✉️\n"
            "اختر شكل الرسالة والمنطقة الزمنية:",
            reply_markup=kb.format_options_keyboard(group_id)
        )
    
    elif data.startswith("format_set:"):
        parts = data.split(":")
        group_id = parts[1]
        format_id = int(parts[2])
        
        # الحصول على المنطقة الزمنية الحالية
        group_settings = db.get_group_settings(group_id)
        timezone = group_settings["timezone"] if group_settings else "GMT"
        
        success, message = db.update_group_message_format(group_id, format_id, timezone)
        
        await query.edit_message_text(
            f"نتيجة تحديث شكل الرسالة: {message}\n"
            f"الشكل الجديد: {format_id}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.format_options_keyboard(group_id)
        )
    
    elif data.startswith("format_set_tz:"):
        parts = data.split(":")
        group_id = parts[1]
        timezone = parts[2]
        
        # الحصول على شكل الرسالة الحالي
        group_settings = db.get_group_settings(group_id)
        format_id = group_settings["message_format"] if group_settings else 1
        
        success, message = db.update_group_message_format(group_id, format_id, timezone)
        
        await query.edit_message_text(
            f"نتيجة تحديث المنطقة الزمنية: {message}\n"
            f"المنطقة الزمنية الجديدة: {timezone}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.format_options_keyboard(group_id)
        )
    
    # معالجة أزرار إدارة محاولات المستخدمين
    elif data.startswith("attempts_select_group:"):
        group_id = data.split(":")[1]
        await query.edit_message_text(
            f"إدارة محاولات المستخدمين للمجموعة: {group_id} 👤\n"
            "اختر المستخدم الذي تريد إدارة محاولاته:",
            reply_markup=kb.select_user_for_attempts_keyboard(group_id)
        )
    
    elif data.startswith("attempts_user_page:"):
        parts = data.split(":")
        group_id = parts[1]
        page = int(parts[2])
        
        await query.edit_message_text(
            f"إدارة محاولات المستخدمين للمجموعة: {group_id} 👤 (صفحة {page})\n"
            "اختر المستخدم الذي تريد إدارة محاولاته:",
            reply_markup=kb.select_user_for_attempts_keyboard(group_id, page)
        )
    
    elif data.startswith("attempts_select_user:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        
        await query.edit_message_text(
            f"إدارة محاولات المستخدم: {user_id} في المجموعة: {group_id} 👤\n"
            "اختر الإجراء الذي تريد القيام به:",
            reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
        )
    
    elif data.startswith("attempts_ban:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        
        success = db.ban_user(user_id, group_id)
        
        await query.edit_message_text(
            f"تم حظر المستخدم: {user_id} من طلب الرموز في المجموعة: {group_id}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
        )
    
    elif data.startswith("attempts_unban:"):
        parts = data.split(":")
        group_id = parts[1]
        user_id = int(parts[2])
        
        success = db.unban_user(user_id, group_id)
        
        await query.edit_message_text(
            f"تم إلغاء حظر المستخدم: {user_id} في المجموعة: {group_id}\n\n"
            "اختر إجراءً آخر:",
            reply_markup=kb.manage_user_attempts_keyboard(group_id, user_id)
        )
    
    elif data.startswith("attempts_set_default:"):
        group_id = data.split(":")[1]
        context.user_data["temp_group_id"] = group_id
        
        await query.edit_message_text(
            f"تعديل الحد الافتراضي للمحاولات للمجموعة: {group_id} ⚙️\n"
            "يرجى إدخال العدد الأقصى للمحاولات الذي سيحصل عليه المستخدمون الجدد في هذه المجموعة:"
        )
        return WAITING_FOR_MAX_ATTEMPTS
    
    # معالجة أزرار إدارة المسؤولين
    elif data == "admin_add":
        await query.edit_message_text(
            "إضافة مسؤول جديد ➕\n"
            "يرجى إدخال معرف المستخدم (User ID) للمسؤول الجديد:"
        )
        return WAITING_FOR_ADMIN_ID
    
    elif data == "admin_select_remove":
        await query.edit_message_text(
            "إزالة مسؤول ➖\n"
            "اختر المسؤول الذي تريد إزالته:",
            reply_markup=kb.select_admin_to_remove_keyboard()
        )
    
    elif data.startswith("admin_remove:"):
        admin_id = int(data.split(":")[1])
        success, message = db.remove_admin(admin_id)
        
        await query.edit_message_text(
            f"نتيجة إزالة المسؤول: {message}\n\n"
            "العودة إلى إدارة المسؤولين:",
            reply_markup=kb.back_keyboard("admin_manage_admins")
        )
    
    # معالجة زر طلب الرمز
    elif data.startswith("copy_code:"):
        group_id = data.split(":")[1]
        
        # الحصول على إعدادات المجموعة
        group_settings = db.get_group_settings(group_id)
        if not group_settings:
            await query.answer("عذراً، لم يتم العثور على إعدادات لهذه المجموعة.", show_alert=True)
            return
        
        # التحقق من عدد المحاولات المتبقية للمستخدم
        attempts_left, is_banned = db.get_user_attempts(user_id, group_id)
        
        if is_banned:
            await query.answer("⛔ أنت محظور من طلب الرموز لهذه المجموعة.", show_alert=True)
            return
        
        if attempts_left <= 0:
            await query.answer(f"⚠️ لقد استنفدت محاولاتك ({group_settings['max_attempts']}) لنسخ الرمز لهذه المجموعة.", show_alert=True)
            return
        
        # توليد رمز TOTP
        totp_secret = group_settings["totp_secret"]
        code = totp.generate_totp(totp_secret)
        remaining_seconds = totp.get_remaining_seconds()
        
        # تقليل عدد المحاولات المتبقية
        db.decrement_user_attempt(user_id, group_id)
        
        # الحصول على عدد المحاولات المتبقية بعد التقليل
        new_attempts_left, _ = db.get_user_attempts(user_id, group_id)
        
        # إرسال الرمز في رسالة خاصة
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔑 *رمز المصادقة الخاص بك:* `{code}`\n\n"
                     f"⏱ *صالح لمدة:* `{remaining_seconds} ثانية`\n"
                     f"🔄 *المحاولات المتبقية:* `{new_attempts_left}`\n\n"
                     f"⚠️ *تنبيه:* هذا الرمز صالح لمدة 30 ثانية فقط.",
                parse_mode=ParseMode.MARKDOWN
            )
            await query.answer("تم إرسال الرمز إليك في رسالة خاصة.", show_alert=True)
        except TelegramError as e:
            logger.error(f"خطأ في إرسال الرمز إلى المستخدم {user_id}: {e}")
            await query.answer("عذراً، لم نتمكن من إرسال الرمز إليك. يرجى بدء محادثة مع البوت أولاً.", show_alert=True)
    
    elif data == "no_op":
        # زر بدون عملية (للعرض فقط)
        await query.answer()
    
    return ConversationHandler.END

# معالجات المحادثة
async def add_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية إضافة مجموعة جديدة."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "إضافة مجموعة جديدة ➕\n"
        "يرجى إدخال معرف المجموعة (Group ID):"
    )
    return WAITING_FOR_GROUP_ID

async def add_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال معرف المجموعة."""
    text = update.message.text.strip()
    
    # التحقق من صحة معرف المجموعة
    try:
        group_id = int(text)
        if not (text.startswith("-100") and len(text) > 4):
            await update.message.reply_text(
                "⚠️ معرف المجموعة غير صالح. يجب أن يبدأ بـ -100 ويكون رقماً صحيحاً.\n"
                "يرجى إدخال معرف المجموعة مرة أخرى:"
            )
            return WAITING_FOR_GROUP_ID
    except ValueError:
        await update.message.reply_text(
            "⚠️ معرف المجموعة غير صالح. يجب أن يكون رقماً صحيحاً.\n"
            "يرجى إدخال معرف المجموعة مرة أخرى:"
        )
        return WAITING_FOR_GROUP_ID
    
    # حفظ معرف المجموعة في بيانات المستخدم المؤقتة
    context.user_data["temp_group_id"] = group_id
    
    await update.message.reply_text(
        f"تم استلام معرف المجموعة: {group_id}\n"
        "الآن يرجى إدخال المفتاح السري TOTP (TOTP Secret):"
    )
    return WAITING_FOR_TOTP_SECRET

async def add_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال المفتاح السري TOTP."""
    totp_secret = update.message.text.strip()
    group_id = context.user_data["temp_group_id"]
    
    # التحقق من صحة المفتاح السري
    if not totp.validate_totp_secret(totp_secret):
        await update.message.reply_text(
            "⚠️ المفتاح السري TOTP غير صالح.\n"
            "يرجى إدخال مفتاح صالح:"
        )
        return WAITING_FOR_TOTP_SECRET
    
    # إضافة المجموعة إلى قاعدة البيانات
    success, message = db.add_or_update_group(group_id, totp_secret)
    
    if success:
        # جدولة إرسال الرسائل الدورية
        schedule_periodic_message(context.application, group_id)
    
    await update.message.reply_text(
        f"نتيجة إضافة المجموعة: {message}\n\n"
        "العودة إلى إدارة المجموعات:",
        reply_markup=kb.back_keyboard("admin_manage_groups")
    )
    
    # تنظيف البيانات المؤقتة
    if "temp_group_id" in context.user_data:
        del context.user_data["temp_group_id"]
    
    return ConversationHandler.END

async def edit_group_secret_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية تعديل المفتاح السري لمجموعة."""
    query = update.callback_query
    await query.answer()
    
    group_id = query.data.split(":")[1]
    context.user_data["temp_group_id"] = group_id
    
    await query.edit_message_text(
        f"تعديل المفتاح السري TOTP للمجموعة: {group_id} 🔑\n"
        "يرجى إدخال المفتاح السري الجديد:"
    )
    return WAITING_FOR_NEW_SECRET

async def edit_group_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال المفتاح السري الجديد."""
    totp_secret = update.message.text.strip()
    group_id = context.user_data["temp_group_id"]
    
    # التحقق من صحة المفتاح السري
    if not totp.validate_totp_secret(totp_secret):
        await update.message.reply_text(
            "⚠️ المفتاح السري TOTP غير صالح.\n"
            "يرجى إدخال مفتاح صالح:"
        )
        return WAITING_FOR_NEW_SECRET
    
    # الحصول على الإعدادات الحالية للمجموعة
    group_settings = db.get_group_settings(group_id)
    if not group_settings:
        await update.message.reply_text(
            "⚠️ لم يتم العثور على إعدادات لهذه المجموعة.\n"
            "العودة إلى إدارة المجموعات:",
            reply_markup=kb.back_keyboard("admin_manage_groups")
        )
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
    
    await update.message.reply_text(
        f"نتيجة تحديث المفتاح السري: {message}\n\n"
        "العودة إلى إدارة المجموعات:",
        reply_markup=kb.back_keyboard("admin_manage_groups")
    )
    
    # تنظيف البيانات المؤقتة
    if "temp_group_id" in context.user_data:
        del context.user_data["temp_group_id"]
    
    return ConversationHandler.END

async def add_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال معرف المسؤول الجديد."""
    text = update.message.text.strip()
    
    # التحقق من صحة معرف المستخدم
    try:
        admin_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ معرف المستخدم غير صالح. يجب أن يكون رقماً صحيحاً.\n"
            "يرجى إدخال معرف المستخدم مرة أخرى:"
        )
        return WAITING_FOR_ADMIN_ID
    
    # إضافة المسؤول إلى قاعدة البيانات
    success, message = db.add_admin(admin_id)
    
    await update.message.reply_text(
        f"نتيجة إضافة المسؤول: {message}\n\n"
        "العودة إلى إدارة المسؤولين:",
        reply_markup=kb.back_keyboard("admin_manage_admins")
    )
    
    return ConversationHandler.END

async def set_max_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال الحد الأقصى للمحاولات."""
    text = update.message.text.strip()
    group_id = context.user_data["temp_group_id"]
    
    # التحقق من صحة عدد المحاولات
    try:
        max_attempts = int(text)
        if max_attempts <= 0:
            await update.message.reply_text(
                "⚠️ عدد المحاولات يجب أن يكون أكبر من صفر.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_MAX_ATTEMPTS
    except ValueError:
        await update.message.reply_text(
            "⚠️ عدد المحاولات غير صالح. يجب أن يكون رقماً صحيحاً.\n"
            "يرجى إدخال عدد المحاولات مرة أخرى:"
        )
        return WAITING_FOR_MAX_ATTEMPTS
    
    # تحديث الحد الأقصى للمحاولات
    success, message = db.update_group_max_attempts(group_id, max_attempts)
    
    await update.message.reply_text(
        f"نتيجة تحديث الحد الأقصى للمحاولات: {message}\n\n"
        "العودة إلى إدارة محاولات المستخدمين:",
        reply_markup=kb.back_keyboard(f"attempts_select_group:{group_id}")
    )
    
    # تنظيف البيانات المؤقتة
    if "temp_group_id" in context.user_data:
        del context.user_data["temp_group_id"]
    
    return ConversationHandler.END

async def add_attempts_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية إضافة محاولات لمستخدم."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    group_id = parts[1]
    user_id = int(parts[2])
    
    context.user_data["temp_group_id"] = group_id
    context.user_data["temp_user_id"] = user_id
    
    await query.edit_message_text(
        f"إضافة محاولات للمستخدم: {user_id} في المجموعة: {group_id} ➕\n"
        "يرجى إدخال عدد المحاولات التي تريد إضافتها:"
    )
    return WAITING_FOR_ADD_ATTEMPTS

async def add_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال عدد المحاولات المضافة."""
    text = update.message.text.strip()
    group_id = context.user_data["temp_group_id"]
    user_id = context.user_data["temp_user_id"]
    
    # التحقق من صحة عدد المحاولات
    try:
        attempts = int(text)
        if attempts <= 0:
            await update.message.reply_text(
                "⚠️ عدد المحاولات يجب أن يكون أكبر من صفر.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_ADD_ATTEMPTS
    except ValueError:
        await update.message.reply_text(
            "⚠️ عدد المحاولات غير صالح. يجب أن يكون رقماً صحيحاً.\n"
            "يرجى إدخال عدد المحاولات مرة أخرى:"
        )
        return WAITING_FOR_ADD_ATTEMPTS
    
    # إضافة المحاولات
    success, message = db.add_user_attempts(user_id, group_id, attempts)
    
    await update.message.reply_text(
        f"نتيجة إضافة المحاولات: {message}\n\n"
        "العودة إلى إدارة محاولات المستخدم:",
        reply_markup=kb.back_keyboard(f"attempts_select_user:{group_id}:{user_id}")
    )
    
    # تنظيف البيانات المؤقتة
    if "temp_group_id" in context.user_data:
        del context.user_data["temp_group_id"]
    if "temp_user_id" in context.user_data:
        del context.user_data["temp_user_id"]
    
    return ConversationHandler.END

async def remove_attempts_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية حذف محاولات من مستخدم."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    group_id = parts[1]
    user_id = int(parts[2])
    
    context.user_data["temp_group_id"] = group_id
    context.user_data["temp_user_id"] = user_id
    
    await query.edit_message_text(
        f"حذف محاولات من المستخدم: {user_id} في المجموعة: {group_id} ➖\n"
        "يرجى إدخال عدد المحاولات التي تريد حذفها:"
    )
    return WAITING_FOR_REMOVE_ATTEMPTS

async def remove_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال عدد المحاولات المحذوفة."""
    text = update.message.text.strip()
    group_id = context.user_data["temp_group_id"]
    user_id = context.user_data["temp_user_id"]
    
    # التحقق من صحة عدد المحاولات
    try:
        attempts = int(text)
        if attempts <= 0:
            await update.message.reply_text(
                "⚠️ عدد المحاولات يجب أن يكون أكبر من صفر.\n"
                "يرجى إدخال عدد المحاولات مرة أخرى:"
            )
            return WAITING_FOR_REMOVE_ATTEMPTS
    except ValueError:
        await update.message.reply_text(
            "⚠️ عدد المحاولات غير صالح. يجب أن يكون رقماً صحيحاً.\n"
            "يرجى إدخال عدد المحاولات مرة أخرى:"
        )
        return WAITING_FOR_REMOVE_ATTEMPTS
    
    # حذف المحاولات
    success, message = db.remove_user_attempts(user_id, group_id, attempts)
    
    await update.message.reply_text(
        f"نتيجة حذف المحاولات: {message}\n\n"
        "العودة إلى إدارة محاولات المستخدم:",
        reply_markup=kb.back_keyboard(f"attempts_select_user:{group_id}:{user_id}")
    )
    
    # تنظيف البيانات المؤقتة
    if "temp_group_id" in context.user_data:
        del context.user_data["temp_group_id"]
    if "temp_user_id" in context.user_data:
        del context.user_data["temp_user_id"]
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة الحالية."""
    await update.message.reply_text(
        "تم إلغاء العملية الحالية.\n"
        "استخدم الأمر /admin للعودة إلى لوحة التحكم."
    )
    
    # تنظيف البيانات المؤقتة
    for key in list(context.user_data.keys()):
        if key.startswith("temp_"):
            del context.user_data[key]
    
    return ConversationHandler.END

async def post_init(application: Application):
    """تنفيذ الإجراءات بعد بدء البوت."""
    # تعيين أوامر البوت
    commands = [
        BotCommand("start", "بدء استخدام البوت"),
        BotCommand("admin", "الوصول إلى لوحة تحكم المسؤول")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("تم تعيين أوامر البوت.")
    
    # تحميل المهام المجدولة للمجموعات النشطة
    logger.info("جاري تحميل المهام المجدولة للمجموعات النشطة...")
    groups = db.get_all_groups()
    active_groups = [group for group in groups if group["is_active"]]
    
    for group in active_groups:
        schedule_periodic_message(application, group["group_id"])
    
    logger.info(f"تم تحميل وجدولة المهام لـ {len(active_groups)} مجموعة نشطة.")

def main():
    """النقطة الرئيسية لتشغيل البوت."""
    # إنشاء تطبيق البوت
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    
    # إضافة معالجات المحادثة
    add_group_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_group_start, pattern="^group_add$")],
        states={
            WAITING_FOR_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_id)],
            WAITING_FOR_TOTP_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_group_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    application.add_handler(add_group_conv)
    
    edit_secret_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_group_secret_start, pattern="^group_edit_secret:")],
        states={
            WAITING_FOR_NEW_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_group_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    application.add_handler(edit_secret_conv)
    
    manage_attempts_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_attempts_start, pattern="^attempts_add:"),
            CallbackQueryHandler(remove_attempts_start, pattern="^attempts_remove:"),
        ],
        states={
            WAITING_FOR_ADD_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_attempts)],
            WAITING_FOR_REMOVE_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_attempts)],
            WAITING_FOR_MAX_ATTEMPTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_max_attempts)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    application.add_handler(manage_attempts_conv)
    
    add_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u, c: u.callback_query.answer() or u.callback_query.edit_message_text(
            "إضافة مسؤول جديد ➕\n"
            "يرجى إدخال معرف المستخدم (User ID) للمسؤول الجديد:"
        ) or WAITING_FOR_ADMIN_ID, pattern="^admin_add$")],
        states={
            WAITING_FOR_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    application.add_handler(add_admin_conv)
    
    # إضافة معالج عام للأزرار
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # بدء تشغيل البوت
    logger.info("جاري بدء تشغيل البوت...")
    application.run_polling()

if __name__ == "__main__":
    main()

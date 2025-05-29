# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from utils import load_groups
import pyotp

# إعداد التسجيل
logger = logging.getLogger(__name__)

# تنسيقات الرسائل
FORMATS = {
    1: "🔐 *2FA Verification Code*\n\nNext code at: {next_time}",
    2: "🔐 *2FA Verification Code*\n\nNext code in: {interval}\nNext code at: {next_time}",
    3: "🔐 *2FA Verification Code*\n\nNext code in: {interval}\nCurrent Time: {current_time}\nNext Code at: {next_time}"
}

async def send_scheduled_message(application: Application, group_id: int) -> None:
    """
    إرسال رسالة مجدولة إلى المجموعة تحتوي على زر لنسخ رمز المصادقة الثنائية.
    
    Args:
        application: كائن التطبيق من python-telegram-bot.
        group_id: معرف المجموعة (int).
    """
    try:
        # تحميل إعدادات المجموعات
        groups = load_groups()
        group_id_str = str(group_id)
        
        # التحقق من وجود المجموعة وتفعيلها
        if group_id_str not in groups:
            logger.warning(f"Group {group_id} not found in groups.json.")
            return
        config = groups[group_id_str]
        if not config.get("active", False):
            logger.info(f"Group {group_id} is not active. Skipping scheduled message.")
            return
        if not config.get("secret"):
            logger.error(f"No TOTP secret found for group {group_id}. Skipping scheduled message.")
            return

        # الحصول على إعدادات المجموعة
        timezone_str = config.get("timezone", "UTC")
        format_id = config.get("format", 1)
        interval_minutes = config.get("interval_minutes", 10)

        # تحديد المنطقة الزمنية
        try:
            tz = pytz.timezone(timezone_str)
        except pytz:
            logger.error(f"Invalid timezone {timezone_str} for group {group_id}. Using UTC.")
            tz = pytz.timezone("UTC")

        # حساب الأوقات
        current_time = datetime.now(tz)
        next_time = current_time + timedelta(minutes=interval_minutes)
        
        # تنسيق الأوقات
        current_time_str = current_time.strftime("%I:%M:%S %p")
        next_time_str = next_time.strftime("%I:%M:%S %p")
        
        # تنسيق فترة التكرار
        if interval_minutes < 60:
            interval_display = f"{interval_minutes} minute{'s' if interval_minutes != 1 else ''}"
        else:
            hours = interval_minutes // 60
            interval_display = f"{hours} hour{'s' if hours != 1 else ''}"

        # إنشاء نص الرسالة بناءً على التنسيق
        message_text = FORMATS.get(format_id, FORMATS[1]).format(
            interval=interval_display,
            current_time=current_time_str,
            next_time=next_time_str
        )

        # إنشاء زر "Copy Code"
        keyboard = [[InlineKeyboardButton("Copy Code", callback_data=f"copy_code_{group_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # إرسال الرسالة
        await application.bot.send_message(
            chat_id=group_id,
            text=message_text,
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        logger.info(f"Scheduled message sent to group {group_id}.")

    except Exception as e:
        logger.error(f"Error sending scheduled message to group {group_id}: {e}")

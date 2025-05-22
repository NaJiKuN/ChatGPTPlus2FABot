#!/usr/bin/python3
import os
import time
import pyotp
import pytz
import asyncio
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext,
)
from functools import wraps
import logging
import sys

# تكوين الأساسيات
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
BOT_CHAT_ID = 792534650
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
ADMIN_ID = 764559466  # تم تحديثه إلى ID الخاص بك

# إعدادات النسخ
MAX_COPIES_PER_DAY = 5
current_copies = 0
last_reset_time = datetime.now()
allowed_users = set()  # مجموعة المستخدمين المسموح لهم بنسخ الرمز

# إعدادات اللغة
LANGUAGES = {
    'en': {
        'copy_button': '📋 Copy Code',
        'code_expires': 'The code is valid for 30 seconds from the time of copying.',
        'copies_remaining': 'Copies remaining today: {}',
        'no_copies_left': 'No copies left for today.',
        'admin_panel': 'Admin Panel',
        'add_user': '➕ Add User',
        'remove_user': '➖ Remove User',
        'increase_copies': '➕ Increase Copies',
        'decrease_copies': '➖ Decrease Copies',
        'user_added': 'User added successfully.',
        'user_removed': 'User removed successfully.',
        'copies_increased': 'Daily copies increased to {}.',
        'copies_decreased': 'Daily copies decreased to {}.',
        'next_code_at': 'Next code at {}',
        'language_button': '🌐 Change Language',
        'select_language': 'Select Language:',
        'language_changed': 'Language changed to {}.',
        'unauthorized': 'You are not authorized to perform this action.',
        'copy_alert_admin': 'User {} (IP: {}) copied the 2FA code. Remaining copies: {}'
    },
    'ar': {
        'copy_button': '📋 نسخ الرمز',
        'code_expires': 'الرمز صالح لمدة 30 ثانية من وقت النسخ.',
        'copies_remaining': 'عدد مرات النسخ المتبقية اليوم: {}',
        'no_copies_left': 'لا توجد محاولات نسخ متبقية لليوم.',
        'admin_panel': 'لوحة التحكم',
        'add_user': '➕ إضافة عضو',
        'remove_user': '➖ إزالة عضو',
        'increase_copies': '➕ زيادة النسخ',
        'decrease_copies': '➖ تقليل النسخ',
        'user_added': 'تمت إضافة العضو بنجاح.',
        'user_removed': 'تمت إزالة العضو بنجاح.',
        'copies_increased': 'تم زيادة عدد النسخ اليومية إلى {}.',
        'copies_decreased': 'تم تقليل عدد النسخ اليومية إلى {}.',
        'next_code_at': 'الرمز التالي عند {}',
        'language_button': '🌐 تغيير اللغة',
        'select_language': 'اختر اللغة:',
        'language_changed': 'تم تغيير اللغة إلى {}.',
        'unauthorized': 'غير مسموح لك بتنفيذ هذا الإجراء.',
        'copy_alert_admin': 'العضو {} (IP: {}) قام بنسخ رمز المصادقة. النسخ المتبقية: {}'
    }
}

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/chatgptplus2fa.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# تهيئة TOTP
totp = pyotp.TOTP(TOTP_SECRET)

# وظيفة المسؤول
def admin_required(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if user_id == ADMIN_ID:
            return await func(update, context, *args, **kwargs)
            
        try:
            chat_member = await context.bot.get_chat_member(GROUP_CHAT_ID, user_id)
            if chat_member.status in ['administrator', 'creator']:
                return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
        
        lang = user_language.get(user_id, 'en')
        await update.message.reply_text(LANGUAGES[lang]['unauthorized'])
        return
    return wrapped

async def send_2fa_code(context: CallbackContext):
    try:
        global current_copies, last_reset_time
        
        now = datetime.now()
        if now.date() != last_reset_time.date():
            current_copies = 0
            last_reset_time = now
        
        code = totp.now()
        next_code_time = (now + timedelta(minutes=5)).strftime("%I:%M:%S %p")
        
        keyboard = [
            [InlineKeyboardButton(LANGUAGES['ar']['copy_button'], callback_data='copy_code')],
            [InlineKeyboardButton(LANGUAGES['ar']['language_button'], callback_data='change_language')]
        ]
        
        try:
            chat_member = await context.bot.get_chat_member(GROUP_CHAT_ID, ADMIN_ID)
            if chat_member.status in ['administrator', 'creator']:
                keyboard.append([InlineKeyboardButton(LANGUAGES['ar']['admin_panel'], callback_data='admin_panel')])
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = f"رمز المصادقة الثنائية الجاهز.\n\n{LANGUAGES['ar']['next_code_at'].format(next_code_time)}"
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in send_2fa_code: {e}", exc_info=True)

async def main():
    try:
        # إضافة المسؤول إلى القائمة المسموح لهم
        allowed_users.add(ADMIN_ID)
        
        application = Application.builder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("admin", admin_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        job_queue = application.job_queue
        job_queue.run_repeating(send_2fa_code, interval=300, first=0)
        
        logger.info("Starting bot...")
        await application.run_polling()
    except Exception as e:
        logger.error(f"Bot failed: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

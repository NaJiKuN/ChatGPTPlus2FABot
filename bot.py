#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import traceback
from typing import Optional
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from user_agents import parse
import pyotp
import os
from datetime import datetime

# ======= إعدادات النظام الأساسية =======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_errors.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ======= الثوابت والإعدادات =======
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
GROUP_CHAT_ID = int(os.getenv('GROUP_CHAT_ID', "-1002329495586"))
TOTP_SECRET = os.getenv('TOTP_SECRET', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")

# ======= الديكوراتورات المساعدة =======
def safe_execute(func):
    """تنفيذ آمن للوظائف مع التعامل مع الأخطاء"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            if len(args) > 1 and hasattr(args[1], 'bot'):
                args[1].bot.send_message(
                    chat_id=args[0].effective_chat.id,
                    text="⚠️ حدث خطأ في العملية المطلوبة"
                )
            return None
    return wrapper

# ======= الوظائف الأساسية =======
def get_user_device(user_agent: str) -> str:
    """تحليل نوع الجهاز من User-Agent"""
    try:
        if not user_agent:
            return "جهاز غير معروف"
        
        ua = parse(user_agent)
        device_info = [
            ua.device.family if ua.device.family else "",
            ua.os.family if ua.os.family else "",
            ua.browser.family if ua.browser.family else ""
        ]
        return " | ".join(filter(None, device_info))
    except Exception as e:
        logger.warning(f"فشل تحليل الجهاز: {str(e)}")
        return "جهاز غير معروف"

def generate_2fa_code() -> str:
    """توليد رمز المصادقة الثنائية"""
    try:
        totp = pyotp.TOTP(TOTP_SECRET)
        return totp.now()
    except Exception as e:
        logger.error(f"فشل توليد الرمز: {str(e)}")
        return "000000"  # رمز افتراضي في حالة الخطأ

# ======= معالجات الأوامر =======
@safe_execute
def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    welcome_msg = (
        "مرحبًا! 👋\n"
        "أنا بوت المصادقة الثنائية.\n"
        "سأرسل رموز التحقق كل 10 دقائق تلقائيًا."
    )
    update.message.reply_text(welcome_msg)

@safe_execute
def send_2fa_code(update: Update, context: CallbackContext):
    """إرسال رمز المصادقة"""
    try:
        code = generate_2fa_code()
        device = "جهاز غير معروف"
        
        # محاولة الحصول على معلومات الجهاز
        try:
            updates = context.bot.get_updates(timeout=5)
            if updates:
                user_agent = updates[-1].effective_user._effective_user_agent
                device = get_user_device(user_agent)
        except Exception as e:
            logger.warning(f"فشل الحصول على معلومات الجهاز: {str(e)}")
        
        message = (
            "🔑 تم توليد رمز مصادقة جديد\n\n"
            f"الرمز: `{code}`\n"
            f"الجهاز: {device}\n"
            f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "صالح لمدة 10 دقائق ⏳"
        )
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"فشل إرسال الرمز: {str(e)}")
        if update.effective_chat:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ حدث خطأ أثناء إرسال الرمز"
            )

# ======= معالجة الأخطاء =======
def error_handler(update: Optional[Update], context: CallbackContext):
    """تسجيل ومعالجة جميع الأخطاء"""
    try:
        error_msg = str(context.error) if context.error else "خطأ غير معروف"
        
        logger.error(
            f"\n{'='*50}\n"
            f"حدث خطأ:\n"
            f"المحتوى: {update.to_dict() if update else 'لا يوجد'}\n"
            f"الخطأ: {error_msg}\n"
            f"التتبع: {''.join(traceback.format_tb(context.error.__traceback__))}\n"
            f"{'='*50}"
        )
        
        if update and update.effective_chat:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ حدث خطأ غير متوقع. تم إعلام الفريق التقني."
            )
    except Exception as e:
        logger.critical(f"فشل معالجة الخطأ: {str(e)}")

# ======= الوظائف المجدولة =======
def auto_send_2fa(context: CallbackContext):
    """إرسال تلقائي للرموز كل 10 دقائق"""
    try:
        code = generate_2fa_code()
        message = (
            "🔐 رمز المصادقة الجديد\n\n"
            f"الرمز: `{code}`\n"
            f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "صالح لمدة 10 دقائق ⏳"
        )
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"فشل الإرسال التلقائي: {str(e)}")

# ======= الإعدادات الرئيسية =======
def main():
    """تهيئة وتشغيل البوت"""
    try:
        # إنشاء الكائنات الأساسية
        updater = Updater(
            token=BOT_TOKEN,
            use_context=True,
            request_kwargs={'read_timeout': 10, 'connect_timeout': 10}
        )
        dp = updater.dispatcher
        
        # إضافة المعالجات
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("sendcode", send_2fa_code))
        dp.add_error_handler(error_handler)
        
        # الجدولة التلقائية
        job_queue = updater.job_queue
        job_queue.run_repeating(
            auto_send_2fa,
            interval=600,  # 10 دقائق
            first=0
        )
        
        # بدء البوت
        updater.start_polling()
        logger.info("بدأ البوت العمل بنجاح")
        updater.idle()
        
    except Exception as e:
        logger.critical(f"فشل تشغيل البوت: {str(e)}")
        raise

if __name__ == '__main__':
    main()

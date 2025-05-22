#!/usr/bin/python3
import os
import sys
import asyncio
import pyotp
import signal
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ContextTypes,
)
import logging
from typing import Dict, Set

# تكوين الأساسيات
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
ADMIN_ID = 764559466

# مسارات السجلات
LOG_FILE = "/var/log/chatgptplus2fa.log"
ERROR_FILE = "/var/log/chatgptplus2fa.err"

# إعداد التسجيل المتقدم
class BotLogger:
    def __init__(self):
        self.logger = logging.getLogger('ChatGPTPlus2FABot')
        self.logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # معالج لملف السجل
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(formatter)
        
        # معالج لسجل الأخطاء
        error_handler = logging.FileHandler(ERROR_FILE)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        
        # معالج للطرفية
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(stream_handler)
    
    def get_logger(self):
        return self.logger

# تهيئة المسجل
bot_logger = BotLogger()
logger = bot_logger.get_logger()

class TwoFABot:
    def __init__(self):
        self.totp = pyotp.TOTP(TOTP_SECRET)
        self.allowed_users: Set[int] = {ADMIN_ID}
        self.max_copies = 5
        self.current_copies = 0
        self.last_reset = datetime.now()
        self.application: Application = None
        self.shutdown_event = asyncio.Event()
        
        # إعداد معالجات الإشارات
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

    def handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()

    async def initialize(self):
        """تهيئة البوت والتطبيق"""
        try:
            self.application = Application.builder().token(TOKEN).build()
            self.register_handlers()
            await self.setup_job_queue()
        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            raise

    def register_handlers(self):
        """تسجيل معالجات الأوامر والأزرار"""
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler)
        )

    async def setup_job_queue(self):
        """إعداد قائمة المهام الدورية"""
        self.application.job_queue.run_repeating(
            self.send_code,
            interval=300,
            first=10,
            name="send_2fa_code"
        )

    async def cleanup(self):
        """تنظيف الموارد قبل الإغلاق"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

    async def run(self):
        """تشغيل البوت الرئيسي"""
        try:
            await self.initialize()
            logger.info("Bot starting up...")
            
            # الانتظار حتى إشارة الإغلاق
            while not self.shutdown_event.is_set():
                try:
                    await self.application.updater.start_polling()
                    await self.shutdown_event.wait()
                except asyncio.CancelledError:
                    logger.info("Received cancellation, shutting down...")
                    break
                except Exception as e:
                    logger.error(f"Runtime error: {e}", exc_info=True)
                    await asyncio.sleep(5)  # انتظار قبل إعادة المحاولة
            
            logger.info("Shutting down gracefully...")
            await self.cleanup()
            
        except Exception as e:
            logger.critical(f"Fatal error: {e}", exc_info=True)
            raise
        finally:
            logger.info("Bot shutdown complete")

    async def send_code(self, context: ContextTypes.DEFAULT_TYPE):
        """إرسال رمز المصادقة"""
        try:
            now = datetime.now()
            if now.date() != self.last_reset.date():
                self.current_copies = 0
                self.last_reset = now
            
            code = self.totp.now()
            next_time = (now + timedelta(minutes=5)).strftime("%H:%M:%S")
            
            keyboard = [
                [InlineKeyboardButton("📋 نسخ الرمز", callback_data='copy_code')],
                [InlineKeyboardButton("🌐 تغيير اللغة", callback_data='change_lang')]
            ]
            
            if await self.is_admin(ADMIN_ID):
                keyboard.append([InlineKeyboardButton("لوحة التحكم", callback_data='admin_panel')])
            
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=f"رمز المصادقة جاهز\n\nالرمز التالي الساعة {next_time}",
                reply_markup=InlineKeyboardMarkup(keyboard)
                
        except Exception as e:
            logger.error(f"Error in send_code: {e}", exc_info=True)
            raise

    async def is_admin(self, user_id: int) -> bool:
        """التحقق من صلاحية المشرف"""
        try:
            chat_member = await self.application.bot.get_chat_member(GROUP_CHAT_ID, user_id)
            return chat_member.status in ['administrator', 'creator']
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return False

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أحداث الأزرار"""
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data == 'copy_code':
                await self.handle_code_copy(query, context)
            elif query.data == 'admin_panel':
                await self.show_admin_panel(query)
        except Exception as e:
            logger.error(f"Button handler error: {e}", exc_info=True)

    async def handle_code_copy(self, query, context: ContextTypes.DEFAULT_TYPE):
        """معالجة نسخ الرمز"""
        user_id = query.from_user.id
        if user_id not in self.allowed_users and not await self.is_admin(user_id):
            await query.answer("غير مسموح لك بنسخ الرمز", show_alert=True)
            return
        
        if self.current_copies >= self.max_copies:
            await query.answer("تم استنفاذ عدد النسخ اليومي", show_alert=True)
            return
        
        self.current_copies += 1
        code = self.totp.now()
        remaining = self.max_copies - self.current_copies
        
        await query.answer(
            f"{code}\n\nالرمز صالح لمدة 30 ثانية\nالنسخ المتبقية: {remaining}",
            show_alert=True)
        
        if user_id != ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"العضو {query.from_user.full_name} قام بنسخ الرمز. النسخ المتبقية: {remaining}")

    async def show_admin_panel(self, query):
        """عرض لوحة تحكم المسؤول"""
        keyboard = [
            [InlineKeyboardButton("➕ إضافة عضو", callback_data='add_user')],
            [InlineKeyboardButton("➖ إزالة عضو", callback_data='remove_user')],
            [InlineKeyboardButton("➕ زيادة النسخ", callback_data='increase_copies')],
            [InlineKeyboardButton("➖ تقليل النسخ", callback_data='decrease_copies')]
        ]
        await query.edit_message_text(
            text="لوحة تحكم المسؤول",
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر المسؤول"""
        if update.effective_user.id == ADMIN_ID:
            await self.show_admin_panel(update.message)

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الرسائل العامة"""
        pass

async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    bot = TwoFABot()
    try:
        await bot.run()
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    # إنشاء مجلد السجلات إذا لم يكن موجوداً
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    # تشغيل البوت
    asyncio.run(main())

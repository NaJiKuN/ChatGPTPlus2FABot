#!/usr/bin/python3
import os
import sys
import asyncio
import pyotp
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext,
)
import logging

# تكوين الأساسيات
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
ADMIN_ID = 764559466

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/chatgptplus2fa.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.totp = pyotp.TOTP(TOTP_SECRET)
        self.allowed_users = {ADMIN_ID}
        self.max_copies = 5
        self.current_copies = 0
        self.last_reset = datetime.now()
        self.application = None

    async def start(self):
        try:
            self.application = Application.builder().token(TOKEN).build()
            
            # إضافة المعالجات
            self.application.add_handler(CommandHandler("admin", self.admin_command))
            self.application.add_handler(CallbackQueryHandler(self.button_handler))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
            
            # بدء المهمة الدورية
            self.application.job_queue.run_repeating(self.send_code, interval=300, first=10)
            
            logger.info("Starting bot polling...")
            await self.application.run_polling()
        except Exception as e:
            logger.error(f"Failed to start bot: {e}", exc_info=True)
            raise

    async def send_code(self, context: CallbackContext):
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

    async def is_admin(self, user_id):
        try:
            chat_member = await self.application.bot.get_chat_member(GROUP_CHAT_ID, user_id)
            return chat_member.status in ['administrator', 'creator']
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return False

    async def button_handler(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data == 'copy_code':
                await self.handle_code_copy(query, context)
            elif query.data == 'admin_panel':
                await self.show_admin_panel(query)
        except Exception as e:
            logger.error(f"Button handler error: {e}", exc_info=True)

    async def handle_code_copy(self, query, context):
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
        keyboard = [
            [InlineKeyboardButton("➕ إضافة عضو", callback_data='add_user')],
            [InlineKeyboardButton("➖ إزالة عضو", callback_data='remove_user')],
            [InlineKeyboardButton("➕ زيادة النسخ", callback_data='increase_copies')],
            [InlineKeyboardButton("➖ تقليل النسخ", callback_data='decrease_copies')]
        ]
        await query.edit_message_text(
            text="لوحة تحكم المسؤول",
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_command(self, update: Update, context: CallbackContext):
        if update.effective_user.id == ADMIN_ID:
            await self.show_admin_panel(update.message)

    async def message_handler(self, update: Update, context: CallbackContext):
        pass  # يمكن إضافة معالجة الرسائل هنا

async def main():
    bot = BotManager()
    await bot.start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)

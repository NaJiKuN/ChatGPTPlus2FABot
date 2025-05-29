# -*- coding: utf-8 -*-
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from utils import is_admin, load_groups, load_users, load_config, save_config, save_groups, save_users, block_user, set_user_attempts

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for admin operations
(SELECTING_ACTION, SELECTING_GROUP_ACTION, SELECTING_GROUP_ID, ENTERING_SECRET, 
 CONFIRM_DELETE_GROUP, SELECTING_INTERVAL_GROUP, SELECTING_INTERVAL, 
 SELECTING_STYLE_GROUP, SELECTING_STYLE, SELECTING_TIMEZONE, 
 SELECTING_ATTEMPTS_GROUP, SELECTING_USER_FOR_ATTEMPTS, SELECTING_USER_ACTION, 
 ENTERING_ATTEMPTS_COUNT, CONFIRM_BLOCK_USER, SELECTING_ADMIN_ACTION, 
 ENTERING_ADMIN_ID, CONFIRM_REMOVE_ADMIN) = range(18)

# --- Main Admin Command ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the admin conversation flow."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمسؤولين فقط.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("⚙️ إدارة المجموعات/السر", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("⏰ إدارة فترة التكرار", callback_data="admin_manage_interval")],
        [InlineKeyboardButton("🎨 إدارة شكل/توقيت الرسالة", callback_data="admin_manage_style")],
        [InlineKeyboardButton("🔢 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("لوحة تحكم المسؤول - ChatGPTPlus2FABot:", reply_markup=reply_markup)
    return SELECTING_ACTION

async def cancel_admin_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current admin conversation."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="تم إلغاء العملية.")
    # Clear conversation state if needed
    context.user_data.clear()
    return ConversationHandler.END

# Placeholder for other admin handlers to be added in callback_query.py
# This file primarily defines the entry point and states.


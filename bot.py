#!/usr/bin/env python3 اصدار 1
import os
import logging
import requests
from datetime import datetime, timedelta
import pytz
import pyotp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    MessageHandler,
    Filters
)

# Configurations
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_ID = -1002329495586
ADMIN_ID = 764559466
BOT_ID = 792534650
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# Global variables
DAILY_COPY_LIMIT = 5
current_copies = 0
allowed_users = {ADMIN_ID}
users_copy_count = {}
user_language = {}
last_code_sent_time = None

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Timezone setup
gaza_tz = pytz.timezone('Asia/Gaza')

# Language texts
texts = {
    'en': {
        'code_message': '🔐 *2FA Verification Code*\n\nNext code at: {next_time}',
        'copy_button': '📋 Copy Code',
        'language_button': '🌐 Change Language',
        'copy_success': '✅ Code copied successfully! Valid for 30 seconds.\nRemaining copies today: {remaining}',
        'copy_limit_reached': '❌ Daily copy limit reached. Contact admin.',
        'not_allowed': '❌ You are not allowed to copy codes.',
        'admin_menu': '🛠 *Admin Menu*',
        'add_user': '➕ Add User',
        'remove_user': '➖ Remove User',
        'increase_limit': '📈 Increase Daily Limit',
        'decrease_limit': '📉 Decrease Daily Limit',
        'user_added': '✅ User added successfully.',
        'user_removed': '✅ User removed successfully.',
        'limit_increased': '✅ Daily limit increased to {limit}.',
        'limit_decreased': '✅ Daily limit decreased to {limit}.',
        'invalid_user_id': '❌ Invalid user ID.',
        'user_info': '👤 *User Info*\n\n🔹 Name: {user_name}\n🔹 ID: `{user_id}`\n🔹 IP: `{ip}`\n🔹 Time: `{time}`\n🔹 Code: `{code}`'
    },
    'ar': {
        'code_message': '🔐 *رمز المصادقة الثنائية*\n\nالرمز التالي في: {next_time}',
        'copy_button': '📋 نسخ الرمز',
        'language_button': '🌐 تغيير اللغة',
        'copy_success': '✅ تم نسخ الرمز بنجاح! صالح لمدة 30 ثانية.\nعدد النسخ المتبقية اليوم: {remaining}',
        'copy_limit_reached': '❌ تم الوصول إلى الحد اليومي للنسخ. تواصل مع المسؤول.',
        'not_allowed': '❌ غير مسموح لك بنسخ الرموز.',
        'admin_menu': '🛠 *قائمة المسؤول*',
        'add_user': '➕ إضافة عضو',
        'remove_user': '➖ إزالة عضو',
        'increase_limit': '📈 زيادة الحد اليومي',
        'decrease_limit': '📉 تقليل الحد اليومي',
        'user_added': '✅ تمت إضافة العضو بنجاح.',
        'user_removed': '✅ تمت إزالة العضو بنجاح.',
        'limit_increased': '✅ تم زيادة الحد اليومي إلى {limit}.',
        'limit_decreased': '✅ تم تقليل الحد اليومي إلى {limit}.',
        'invalid_user_id': '❌ معرّف العضو غير صالح.',
        'user_info': '👤 *معلومات العضو*\n\n🔹 الاسم: {user_name}\n🔹 الرقم: `{user_id}`\n🔹 الأيبي: `{ip}`\n🔹 الوقت: `{time}`\n🔹 الرمز: `{code}`'
    }
}

def get_user_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json')
        if response.status_code == 200:
            return response.json().get('ip', 'Unknown')
    except:
        pass
    return 'Unknown'

def get_user_language(user_id):
    return user_language.get(user_id, 'en')

def generate_2fa_code():
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def send_2fa_code(context: CallbackContext):
    global last_code_sent_time
    
    code = generate_2fa_code()
    next_time = (datetime.now(gaza_tz) + timedelta(minutes=5)).strftime('%I:%M:%S %p')
    last_code_sent_time = datetime.now(gaza_tz)
    
    # Get language for the group
    lang = 'en'  # Default language for group messages
    
    keyboard = [
        [InlineKeyboardButton(texts[lang]['copy_button'], callback_data=f'copy_{code}')],
        [InlineKeyboardButton(texts[lang]['language_button'], callback_data='change_language')]
    ]

    context.bot.send_message(
        chat_id=GROUP_ID,
        text=texts[lang]['code_message'].format(next_time=next_time),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(f"Hello! I'm the 2FA bot. Your ID: {user_id}")

def handle_copy(update: Update, context: CallbackContext):
    global current_copies, users_copy_count
    
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    lang = get_user_language(user_id)
    
    if user_id not in allowed_users:
        query.answer(text=texts[lang]['not_allowed'], show_alert=True)
        return
    
    if current_copies >= DAILY_COPY_LIMIT:
        query.answer(text=texts[lang]['copy_limit_reached'], show_alert=True)
        return
    
    code = query.data.split('_')[1]
    current_copies += 1
    users_copy_count[user_id] = users_copy_count.get(user_id, 0) + 1
    
    remaining = DAILY_COPY_LIMIT - current_copies
    query.answer(text=texts[lang]['copy_success'].format(remaining=remaining), show_alert=True)
    
    # Get user IP address
    ip_address = get_user_ip()
    
    # Format time
    now = datetime.now(gaza_tz).strftime('%Y-%m-%d %H:%M:%S')
    
    # Send the code to user
    context.bot.send_message(
        chat_id=user_id,
        text=f"Your 2FA code: `{code}`\n\nCopy this code and use it within 30 seconds.",
        parse_mode='Markdown'
    )
    
    # Send user info to admin
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=texts[lang]['user_info'].format(
            user_name=user_name,
            user_id=user_id,
            ip=ip_address,
            time=now,
            code=code
        ),
        parse_mode='Markdown'
    )

# ... [بقية الدوال تبقى كما هي بدون تغيير] ...

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", admin_command))
    dp.add_handler(CallbackQueryHandler(handle_copy, pattern='^copy_'))
    dp.add_handler(CallbackQueryHandler(change_language, pattern='^change_language$'))
    dp.add_handler(CallbackQueryHandler(admin_actions, pattern='^admin_'))
    dp.add_handler(MessageHandler(Filters.text & Filters.reply, handle_admin_reply))
    dp.add_error_handler(error_handler)
    
    jq = updater.job_queue
    jq.run_repeating(send_2fa_code, interval=300, first=0)  # Send code every 5 minutes
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

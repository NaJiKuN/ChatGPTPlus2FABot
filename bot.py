#!/usr/bin/env python3 v1.7
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
allowed_users = {ADMIN_ID: {'limit': 5, 'used': 0, 'name': 'Admin'}}
user_language = {}
last_code_sent_time = None
pending_actions = {}

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
        'copy_success': '✅ Code sent to your private chat! Valid for 30 seconds.',
        'copy_limit_reached': '❌ Daily copy limit reached ({used}/{limit}). Try again tomorrow.',
        'not_allowed': '❌ You are not allowed to copy codes.',
        'admin_menu': '🛠 *Admin Menu*',
        'add_user': '➕ Add User',
        'remove_user': '➖ Remove User',
        'set_limit': '📝 Set User Limit',
        'list_users': '👥 List All Users',
        'user_added': '✅ User {user_id} added successfully with default 5 copies/day.',
        'user_removed': '✅ User {user_id} removed successfully.',
        'user_not_found': '❌ User {user_id} not found.',
        'limit_updated': '✅ Daily limit updated to {limit} for user {user_name} (ID: {user_id}).',
        'invalid_input': '❌ Invalid input. Please send a valid number.',
        'user_info': '👤 *User Info*\n\n🔹 Name: {user_name}\n🔹 ID: `{user_id}`\n🔹 IP: `{ip}`\n🔹 Time: `{time}`\n🔹 Code: `{code}`',
        'current_limit': '🔢 *Set User Limit*\n\nUser: {user_name} (ID: {user_id})\nCurrent limit: {limit}\n\nSelect action:',
        'increase': '➕ Increase',
        'decrease': '➖ Decrease',
        'send_user_id': 'Please send the user ID:',
        'code_private_msg': '🔐 *2FA Code*\n\nYour verification code: `{code}`\n\n⚠️ Valid for 30 seconds only!',
        'limit_change_success': '✅ Limit changed successfully! New limit: {limit}'
    },
    'ar': {
        'code_message': '🔐 *رمز المصادقة الثنائية*\n\nالرمز التالي في: {next_time}',
        'copy_button': '📋 نسخ الرمز',
        'language_button': '🌐 تغيير اللغة',
        'copy_success': '✅ تم إرسال الرمز إلى محادثتك الخاصة! صالح لمدة 30 ثانية.',
        'copy_limit_reached': '❌ تم الوصول إلى الحد اليومي للنسخ ({used}/{limit}). حاول مرة أخرى غداً.',
        'not_allowed': '❌ غير مسموح لك بنسخ الرموز.',
        'admin_menu': '🛠 *قائمة المسؤول*',
        'add_user': '➕ إضافة عضو',
        'remove_user': '➖ إزالة عضو',
        'set_limit': '📝 تعيين حد للمستخدم',
        'list_users': '👥 عرض جميع الأعضاء',
        'user_added': '✅ تمت إضافة العضو {user_id} بنجاح مع حد افتراضي 5 نسخ/يوم.',
        'user_removed': '✅ تمت إزالة العضو {user_id} بنجاح.',
        'user_not_found': '❌ العضو {user_id} غير موجود.',
        'limit_updated': '✅ تم تحديث الحد اليومي إلى {limit} للعضو {user_name} (ID: {user_id}).',
        'invalid_input': '❌ إدخال غير صالح. الرجاء إرسال رقم صحيح.',
        'user_info': '👤 *معلومات العضو*\n\n🔹 الاسم: {user_name}\n🔹 الرقم: `{user_id}`\n🔹 الأيبي: `{ip}`\n🔹 الوقت: `{time}`\n🔹 الرمز: `{code}`',
        'current_limit': '🔢 *تعيين حد المستخدم*\n\nالعضو: {user_name} (ID: {user_id})\nالحد الحالي: {limit}\n\nاختر الإجراء:',
        'increase': '➕ زيادة',
        'decrease': '➖ نقصان',
        'send_user_id': 'الرجاء إرسال معرف المستخدم:',
        'code_private_msg': '🔐 *رمز المصادقة*\n\nرمز التحقق الخاص بك: `{code}`\n\n⚠️ صالح لمدة 30 ثانية فقط!',
        'limit_change_success': '✅ تم تغيير الحد بنجاح! الحد الجديد: {limit}'
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
    
    lang = 'en'
    
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

def handle_copy(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    lang = get_user_language(user_id)
    code = query.data.split('_')[1]
    
    # Auto-add user with default 5 copies if not exists
    if user_id not in allowed_users:
        allowed_users[user_id] = {
            'limit': 5,
            'used': 0,
            'name': user_name
        }
    
    user_data = allowed_users[user_id]
    
    if user_data['used'] >= user_data['limit']:
        query.answer(
            text=texts[lang]['copy_limit_reached'].format(
                used=user_data['used'],
                limit=user_data['limit']
            ),
            show_alert=True
        )
        return
    
    # Generate fresh code in real-time
    real_time_code = generate_2fa_code()
    
    # Send real-time code to private chat
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['code_private_msg'].format(code=real_time_code),
            parse_mode='Markdown'
        )
        user_data['used'] += 1
        query.answer(text=texts[lang]['copy_success'], show_alert=True)
    except Exception as e:
        query.answer(text="❌ Failed to send code. Please start a chat with the bot first.", show_alert=True)
        return
    
    # Log to admin
    ip_address = get_user_ip()
    now = datetime.now(gaza_tz).strftime('%Y-%m-%d %H:%M:%S')
    
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=texts[lang]['user_info'].format(
            user_name=user_name,
            user_id=user_id,
            ip=ip_address,
            time=now,
            code=real_time_code
        ),
        parse_mode='Markdown'
    )

# ... [بقية الدوال كما هي بدون تغيير] ...

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", admin_command))
    dp.add_handler(CallbackQueryHandler(handle_copy, pattern='^copy_'))
    dp.add_handler(CallbackQueryHandler(change_language, pattern='^change_language$'))
    dp.add_handler(CallbackQueryHandler(admin_actions, pattern='^admin_'))
    dp.add_handler(CallbackQueryHandler(handle_limit_actions, pattern='^limit_'))
    dp.add_handler(MessageHandler(Filters.text & Filters.reply, handle_admin_reply))
    dp.add_error_handler(error_handler)
    
    jq = updater.job_queue
    jq.run_repeating(send_2fa_code, interval=300, first=0)
    jq.run_daily(reset_daily_limits, time=datetime.strptime("00:00", "%H:%M").time())
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

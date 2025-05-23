#!/usr/bin/env python3 v1.2
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
allowed_users = {ADMIN_ID: {'limit': 5, 'used': 0, 'name': 'Admin'}}  # {user_id: {limit: int, used: int, name: str}}
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
        'copy_success': '✅ Code copied successfully! Valid for 30 seconds.\nRemaining copies today: {remaining}/{limit}',
        'copy_limit_reached': '❌ Daily copy limit reached ({used}/{limit}). Contact admin.',
        'not_allowed': '❌ You are not allowed to copy codes.',
        'admin_menu': '🛠 *Admin Menu*',
        'add_user': '➕ Add User',
        'remove_user': '➖ Remove User',
        'set_limit': '📝 Set User Limit',
        'list_users': '👥 List All Users',
        'user_added': '✅ User added successfully with limit {limit} copies/day.',
        'user_removed': '✅ User removed successfully.',
        'limit_set': '✅ Daily limit set to {limit} for user {user_id}.',
        'invalid_user_id': '❌ Invalid user ID.',
        'user_info': '👤 *User Info*\n\n🔹 Name: {user_name}\n🔹 ID: `{user_id}`\n🔹 IP: `{ip}`\n🔹 Time: `{time}`\n🔹 Code: `{code}`',
        'user_list': '👥 *User List*\n\n{users_list}',
        'user_entry': '🔹 {user_name} (ID: {user_id}) - {used}/{limit} copies today',
        'send_user_id': 'Please send the user ID:',
        'send_new_limit': 'Please send the new daily limit for this user:'
    },
    'ar': {
        'code_message': '🔐 *رمز المصادقة الثنائية*\n\nالرمز التالي في: {next_time}',
        'copy_button': '📋 نسخ الرمز',
        'language_button': '🌐 تغيير اللغة',
        'copy_success': '✅ تم نسخ الرمز بنجاح! صالح لمدة 30 ثانية.\nعدد النسخ المتبقية اليوم: {remaining}/{limit}',
        'copy_limit_reached': '❌ تم الوصول إلى الحد اليومي للنسخ ({used}/{limit}). تواصل مع المسؤول.',
        'not_allowed': '❌ غير مسموح لك بنسخ الرموز.',
        'admin_menu': '🛠 *قائمة المسؤول*',
        'add_user': '➕ إضافة عضو',
        'remove_user': '➖ إزالة عضو',
        'set_limit': '📝 تعيين حد للمستخدم',
        'list_users': '👥 عرض جميع الأعضاء',
        'user_added': '✅ تمت إضافة العضو بنجاح مع حد {limit} نسخة/يوم.',
        'user_removed': '✅ تمت إزالة العضو بنجاح.',
        'limit_set': '✅ تم تعيين الحد اليومي إلى {limit} للعضو {user_id}.',
        'invalid_user_id': '❌ معرّف العضو غير صالح.',
        'user_info': '👤 *معلومات العضو*\n\n🔹 الاسم: {user_name}\n🔹 الرقم: `{user_id}`\n🔹 الأيبي: `{ip}`\n🔹 الوقت: `{time}`\n🔹 الرمز: `{code}`',
        'user_list': '👥 *قائمة الأعضاء*\n\n{users_list}',
        'user_entry': '🔹 {user_name} (ID: {user_id}) - {used}/{limit} نسخ اليوم',
        'send_user_id': 'الرجاء إرسال معرف المستخدم:',
        'send_new_limit': 'الرجاء إرسال الحد اليومي الجديد لهذا المستخدم:'
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
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    lang = get_user_language(user_id)
    
    if user_id not in allowed_users:
        query.answer(text=texts[lang]['not_allowed'], show_alert=True)
        return
    
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
    
    code = query.data.split('_')[1]
    user_data['used'] += 1
    
    remaining = user_data['limit'] - user_data['used']
    query.answer(
        text=texts[lang]['copy_success'].format(
            remaining=remaining,
            limit=user_data['limit']
        ),
        show_alert=True
    )
    
    ip_address = get_user_ip()
    now = datetime.now(gaza_tz).strftime('%Y-%m-%d %H:%M:%S')
    
    # Send code directly to user (simulates copy to clipboard)
    context.bot.send_message(
        chat_id=user_id,
        text=f"Your 2FA code: `{code}`\n\nThis code is valid for 30 seconds.",
        parse_mode='Markdown'
    )
    
    # Send notification to admin
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

def change_language(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    current_lang = get_user_language(user_id)
    new_lang = 'ar' if current_lang == 'en' else 'en'
    user_language[user_id] = new_lang
    
    code_message = query.message.text.split('\n')[0]
    next_time = (datetime.now(gaza_tz) + timedelta(minutes=5)).strftime('%I:%M:%S %p')
    
    keyboard = [
        [InlineKeyboardButton(texts[new_lang]['copy_button'], callback_data=query.message.reply_markup.inline_keyboard[0][0].callback_data)],
        [InlineKeyboardButton(texts[new_lang]['language_button'], callback_data='change_language')]
    ]
    
    query.edit_message_text(
        text=texts[new_lang]['code_message'].format(next_time=next_time),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    query.answer(text=f"Language changed to {new_lang.upper()}")

def admin_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    lang = get_user_language(user_id)
    keyboard = [
        [InlineKeyboardButton(texts[lang]['add_user'], callback_data='admin_add_user')],
        [InlineKeyboardButton(texts[lang]['remove_user'], callback_data='admin_remove_user')],
        [InlineKeyboardButton(texts[lang]['set_limit'], callback_data='admin_set_limit')],
        [InlineKeyboardButton(texts[lang]['list_users'], callback_data='admin_list_users')]
    ]
    
    update.message.reply_text(
        text=texts[lang]['admin_menu'],
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def admin_actions(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        return

    lang = get_user_language(user_id)
    action = query.data

    if action == 'admin_add_user':
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['add_user'] + "\n" + texts[lang]['send_user_id']
        )
    elif action == 'admin_remove_user':
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['remove_user'] + "\n" + texts[lang]['send_user_id']
        )
    elif action == 'admin_set_limit':
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['set_limit'] + "\n" + texts[lang]['send_user_id']
        )
    elif action == 'admin_list_users':
        list_users(update, context)

def list_users(update: Update, context: CallbackContext):
    lang = get_user_language(ADMIN_ID)
    users_list = []
    
    for user_id, user_data in allowed_users.items():
        users_list.append(texts[lang]['user_entry'].format(
            user_name=user_data['name'],
            user_id=user_id,
            used=user_data['used'],
            limit=user_data['limit']
        ))
    
    if not users_list:
        users_list.append("No users available")
    
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=texts[lang]['user_list'].format(
            users_list="\n".join(users_list)
        ),
        parse_mode='Markdown'
    )

def handle_admin_reply(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    lang = get_user_language(user_id)
    reply_to = update.message.reply_to_message
    
    if reply_to and ("Add User" in reply_to.text or "إضافة عضو" in reply_to.text):
        try:
            new_user_id = int(update.message.text)
            if new_user_id not in allowed_users:
                allowed_users[new_user_id] = {
                    'limit': 5,
                    'used': 0,
                    'name': f"User {new_user_id}"
                }
                update.message.reply_text(
                    texts[lang]['user_added'].format(limit=5)
                )
            else:
                update.message.reply_text("User already exists")
        except ValueError:
            update.message.reply_text(texts[lang]['invalid_user_id'])
    
    elif reply_to and ("Remove User" in reply_to.text or "إزالة عضو" in reply_to.text):
        try:
            remove_user_id = int(update.message.text)
            if remove_user_id in allowed_users:
                del allowed_users[remove_user_id]
                update.message.reply_text(texts[lang]['user_removed'])
            else:
                update.message.reply_text("User not in allowed list")
        except ValueError:
            update.message.reply_text(texts[lang]['invalid_user_id'])
    
    elif reply_to and ("Set User Limit" in reply_to.text or "تعيين حد للمستخدم" in reply_to.text):
        try:
            parts = update.message.text.split()
            if len(parts) == 2:
                user_id = int(parts[0])
                new_limit = int(parts[1])
                
                if user_id in allowed_users:
                    allowed_users[user_id]['limit'] = new_limit
                    update.message.reply_text(
                        texts[lang]['limit_set'].format(
                            limit=new_limit,
                            user_id=user_id
                        )
                    )
                else:
                    update.message.reply_text("User not found")
            else:
                update.message.reply_text("Please send user ID and new limit separated by space")
        except ValueError:
            update.message.reply_text("Invalid input. Please send user ID and new limit as numbers")

def reset_daily_limits(context: CallbackContext):
    for user_data in allowed_users.values():
        user_data['used'] = 0
    logger.info("Daily copy limits have been reset")

def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

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
    jq.run_daily(reset_daily_limits, time=datetime.strptime("00:00", "%H:%M").time())  # Reset limits at midnight
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

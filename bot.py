#!/usr/bin/env python3 v2.0
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
        [InlineKeyboardButton(texts[lang]['copy_button'], callback_data='generate_new_code')],
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
    
    # Generate new code in real-time
    code = generate_2fa_code()
    
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
    
    # Send real-time code to private chat
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['code_private_msg'].format(code=code),
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
        [InlineKeyboardButton(texts[new_lang]['copy_button'], callback_data='generate_new_code')],
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
        pending_actions[user_id] = {'action': 'add_user'}
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['send_user_id']
        )
    elif action == 'admin_remove_user':
        pending_actions[user_id] = {'action': 'remove_user'}
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['send_user_id']
        )
    elif action == 'admin_set_limit':
        pending_actions[user_id] = {'action': 'set_limit'}
        context.bot.send_message(
            chat_id=user_id,
            text=texts[lang]['send_user_id']
        )
    elif action == 'admin_list_users':
        list_users(update, context)

def list_users(update: Update, context: CallbackContext):
    user_id = update.effective_user.id or update.callback_query.from_user.id
    if user_id != ADMIN_ID:
        return
    
    lang = get_user_language(user_id)
    users_list = []
    
    for uid, user_data in allowed_users.items():
        users_list.append(f"🔹 {user_data['name']} (ID: {uid}) - {user_data['used']}/{user_data['limit']} copies today")
    
    if not users_list:
        users_list.append("No users available")
    
    if update.callback_query:
        update.callback_query.answer()
    
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text="👥 *User List*\n\n" + "\n".join(users_list),
        parse_mode='Markdown'
    )

def handle_admin_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or user_id not in pending_actions:
        return
    
    lang = get_user_language(user_id)
    text = update.message.text
    action = pending_actions[user_id]['action']
    
    try:
        target_user = int(text)
        
        if action == 'add_user':
            if target_user not in allowed_users:
                allowed_users[target_user] = {
                    'limit': 5,
                    'used': 0,
                    'name': f"User {target_user}"
                }
                update.message.reply_text(
                    texts[lang]['user_added'].format(user_id=target_user)
                )
            else:
                update.message.reply_text(f"User {target_user} already exists")
        
        elif action == 'remove_user':
            if target_user in allowed_users:
                del allowed_users[target_user]
                update.message.reply_text(
                    texts[lang]['user_removed'].format(user_id=target_user)
                )
            else:
                update.message.reply_text(
                    texts[lang]['user_not_found'].format(user_id=target_user)
                )
        
        elif action == 'set_limit':
            if target_user in allowed_users:
                user_data = allowed_users[target_user]
                keyboard = [
                    [
                        InlineKeyboardButton(texts[lang]['increase'], callback_data=f'limit_inc_{target_user}'),
                        InlineKeyboardButton(texts[lang]['decrease'], callback_data=f'limit_dec_{target_user}')
                    ]
                ]
                
                update.message.reply_text(
                    texts[lang]['current_limit'].format(
                        user_name=user_data['name'],
                        user_id=target_user,
                        limit=user_data['limit']
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            else:
                update.message.reply_text(
                    texts[lang]['user_not_found'].format(user_id=target_user)
                )
    
    except ValueError:
        update.message.reply_text(texts[lang]['invalid_input'])
    
    del pending_actions[user_id]

def handle_limit_actions(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        return
    
    lang = get_user_language(user_id)
    data = query.data.split('_')
    action = data[1]
    target_user = int(data[2])
    
    if target_user not in allowed_users:
        query.answer(text=texts[lang]['user_not_found'].format(user_id=target_user), show_alert=True)
        return
    
    user_data = allowed_users[target_user]
    
    if action == 'inc':
        user_data['limit'] += 1
    elif action == 'dec':
        if user_data['limit'] > 1:
            user_data['limit'] -= 1
        else:
            query.answer(text="Limit cannot be less than 1", show_alert=True)
            return
    
    query.edit_message_text(
        text=texts[lang]['limit_updated'].format(
            limit=user_data['limit'],
            user_name=user_data['name'],
            user_id=target_user
        ),
        parse_mode='Markdown'
    )
    query.answer(text=texts[lang]['limit_change_success'].format(limit=user_data['limit']), show_alert=True)

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
    dp.add_handler(CallbackQueryHandler(handle_copy, pattern='^generate_new_code$'))
    dp.add_handler(CallbackQueryHandler(change_language, pattern='^change_language$'))
    dp.add_handler(CallbackQueryHandler(admin_actions, pattern='^admin_'))
    dp.add_handler(CallbackQueryHandler(handle_limit_actions, pattern='^limit_'))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_message))
    dp.add_error_handler(error_handler)
    
    jq = updater.job_queue
    jq.run_repeating(send_2fa_code, interval=300, first=0)
    jq.run_daily(reset_daily_limits, time=datetime.strptime("00:00", "%H:%M").time())
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

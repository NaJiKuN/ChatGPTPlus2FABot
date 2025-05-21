import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
import pyotp
from datetime import datetime, timedelta
import pytz
import json
import os
import requests
from user_agents import parse

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
ADMIN_CHAT_ID = 792534650  # Chat ID الخاص بك كلوحة تحكم
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
LOG_FILE = "code_requests.log"
CONFIG_FILE = "bot_config.json"
USER_LIMITS_FILE = "user_limits.json"

# تهيئة المنطقة الزمنية لفلسطين
PALESTINE_TZ = pytz.timezone('Asia/Gaza')

# تهيئة ملفات البيانات
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({
            "max_requests_per_user": 5,
            "code_visibility": True,
            "allowed_users": []
        }, f)

if not os.path.exists(USER_LIMITS_FILE):
    with open(USER_LIMITS_FILE, 'w') as f:
        json.dump({}, f)

# دعم اللغات
MESSAGES = {
    'en': {
        # ... (نفس الرسائل السابقة) ...
        'admin_panel': "👑 *Admin Panel*\n\n- Max requests per user: {max_requests}\n- Code visibility: {visibility}\n- Allowed users: {user_count}",
        'visibility_on': "ON ✅",
        'visibility_off': "OFF ❌",
        'change_max_requests': "✏️ Change max requests",
        'toggle_visibility': "👁️ Toggle code visibility",
        'manage_users': "👥 Manage allowed users",
        'enter_new_max': "Please enter the new maximum requests per user (1-20):",
        'invalid_max': "Invalid input! Please enter a number between 1 and 20.",
        'max_updated': "✅ Max requests updated to {max_requests} per user.",
        'visibility_updated': "✅ Code visibility updated to {status}.",
        'add_user': "➕ Add user",
        'remove_user': "➖ Remove user",
        'enter_user_id': "Please enter the user ID to add/remove:",
        'user_added': "✅ User {user_id} added to allowed list.",
        'user_removed': "✅ User {user_id} removed from allowed list.",
        'user_not_found': "⚠️ User not found in the allowed list."
    },
    'ar': {
        # ... (نفس الرسائل السابقة) ...
        'admin_panel': "👑 *لوحة التحكم*\n\n- الحد الأقصى للطلبات لكل مستخدم: {max_requests}\n- إظهار الأكواد: {visibility}\n- المستخدمون المسموح لهم: {user_count}",
        'visibility_on': "مفعل ✅",
        'visibility_off': "معطل ❌",
        'change_max_requests': "✏️ تغيير الحد الأقصى للطلبات",
        'toggle_visibility': "👁️ تبديل إظهار الأكواد",
        'manage_users': "👥 إدارة المستخدمين المسموح لهم",
        'enter_new_max': "الرجاء إدخال الحد الأقصى الجديد للطلبات لكل مستخدم (1-20):",
        'invalid_max': "إدخال غير صحيح! الرجاء إدخال رقم بين 1 و 20.",
        'max_updated': "✅ تم تحديث الحد الأقصى للطلبات إلى {max_requests} لكل مستخدم.",
        'visibility_updated': "✅ تم تحديث إظهار الأكواد إلى {status}.",
        'add_user': "➕ إضافة مستخدم",
        'remove_user': "➖ إزالة مستخدم",
        'enter_user_id': "الرجاء إدخال معرف المستخدم للإضافة/الإزالة:",
        'user_added': "✅ تمت إضافة المستخدم {user_id} إلى القائمة المسموح بها.",
        'user_removed': "✅ تمت إزالة المستخدم {user_id} من القائمة المسموح بها.",
        'user_not_found': "⚠️ المستخدم غير موجود في القائمة المسموح بها."
    }
}

# ... (الوظائف المساعدة السابقة مثل get_client_ip, get_user_device, etc) ...

def load_config():
    """تحميل إعدادات البوت"""
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    """حفظ إعدادات البوت"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def is_user_allowed(user_id):
    """التحقق مما إذا كان المستخدم مسموح له برؤية الأكواد"""
    config = load_config()
    return config['code_visibility'] or user_id in config['allowed_users'] or user_id == ADMIN_CHAT_ID

def show_admin_panel(update: Update, context: CallbackContext):
    """عرض لوحة التحكم الإدارية"""
    user = update.effective_user
    if user.id != ADMIN_CHAT_ID:
        return
    
    config = load_config()
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    
    visibility = MESSAGES[lang]['visibility_on'] if config['code_visibility'] else MESSAGES[lang]['visibility_off']
    
    keyboard = [
        [InlineKeyboardButton(MESSAGES[lang]['change_max_requests'], callback_data='change_max')],
        [InlineKeyboardButton(MESSAGES[lang]['toggle_visibility'], callback_data='toggle_visibility')],
        [InlineKeyboardButton(MESSAGES[lang]['manage_users'], callback_data='manage_users')]
    ]
    
    update.message.reply_text(
        MESSAGES[lang]['admin_panel'].format(
            max_requests=config['max_requests_per_user'],
            visibility=visibility,
            user_count=len(config['allowed_users'])
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_admin_callback(update: Update, context: CallbackContext):
    """معالجة أحداث لوحة التحكم"""
    query = update.callback_query
    query.answer()
    user = query.from_user
    
    if user.id != ADMIN_CHAT_ID:
        return
    
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    config = load_config()
    
    if query.data == 'change_max':
        query.edit_message_text(MESSAGES[lang]['enter_new_max'])
        return 'WAITING_FOR_MAX'
    
    elif query.data == 'toggle_visibility':
        config['code_visibility'] = not config['code_visibility']
        save_config(config)
        
        status = MESSAGES[lang]['visibility_on'] if config['code_visibility'] else MESSAGES[lang]['visibility_off']
        query.edit_message_text(
            MESSAGES[lang]['visibility_updated'].format(status=status)
        )
        show_admin_panel(update, context)
    
    elif query.data == 'manage_users':
        keyboard = [
            [InlineKeyboardButton(MESSAGES[lang]['add_user'], callback_data='add_user')],
            [InlineKeyboardButton(MESSAGES[lang]['remove_user'], callback_data='remove_user')],
            [InlineKeyboardButton("🔙 Back", callback_data='back_to_panel')]
        ]
        query.edit_message_text(
            "👥 User Management",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == 'add_user':
        query.edit_message_text(MESSAGES[lang]['enter_user_id'])
        return 'WAITING_FOR_USER_ADD'
    
    elif query.data == 'remove_user':
        query.edit_message_text(MESSAGES[lang]['enter_user_id'])
        return 'WAITING_FOR_USER_REMOVE'
    
    elif query.data == 'back_to_panel':
        show_admin_panel(update, context)

def handle_admin_input(update: Update, context: CallbackContext):
    """معالجة إدخالات لوحة التحكم"""
    user = update.effective_user
    if user.id != ADMIN_CHAT_ID:
        return
    
    text = update.message.text
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    config = load_config()
    
    if context.user_data.get('admin_state') == 'WAITING_FOR_MAX':
        try:
            new_max = int(text)
            if 1 <= new_max <= 20:
                config['max_requests_per_user'] = new_max
                save_config(config)
                update.message.reply_text(
                    MESSAGES[lang]['max_updated'].format(max_requests=new_max)
                show_admin_panel(update, context)
                context.user_data['admin_state'] = None
            else:
                update.message.reply_text(MESSAGES[lang]['invalid_max'])
        except ValueError:
            update.message.reply_text(MESSAGES[lang]['invalid_max'])
    
    elif context.user_data.get('admin_state') == 'WAITING_FOR_USER_ADD':
        try:
            user_id = int(text)
            if user_id not in config['allowed_users']:
                config['allowed_users'].append(user_id)
                save_config(config)
                update.message.reply_text(
                    MESSAGES[lang]['user_added'].format(user_id=user_id))
            else:
                update.message.reply_text(MESSAGES[lang]['user_not_found'])
            show_admin_panel(update, context)
            context.user_data['admin_state'] = None
        except ValueError:
            update.message.reply_text("Invalid user ID!")
    
    elif context.user_data.get('admin_state') == 'WAITING_FOR_USER_REMOVE':
        try:
            user_id = int(text)
            if user_id in config['allowed_users']:
                config['allowed_users'].remove(user_id)
                save_config(config)
                update.message.reply_text(
                    MESSAGES[lang]['user_removed'].format(user_id=user_id))
            else:
                update.message.reply_text(MESSAGES[lang]['user_not_found'])
            show_admin_panel(update, context)
            context.user_data['admin_state'] = None
        except ValueError:
            update.message.reply_text("Invalid user ID!")

# ... (بقية الوظائف السابقة مثل send_2fa_code, start, etc) ...

def send_2fa_code(context: CallbackContext, manual_request=False, lang='en', user=None, ip=None, device=None):
    """إرسال رمز المصادقة إلى المجموعة مع التحقق من الصلاحيات"""
    config = load_config()
    
    if manual_request and user:
        if not can_user_request_code(user.id, config['max_requests_per_user']):
            context.bot.send_message(
                chat_id=user.id,
                text=MESSAGES[lang]['limit_reached'].format(max_requests=config['max_requests_per_user'])
            )
            return
        
        request_count = log_code_request(user, ip, device, config['max_requests_per_user'])
        admin_msg = MESSAGES['en']['admin_log'].format(
            user_name=user.full_name,
            user_id=user.id,
            time=get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
            device=device,
            ip=ip,
            request_count=request_count,
            max_requests=config['max_requests_per_user']
        )
        context.bot.send_message(chat_id=GROUP_CHAT_ID, text=admin_msg)
        
        context.bot.send_message(
            chat_id=user.id,
            text=MESSAGES[lang]['request_count'].format(
                request_count=request_count,
                max_requests=config['max_requests_per_user']
            )
        )
    
    code = generate_2fa_code()
    expiry_time = get_expiry_time()
    
    if manual_request:
        message = MESSAGES[lang]['manual_code'].format(code=code, expiry_time=expiry_time)
    else:
        message = MESSAGES[lang]['new_code'].format(code=code, expiry_time=expiry_time)
    
    # إرسال الرسالة مع التحكم في الرؤية
    if is_user_allowed(user.id if user else None):
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=MESSAGES[lang]['copy'],
                callback_data=f'copy_{code}'
            )
        ]])
    else:
        message = "🔒 You need permission to view authentication codes."
        reply_markup = None
    
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

def main():
    """الدالة الرئيسية"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # إضافة معالجات الأوامر
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("admin", show_admin_panel))
    dp.add_handler(CallbackQueryHandler(button_click))
    dp.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(change_max|toggle_visibility|manage_users|add_user|remove_user|back_to_panel)$'))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
    
    # تسجيل معالج الأخطاء
    dp.add_error_handler(error)

    # بدء البوت
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

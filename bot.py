#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackContext, 
    CallbackQueryHandler, MessageHandler, Filters,
    DispatcherHandlerStop
)
import pyotp
from datetime import datetime, timedelta
import pytz
import sqlite3
from contextlib import closing
import requests
from user_agents import parse

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
ADMIN_CHAT_ID = 792534650
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
MAX_REQUESTS_PER_USER = 5

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تهيئة المنطقة الزمنية لفلسطين
PALESTINE_TZ = pytz.timezone('Asia/Gaza')

# دعم اللغات
MESSAGES = {
    'en': {
        'new_code': "🔑 New Authentication Code Received\n\nA new code has been generated.",
        'manual_code': "🔄 Manual Code Request\n\nYour requested authentication code has been sent privately.",
        'copy': "📋 Copy Code",
        'request': "🔄 Request New Code",
        'help': "🤖 *Bot Commands*\n\n"
                "/start - Start the bot\n"
                "/help - Show this help message\n"
                "/info - Show your info\n"
                "/admin - Admin panel (admins only)\n\n"
                "Codes are valid for 10 minutes\n"
                "Each user can request up to {max_requests} codes per day",
        'welcome': "👋 Welcome to ChatGPTPlus2FA Bot! Use the buttons below to request codes.",
        'language': "🌐 Language",
        'code_copied': "✅ Code copied to clipboard!",
        'admin_log': "👤 User {user_name} (ID: {user_id}) requested a code at {time} (Palestine Time)\n📱 Device: {device}\n🔢 Total requests today: {request_count}/{max_requests}",
        'limit_reached': "⚠️ You have reached your daily limit of {max_requests} code requests.",
        'request_count': "🔄 You have used {request_count} out of {max_requests} allowed requests today.",
        'admin_panel': "👑 *Admin Panel*\n\n- Max requests per user: {max_requests}\n- Allowed users: {user_count}",
        'add_user': "➕ Add user",
        'remove_user': "➖ Remove user",
        'enter_user_id': "Please enter the user ID to add/remove:",
        'user_added': "✅ User {user_id} added to allowed list.",
        'user_removed': "✅ User {user_id} removed from allowed list.",
        'user_not_found': "⚠️ User not found in the allowed list.",
        'private_code': "🔑 Your authentication code:\n\n`{code}`\n\nValid until: {expiry_time}",
        'user_info': "👤 *Your Info*\n\nID: `{user_id}`\nName: {user_name}\nToday's requests: {request_count}/{max_requests}",
        'not_admin': "⛔ You are not authorized to use this command.",
        'commands': "🛠 *Available Commands*\n\n/start - Start bot\n/help - Show help\n/info - Your info\n/admin - Admin panel"
    },
    'ar': {
        'new_code': "🔑 تم توليد رمز مصادقة جديد",
        'manual_code': "🔄 طلب رمز يدوي\n\nتم إرسال رمز المصادقة لك بشكل خاص",
        'copy': "📋 نسخ الرمز",
        'request': "🔄 طلب رمز جديد",
        'help': "🤖 *أوامر البوت*\n\n"
                "/start - بدء البوت\n"
                "/help - عرض رسالة المساعدة\n"
                "/info - عرض معلوماتك\n"
                "/admin - لوحة التحكم (للمشرفين فقط)\n\n"
                "الرموز صالحة لمدة 10 دقائق\n"
                "يمكن لكل مستخدم طلب حتى {max_requests} رموز في اليوم",
        'welcome': "👋 مرحباً بكم في بوت ChatGPTPlus2FA! استخدم الأزرار أدناه لطلب الرموز.",
        'language': "🌐 اللغة",
        'code_copied': "✅ تم نسخ الرمز إلى الحافظة!",
        'admin_log': "👤 المستخدم {user_name} (ID: {user_id}) طلب رمزاً في {time} (توقيت فلسطين)\n📱 الجهاز: {device}\n🔢 إجمالي الطلبات اليوم: {request_count}/{max_requests}",
        'limit_reached': "⚠️ لقد وصلت إلى الحد الأقصى اليومى لطلبات الرموز ({max_requests}).",
        'request_count': "🔄 لقد استخدمت {request_count} من أصل {max_requests} طلبات مسموحة اليوم.",
        'admin_panel': "👑 *لوحة التحكم*\n\n- الحد الأقصى للطلبات لكل مستخدم: {max_requests}\n- المستخدمون المسموح لهم: {user_count}",
        'add_user': "➕ إضافة مستخدم",
        'remove_user': "➖ إزالة مستخدم",
        'enter_user_id': "الرجاء إدخال معرف المستخدم للإضافة/الإزالة:",
        'user_added': "✅ تمت إضافة المستخدم {user_id} إلى القائمة المسموح بها.",
        'user_removed': "✅ تمت إزالة المستخدم {user_id} من القائمة المسموح بها.",
        'user_not_found': "⚠️ المستخدم غير موجود في القائمة المسموح بها.",
        'private_code': "🔑 رمز المصادقة الخاص بك:\n\n`{code}`\n\nصالح حتى: {expiry_time}",
        'user_info': "👤 *معلوماتك*\n\nالمعرف: `{user_id}`\nالاسم: {user_name}\nطلبات اليوم: {request_count}/{max_requests}",
        'not_admin': "⛔ غير مصرح لك باستخدام هذا الأمر.",
        'commands': "🛠 *الأوامر المتاحة*\n\n/start - بدء البوت\n/help - المساعدة\n/info - معلوماتك\n/admin - لوحة التحكم"
    }
}

def init_database():
    """تهيئة قاعدة البيانات SQLite"""
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS code_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            request_time TEXT NOT NULL,
            device_info TEXT,
            ip_address TEXT,
            code_generated TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_limits (
            user_id INTEGER PRIMARY KEY,
            request_date TEXT NOT NULL,
            request_count INTEGER NOT NULL
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS allowed_users (
            user_id INTEGER PRIMARY KEY
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            event_time TEXT NOT NULL,
            description TEXT
        )
        ''')
        
        # إضافة المدير الأساسي إذا لم يكن موجوداً
        cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (ADMIN_CHAT_ID,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO admins (user_id) VALUES (?)', (ADMIN_CHAT_ID,))
        
        conn.commit()

def check_admin(user_id):
    """التحقق مما إذا كان المستخدم مشرفاً"""
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
        return cursor.fetchone() is not None

def check_user_allowed(user_id):
    """التحقق مما إذا كان المستخدم مسموحاً له"""
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM allowed_users WHERE user_id = ?', (user_id,))
        return cursor.fetchone() is not None

def admin_required(func):
    """مصمم للتحقق من صلاحيات المشرف"""
    def wrapper(update: Update, context: CallbackContext):
        user = update.effective_user
        if not check_admin(user.id):
            update.message.reply_text(MESSAGES['en']['not_admin'] if user.language_code != 'ar' else MESSAGES['ar']['not_admin'])
            raise DispatcherHandlerStop
        return func(update, context)
    return wrapper

def get_user_lang(user):
    """الحصول على لغة المستخدم"""
    return 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    user = update.effective_user
    lang = get_user_lang(user)
    
    update.message.reply_text(
        MESSAGES[lang]['welcome'],
        parse_mode='Markdown',
        reply_markup=create_keyboard(lang)
    )

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help"""
    user = update.effective_user
    lang = get_user_lang(user)
    
    update.message.reply_text(
        MESSAGES[lang]['help'].format(max_requests=MAX_REQUESTS_PER_USER),
        parse_mode='Markdown'
    )

def info_command(update: Update, context: CallbackContext):
    """معالجة أمر /info"""
    user = update.effective_user
    lang = get_user_lang(user)
    
    today = datetime.now().strftime('%Y-%m-%d')
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT request_count FROM user_limits 
        WHERE user_id = ? AND request_date = ?
        ''', (user.id, today))
        result = cursor.fetchone()
        request_count = result[0] if result else 0
    
    update.message.reply_text(
        MESSAGES[lang]['user_info'].format(
            user_id=user.id,
            user_name=user.full_name,
            request_count=request_count,
            max_requests=MAX_REQUESTS_PER_USER
        ),
        parse_mode='Markdown'
    )

@admin_required
def admin_command(update: Update, context: CallbackContext):
    """معالجة أمر /admin"""
    admin_panel(update, context)

def admin_panel(update: Update, context: CallbackContext):
    """لوحة تحكم إدارية محسنة"""
    user = update.effective_user
    lang = get_user_lang(user)
    
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM code_requests')
        total_requests = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM code_requests')
        unique_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM allowed_users')
        allowed_users = cursor.fetchone()[0]
        
    keyboard = [
        [InlineKeyboardButton("📊 Usage Stats" if lang == 'en' else "📊 إحصائيات الاستخدام", callback_data='usage_stats')],
        [InlineKeyboardButton("👥 Manage Users" if lang == 'en' else "👥 إدارة المستخدمين", callback_data='manage_users')],
        [InlineKeyboardButton("⚙️ System Settings" if lang == 'en' else "⚙️ إعدادات النظام", callback_data='system_settings')]
    ]
    
    update.message.reply_text(
        MESSAGES[lang]['admin_panel'].format(
            max_requests=MAX_REQUESTS_PER_USER,
            user_count=allowed_users
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def show_commands(update: Update, context: CallbackContext):
    """إظهار الأوامر المتاحة عند كتابة /"""
    user = update.effective_user
    lang = get_user_lang(user)
    
    if update.message.text == '/':
        update.message.reply_text(
            MESSAGES[lang]['commands'],
            parse_mode='Markdown'
        )

def main():
    """الدالة الرئيسية"""
    # تهيئة قاعدة البيانات
    init_database()
    
    # بدء البوت
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # إضافة معالجات الأوامر
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("info", info_command))
    dp.add_handler(CommandHandler("admin", admin_command))
    
    # إظهار الأوامر عند كتابة /
    dp.add_handler(MessageHandler(Filters.regex(r'^/$'), show_commands))
    
    # إضافة معالجات الأزرار
    dp.add_handler(CallbackQueryHandler(button_click))
    dp.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(usage_stats|manage_users|system_settings|add_user|remove_user|back_to_panel)$'))
    
    # إضافة معالجات الرسائل
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
    
    # بدء البوت
    updater.start_polling()
    logger.info("Bot started and polling...")
    updater.idle()

if __name__ == '__main__':
    main()

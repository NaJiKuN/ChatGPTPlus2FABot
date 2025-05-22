#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, Filters
import pyotp
from datetime import datetime, timedelta
import pytz
import sqlite3
from contextlib import closing
import requests
from user_agents import parse

# تكوين البوت (يجب الحفاظ على هذه البيانات الحساسة كما هي)
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
        'help': "🤖 *ChatGPTPlus2FA Bot Help*\n\n- Use 'Request New Code' to get a code\n- Codes are valid for 10 minutes\n- Each user can request up to {max_requests} codes per day",
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
        'private_code': "🔑 Your authentication code:\n\n`{code}`\n\nValid until: {expiry_time}"
    },
    'ar': {
        'new_code': "🔑 تم توليد رمز مصادقة جديد",
        'manual_code': "🔄 طلب رمز يدوي\n\nتم إرسال رمز المصادقة لك بشكل خاص",
        'copy': "📋 نسخ الرمز",
        'request': "🔄 طلب رمز جديد",
        'help': "🤖 *مساعدة بوت ChatGPTPlus2FA*\n\n- استخدم 'طلب رمز جديد' للحصول على رمز\n- الرموز صالحة لمدة 10 دقائق\n- يمكن لكل مستخدم طلب حتى {max_requests} رموز في اليوم",
        'welcome': "👋 مرحباً بكم في بوت ChatGPTPlus2FA! استخدم الأزرار أدناه لطلب الرموز.",
        'language': "🌐 اللغة",
        'code_copied': "✅ تم نسخ الرمز إلى الحافظة!",
        'admin_log': "👤 المستخدم {user_name} (ID: {user_id}) طلب رمزاً في {time} (توقيت فلسطين)\n📱 الجهاز: {device}\n🔢 إجمالي الطلبات اليوم: {request_count}/{max_requests}",
        'limit_reached': "⚠️ لقد وصلت إلى الحد الأقصى اليومي لطلبات الرموز ({max_requests}).",
        'request_count': "🔄 لقد استخدمت {request_count} من أصل {max_requests} طلبات مسموحة اليوم.",
        'admin_panel': "👑 *لوحة التحكم*\n\n- الحد الأقصى للطلبات لكل مستخدم: {max_requests}\n- المستخدمون المسموح لهم: {user_count}",
        'add_user': "➕ إضافة مستخدم",
        'remove_user': "➖ إزالة مستخدم",
        'enter_user_id': "الرجاء إدخال معرف المستخدم للإضافة/الإزالة:",
        'user_added': "✅ تمت إضافة المستخدم {user_id} إلى القائمة المسموح بها.",
        'user_removed': "✅ تمت إزالة المستخدم {user_id} من القائمة المسموح بها.",
        'user_not_found': "⚠️ المستخدم غير موجود في القائمة المسموح بها.",
        'private_code': "🔑 رمز المصادقة الخاص بك:\n\n`{code}`\n\nصالح حتى: {expiry_time}"
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

def get_client_ip():
    """الحصول على IP السيرفر"""
    try:
        return requests.get('https://api.ipify.org').text
    except Exception as e:
        logger.error(f"Error getting IP: {e}")
        return "Unknown"

def get_user_device(user_agent):
    """تحليل معلومات جهاز المستخدم"""
    try:
        ua = parse(user_agent)
        return f"{ua.device.family} {ua.os.family} {ua.browser.family}"
    except Exception as e:
        logger.error(f"Error parsing user agent: {e}")
        return "Unknown device"

def get_palestine_time():
    """الحصول على الوقت الحالي بتوقيت فلسطين"""
    return datetime.now(PALESTINE_TZ)

def generate_2fa_code():
    """توليد رمز المصادقة الثنائية مع وقت انتهاء"""
    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()
    expiry = get_palestine_time() + timedelta(minutes=10)
    return code, expiry.strftime('%Y-%m-%d %H:%M:%S')

def verify_2fa_code(code):
    """التحقق من صحة رمز المصادقة"""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.verify(code)

def check_user_permission(user_id):
    """فحص صلاحيات المستخدم مع مستويات متعددة"""
    try:
        with closing(sqlite3.connect('bot_data.db')) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
            if cursor.fetchone():
                return 'admin'
                
            cursor.execute('SELECT 1 FROM allowed_users WHERE user_id = ?', (user_id,))
            if cursor.fetchone():
                return 'allowed'
                
            return 'denied'
    except Exception as e:
        logger.error(f"Error checking user permissions: {e}")
        return 'denied'

def log_code_request(user_id, user_name, device_info, ip_address, code):
    """تسجيل طلب رمز جديد في قاعدة البيانات"""
    try:
        with closing(sqlite3.connect('bot_data.db')) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO code_requests 
            (user_id, user_name, request_time, device_info, ip_address, code_generated)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, user_name, datetime.now().isoformat(), device_info, ip_address, code))
            
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
            SELECT request_count FROM user_limits 
            WHERE user_id = ? AND request_date = ?
            ''', (user_id, today))
            
            result = cursor.fetchone()
            if result:
                new_count = result[0] + 1
                cursor.execute('''
                UPDATE user_limits 
                SET request_count = ? 
                WHERE user_id = ? AND request_date = ?
                ''', (new_count, user_id, today))
            else:
                cursor.execute('''
                INSERT INTO user_limits (user_id, request_date, request_count)
                VALUES (?, ?, 1)
                ''', (user_id, today))
            
            conn.commit()
            return new_count if result else 1
    except Exception as e:
        logger.error(f"Error logging code request: {e}")
        return 0

def can_user_request_code(user_id):
    """التحقق مما إذا كان يمكن للمستخدم طلب رمز آخر"""
    try:
        with closing(sqlite3.connect('bot_data.db')) as conn:
            cursor = conn.cursor()
            
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
            SELECT request_count FROM user_limits 
            WHERE user_id = ? AND request_date = ?
            ''', (user_id, today))
            
            result = cursor.fetchone()
            if not result:
                return True
                
            return result[0] < MAX_REQUESTS_PER_USER
    except Exception as e:
        logger.error(f"Error checking user limits: {e}")
        return False

def log_security_event(event_type, user_id, description):
    """تسجيل الأحداث الأمنية المهمة"""
    try:
        with closing(sqlite3.connect('bot_data.db')) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO security_events 
            (event_type, user_id, event_time, description)
            VALUES (?, ?, ?, ?)
            ''', (event_type, user_id, datetime.now().isoformat(), description))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Error logging security event: {e}")

def validate_user_id(user_id):
    """التحقق من صحة معرف المستخدم"""
    try:
        user_id = int(user_id)
        if user_id > 0:
            return True
        return False
    except ValueError:
        return False

def create_keyboard(lang='en'):
    """إنشاء لوحة مفاتيح مع أزرار النسخ والطلب"""
    keyboard = [
        [InlineKeyboardButton(MESSAGES[lang]['request'], callback_data='request_code')],
        [InlineKeyboardButton(MESSAGES[lang]['language'], callback_data='change_language')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_language_keyboard():
    """إنشاء لوحة مفاتيح اختيار اللغة"""
    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data='lang_en')],
        [InlineKeyboardButton("العربية 🇸🇦", callback_data='lang_ar')]
    ]
    return InlineKeyboardMarkup(keyboard)

def send_private_code(context, user, lang='en'):
    """إرسال رمز المصادقة بشكل خاص للمستخدم"""
    try:
        code, expiry_time = generate_2fa_code()
        device = "Unknown"
        ip = "Unknown"
        
        try:
            updates = context.bot.get_updates(limit=1)
            if updates:
                device = get_user_device(updates[-1].effective_user._effective_user_agent)
                ip = get_client_ip()
        except Exception as e:
            logger.error(f"Error getting device info: {e}")
        
        context.bot.send_message(
            chat_id=user.id,
            text=MESSAGES[lang]['private_code'].format(code=code, expiry_time=expiry_time),
            parse_mode='Markdown'
        )
        
        request_count = log_code_request(user.id, user.full_name, device, ip, code)
        
        if check_user_permission(user.id) == 'admin':
            admin_msg = MESSAGES['en']['admin_log'].format(
                user_name=user.full_name,
                user_id=user.id,
                time=get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
                device=device,
                request_count=request_count,
                max_requests=MAX_REQUESTS_PER_USER
            )
            
            if ip != "Unknown":
                admin_msg += f"\n🌐 IP: {ip}"
            
            context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg)
            
    except Exception as e:
        logger.error(f"Error sending private code: {e}")

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    try:
        user = update.effective_user
        user_lang = user.language_code or 'en'
        lang = 'ar' if user_lang.startswith('ar') else 'en'
        
        update.message.reply_text(
            MESSAGES[lang]['welcome'],
            parse_mode='Markdown',
            reply_markup=create_keyboard(lang)
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help"""
    try:
        user_lang = update.effective_user.language_code or 'en'
        lang = 'ar' if user_lang.startswith('ar') else 'en'
        
        update.message.reply_text(
            MESSAGES[lang]['help'].format(max_requests=MAX_REQUESTS_PER_USER),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in help command: {e}")

def admin_panel(update: Update, context: CallbackContext):
    """لوحة تحكم إدارية محسنة"""
    user = update.effective_user
    if check_user_permission(user.id) != 'admin':
        return
    
    with closing(sqlite3.connect('bot_data.db')) as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM code_requests')
        total_requests = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM code_requests')
        unique_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM allowed_users')
        allowed_users = cursor.fetchone()[0]
        
    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات الاستخدام", callback_data='usage_stats')],
        [InlineKeyboardButton("👥 إدارة المستخدمين", callback_data='manage_users')],
        [InlineKeyboardButton("⚙️ إعدادات النظام", callback_data='system_settings')]
    ]
    
    update.message.reply_text(
        f"👑 لوحة التحكم الإدارية\n\n"
        f"• إجمالي طلبات الرموز: {total_requests}\n"
        f"• عدد المستخدمين الفريدين: {unique_users}\n"
        f"• المستخدمون المسموح لهم: {allowed_users}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_admin_callback(update: Update, context: CallbackContext):
    """معالجة أحداث لوحة التحكم"""
    try:
        query = update.callback_query
        query.answer()
        user = query.from_user
        
        if check_user_permission(user.id) != 'admin':
            return
            
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        if query.data == 'usage_stats':
            with closing(sqlite3.connect('bot_data.db')) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                SELECT strftime('%Y-%m-%d', request_time) as day, 
                       COUNT(*) as requests 
                FROM code_requests 
                GROUP BY day 
                ORDER BY day DESC 
                LIMIT 7
                ''')
                
                stats = cursor.fetchall()
                stats_text = "📅 إحصائيات الطلبات خلال آخر 7 أيام:\n\n"
                for day, count in stats:
                    stats_text += f"• {day}: {count} طلب\n"
                
                query.edit_message_text(
                    text=stats_text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data='back_to_panel')]
                    ])
                )
        
        elif query.data == 'manage_users':
            keyboard = [
                [InlineKeyboardButton(MESSAGES[lang]['add_user'], callback_data='add_user')],
                [InlineKeyboardButton(MESSAGES[lang]['remove_user'], callback_data='remove_user')],
                [InlineKeyboardButton("🔙 رجوع", callback_data='back_to_panel')]
            ]
            query.edit_message_text(
                text="👥 إدارة المستخدمين",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data == 'system_settings':
            query.edit_message_text(
                text=f"⚙️ إعدادات النظام\n\n"
                     f"• الحد الأقصى للطلبات اليومية: {MAX_REQUESTS_PER_USER}\n"
                     f"• سرية الرموز: مفعلة",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع", callback_data='back_to_panel')]
                ])
            )
        
        elif query.data == 'add_user':
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_state'] = 'WAITING_FOR_USER_ADD'
        
        elif query.data == 'remove_user':
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_state'] = 'WAITING_FOR_USER_REMOVE'
        
        elif query.data == 'back_to_panel':
            admin_panel(update, context)
            
    except Exception as e:
        logger.error(f"Error in admin callback: {e}")

def handle_admin_input(update: Update, context: CallbackContext):
    """معالجة إدخالات لوحة التحكم"""
    try:
        user = update.effective_user
        if check_user_permission(user.id) != 'admin':
            return
        
        text = update.message.text
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        if context.user_data.get('admin_state') == 'WAITING_FOR_USER_ADD':
            if validate_user_id(text):
                user_id = int(text)
                with closing(sqlite3.connect('bot_data.db')) as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute('SELECT 1 FROM allowed_users WHERE user_id = ?', (user_id,))
                    if not cursor.fetchone():
                        cursor.execute('INSERT INTO allowed_users (user_id) VALUES (?)', (user_id,))
                        conn.commit()
                        update.message.reply_text(
                            MESSAGES[lang]['user_added'].format(user_id=user_id))
                        log_security_event('USER_ADDED', user.id, f"Added user {user_id}")
                    else:
                        update.message.reply_text(MESSAGES[lang]['user_not_found'])
            else:
                update.message.reply_text("⚠️ معرف مستخدم غير صالح!")
            
            admin_panel(update, context)
            context.user_data['admin_state'] = None
        
        elif context.user_data.get('admin_state') == 'WAITING_FOR_USER_REMOVE':
            if validate_user_id(text):
                user_id = int(text)
                with closing(sqlite3.connect('bot_data.db')) as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute('SELECT 1 FROM allowed_users WHERE user_id = ?', (user_id,))
                    if cursor.fetchone():
                        cursor.execute('DELETE FROM allowed_users WHERE user_id = ?', (user_id,))
                        conn.commit()
                        update.message.reply_text(
                            MESSAGES[lang]['user_removed'].format(user_id=user_id))
                        log_security_event('USER_REMOVED', user.id, f"Removed user {user_id}")
                    else:
                        update.message.reply_text(MESSAGES[lang]['user_not_found'])
            else:
                update.message.reply_text("⚠️ معرف مستخدم غير صالح!")
            
            admin_panel(update, context)
            context.user_data['admin_state'] = None
            
    except Exception as e:
        logger.error(f"Error in admin input: {e}")

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
    try:
        query = update.callback_query
        query.answer()
        user = query.from_user
        
        user_lang = user.language_code or 'en'
        lang = 'ar' if user_lang.startswith('ar') else 'en'
        
        if query.data == 'request_code':
            if check_user_permission(user.id) == 'denied':
                query.edit_message_text(text=MESSAGES[lang]['user_not_found'])
                return
                
            if not can_user_request_code(user.id):
                query.edit_message_text(
                    text=MESSAGES[lang]['limit_reached'].format(max_requests=MAX_REQUESTS_PER_USER)
                )
                return
            
            send_private_code(context, user, lang)
            
            with closing(sqlite3.connect('bot_data.db')) as conn:
                cursor = conn.cursor()
                today = datetime.now().strftime('%Y-%m-%d')
                cursor.execute('''
                SELECT request_count FROM user_limits 
                WHERE user_id = ? AND request_date = ?
                ''', (user.id, today))
                request_count = cursor.fetchone()[0]
            
            query.edit_message_text(
                text=MESSAGES[lang]['manual_code'] + "\n\n" + 
                MESSAGES[lang]['request_count'].format(
                    request_count=request_count,
                    max_requests=MAX_REQUESTS_PER_USER
                ),
                parse_mode='Markdown'
            )
            
        elif query.data == 'change_language':
            query.edit_message_text(
                text="🌐 Please choose your language / يرجى اختيار اللغة",
                reply_markup=create_language_keyboard()
            )
            
        elif query.data.startswith('lang_'):
            new_lang = query.data.split('_')[1]
            query.edit_message_text(
                text=MESSAGES[new_lang]['welcome'],
                parse_mode='Markdown',
                reply_markup=create_keyboard(new_lang))
                
    except Exception as e:
        logger.error(f"Error in button click: {e}")

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    try:
        error_msg = str(context.error) if context.error else "Unknown error"
        logger.warning(f'Update "{update}" caused error "{error_msg}"')
        log_security_event('ERROR', getattr(update.effective_user, 'id', None), error_msg)
    except Exception as e:
        print(f'Error logging error: {e}')

def main():
    """الدالة الرئيسية"""
    try:
        # تهيئة قاعدة البيانات
        init_database()
        
        # بدء البوت
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        # إضافة معالجات الأوامر
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("admin", admin_panel))
        
        # إضافة معالجات الأزرار
        dp.add_handler(CallbackQueryHandler(button_click))
        dp.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(usage_stats|manage_users|system_settings|add_user|remove_user|back_to_panel)$'))
        
        # إضافة معالجات الرسائل
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
        
        # تسجيل معالج الأخطاء
        dp.add_error_handler(error)

        # بدء البوت
        updater.start_polling()
        logger.info("Bot started and polling...")
        updater.idle()
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == '__main__':
    main()

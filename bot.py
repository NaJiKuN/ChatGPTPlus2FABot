#!/usr/bin/env python3
import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, Filters
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
ADMIN_CHAT_IDS = [792534650, 764559466]  # قائمة المسؤولين
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# مسارات الملفات
HOME_DIR = os.path.expanduser("~")
BOT_DIR = os.path.join(HOME_DIR, "ChatGPTPlus2FABot")
os.makedirs(BOT_DIR, exist_ok=True)

LOG_FILE = os.path.join(BOT_DIR, "code_requests.log")
CONFIG_FILE = os.path.join(BOT_DIR, "bot_config.json")
USER_LIMITS_FILE = os.path.join(BOT_DIR, "user_limits.json")
COPY_LOGS_FILE = os.path.join(BOT_DIR, "copy_logs.json")
REQUEST_LOGS_FILE = os.path.join(BOT_DIR, "request_logs.json")
DEFAULT_MAX_COPIES = 5

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(BOT_DIR, 'bot.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# تهيئة المنطقة الزمنية
PALESTINE_TZ = pytz.timezone('Asia/Gaza')

# تهيئة ملفات البيانات
def init_files():
    defaults = {
        "max_copies_per_user": DEFAULT_MAX_COPIES,
        "allowed_users": [],
        "admins": ADMIN_CHAT_IDS,
        "user_settings": {}
    }
    
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(defaults, f, indent=2)

    for file in [LOG_FILE, COPY_LOGS_FILE, REQUEST_LOGS_FILE]:
        if not os.path.exists(file):
            with open(file, 'w') as f:
                json.dump([], f)

init_files()

# دعم اللغات
MESSAGES = {
    'en': {
        'start': "👋 Welcome to ChatGPTPlus2FA Bot!",
        'help': "🤖 *Bot Help*\n\nCommands:\n/start - Start bot\n/help - Show help\n/settings - User settings\n/admin - Admin panel",
        'settings': "⚙️ *Your Settings*\n\n📋 Copies today: {copies}/{max_copies}\n🌐 Language: {language}",
        'new_code': "🔑 New Authentication Code\n\nClick below to copy",
        'copy': "📋 Copy Code",
        'code_copied': "✅ Code copied to clipboard!\n\n🔄 Copies left today: {remaining}/{max_copies}",
        'admin_panel': "👑 *Admin Panel*\n\n📋 Max copies: {max_copies}\n👥 Allowed users: {user_count}",
        'admin_only': "⚠️ Admins only!",
        'limit_reached': "⚠️ Daily limit reached ({max_copies})",
        'change_lang': "🌐 Change Language",
        'lang_changed': "✅ Language changed to {language}",
        'user_log': "👤 User: {user_name} (ID: {user_id})\n📅 Date: {date}\n📋 Action: {action}\n🔄 Copies today: {copies}/{max_copies}",
        'enter_user_id': "Please enter user ID:",
        'user_added': "✅ User {user_id} added",
        'user_removed': "✅ User {user_id} removed",
        'user_not_found': "⚠️ User not found",
        'enter_max_copies': "Enter new max copies (1-20):",
        'max_copies_updated': "✅ Max copies set to {max_copies}",
        'invalid_input': "⚠️ Invalid input",
        'request_log': "🔒 Manual code request by {user_name} (ID: {user_id})"
    },
    'ar': {
        'start': "👋 مرحبًا ببوت المصادقة!",
        'help': "🤖 *مساعدة البوت*\n\nالأوامر:\n/start - بدء البوت\n/help - المساعدة\n/settings - الإعدادات\n/admin - لوحة التحكم",
        'settings': "⚙️ *إعداداتك*\n\n📋 نسخ اليوم: {copies}/{max_copies}\n🌐 اللغة: {language}",
        'new_code': "🔑 رمز مصادقة جديد\n\nاضغط لنسخ الرمز",
        'copy': "📋 نسخ الرمز",
        'code_copied': "✅ تم نسخ الرمز!\n\n🔄 المتبقي اليوم: {remaining}/{max_copies}",
        'admin_panel': "👑 *لوحة التحكم*\n\n📋 الحد الأقصى: {max_copies}\n👥 المستخدمون المسموح لهم: {user_count}",
        'admin_only': "⚠️ للمشرفين فقط!",
        'limit_reached': "⚠️ وصلت للحد اليومي ({max_copies})",
        'change_lang': "🌐 تغيير اللغة",
        'lang_changed': "✅ تم تغيير اللغة إلى {language}",
        'user_log': "👤 المستخدم: {user_name} (ID: {user_id})\n📅 التاريخ: {date}\n📋 الإجراء: {action}\n🔄 نسخ اليوم: {copies}/{max_copies}",
        'enter_user_id': "الرجاء إدخال معرف المستخدم:",
        'user_added': "✅ تمت إضافة المستخدم {user_id}",
        'user_removed': "✅ تمت إزالة المستخدم {user_id}",
        'user_not_found': "⚠️ المستخدم غير موجود",
        'enter_max_copies': "أدخل الحد الأقصى الجديد للنسخ (1-20):",
        'max_copies_updated': "✅ تم تعيين الحد الأقصى للنسخ إلى {max_copies}",
        'invalid_input': "⚠️ إدخال غير صحيح",
        'request_log': "🔒 طلب رمز يدوي من {user_name} (ID: {user_id})"
    }
}

def get_config():
    """الحصول على إعدادات البوت"""
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    """حفظ إعدادات البوت"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def is_admin(user_id):
    """التحقق من صلاحية المسؤول"""
    config = get_config()
    return user_id in config.get('admins', ADMIN_CHAT_IDS)

def get_user_settings(user_id):
    """الحصول على إعدادات المستخدم"""
    config = get_config()
    return config['user_settings'].get(str(user_id), {'lang': 'en', 'copies_today': 0, 'last_copy_date': None})

def update_user_settings(user_id, settings):
    """تحديث إعدادات المستخدم"""
    config = get_config()
    config['user_settings'][str(user_id)] = settings
    save_config(config)

def get_user_lang(user_id):
    """الحصول على لغة المستخدم"""
    return get_user_settings(user_id)['lang']

def update_user_lang(user_id, lang):
    """تحديث لغة المستخدم"""
    settings = get_user_settings(user_id)
    settings['lang'] = lang
    update_user_settings(user_id, settings)
    return True

def can_user_copy(user_id):
    """التحقق من إمكانية نسخ الرمز"""
    config = get_config()
    max_copies = config['max_copies_per_user']
    settings = get_user_settings(user_id)
    
    today = get_palestine_time().strftime('%Y-%m-%d')
    last_copy_date = settings.get('last_copy_date')
    
    if last_copy_date != today:
        return True, max_copies, 0
    
    copies_today = settings.get('copies_today', 0)
    return copies_today < max_copies, max_copies, copies_today

def update_copy_count(user_id):
    """تحديث عدد نسخ المستخدم"""
    settings = get_user_settings(user_id)
    today = get_palestine_time().strftime('%Y-%m-%d')
    
    if settings.get('last_copy_date') != today:
        settings['copies_today'] = 1
    else:
        settings['copies_today'] += 1
    
    settings['last_copy_date'] = today
    update_user_settings(user_id, settings)
    return settings['copies_today']

def log_action(log_file, action_data):
    """تسجيل أي عمل في الملفات"""
    try:
        with open(log_file, 'r+') as f:
            logs = json.load(f)
            logs.append(action_data)
            f.seek(0)
            json.dump(logs, f, indent=2)
    except Exception as e:
        logger.error(f"Error logging action: {e}")

def create_copy_button(lang='en'):
    """إنشاء زر النسخ مع دعم نسخ الحافظة"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code')],
        [InlineKeyboardButton(MESSAGES[lang]['change_lang'], callback_data='change_lang')]
    ])

def create_lang_keyboard(user_id):
    """إنشاء لوحة اختيار اللغة"""
    current_lang = get_user_lang(user_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("English 🇬🇧" + (" ✅" if current_lang == 'en' else ""), 
            callback_data='set_lang_en'),
            InlineKeyboardButton("العربية 🇸🇦" + (" ✅" if current_lang == 'ar' else ""), 
            callback_data='set_lang_ar')
        ]
    ])

def create_admin_keyboard(lang='en'):
    """إنشاء لوحة تحكم المسؤول"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Change Max Copies", callback_data='change_max_copies')],
        [InlineKeyboardButton("👥 Manage Users", callback_data='manage_users')],
        [InlineKeyboardButton("📋 View Logs", callback_data='view_logs')]
    ])

def create_user_management_keyboard(lang='en'):
    """إنشاء لوحة إدارة المستخدمين"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add User", callback_data='add_user')],
        [InlineKeyboardButton("➖ Remove User", callback_data='remove_user')],
        [InlineKeyboardButton("🔙 Back", callback_data='back_to_admin')]
    ])

def send_auto_code(context: CallbackContext):
    """إرسال تلقائي للرمز"""
    try:
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=MESSAGES['en']['new_code'],
            reply_markup=create_copy_button('en')
        )
    except Exception as e:
        logger.error(f"Error in send_auto_code: {e}")

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    try:
        user = update.effective_user
        lang = get_user_lang(user.id)
        
        if str(user.id) not in get_config()['user_settings']:
            update_user_settings(user.id, {'lang': lang, 'copies_today': 0, 'last_copy_date': None})
        
        update.message.reply_text(
            MESSAGES[lang]['start'],
            reply_markup=create_copy_button(lang)
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help"""
    try:
        user = update.effective_user
        lang = get_user_lang(user.id)
        update.message.reply_text(
            MESSAGES[lang]['help'],
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in help command: {e}")

def settings_command(update: Update, context: CallbackContext):
    """معالجة أمر /settings"""
    try:
        user = update.effective_user
        lang = get_user_lang(user.id)
        config = get_config()
        settings = get_user_settings(user.id)
        
        today = get_palestine_time().strftime('%Y-%m-%d')
        copies_today = 0 if settings.get('last_copy_date') != today else settings.get('copies_today', 0)
        
        language_name = "English" if lang == 'en' else "العربية"
        
        update.message.reply_text(
            MESSAGES[lang]['settings'].format(
                copies=copies_today,
                max_copies=config['max_copies_per_user'],
                language=language_name
            ),
            parse_mode='Markdown',
            reply_markup=create_lang_keyboard(user.id)
        )
    except Exception as e:
        logger.error(f"Error in settings command: {e}")

def admin_command(update: Update, context: CallbackContext):
    """معالجة أمر /admin"""
    try:
        user = update.effective_user
        if not is_admin(user.id):
            lang = get_user_lang(user.id)
            update.message.reply_text(MESSAGES[lang]['admin_only'])
            return
        
        lang = get_user_lang(user.id)
        config = get_config()
        
        update.message.reply_text(
            MESSAGES[lang]['admin_panel'].format(
                max_copies=config['max_copies_per_user'],
                user_count=len(config['allowed_users'])
            ),
            parse_mode='Markdown',
            reply_markup=create_admin_keyboard(lang)
        )
    except Exception as e:
        logger.error(f"Error in admin command: {e}")

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
    try:
        query = update.callback_query
        query.answer()
        user = query.from_user
        lang = get_user_lang(user.id)
        
        if query.data == 'copy_code':
            can_copy, max_copies, copies_today = can_user_copy(user.id)
            
            if not can_copy:
                query.edit_message_text(MESSAGES[lang]['limit_reached'].format(max_copies=max_copies))
                return
            
            code = generate_2fa_code()
            copies_today = update_copy_count(user.id)
            remaining = max(0, max_copies - copies_today)
            
            # إرسال الرمز مع زر النسخ الفعلي
            context.bot.send_message(
                chat_id=user.id,
                text=f"✅ {MESSAGES[lang]['code_copied'].format(remaining=remaining, max_copies=max_copies)}\n\n<code>{code}</code>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        MESSAGES[lang]['copy'],
                        callback_data=f'copy_{code}'
                    )]
                ])
            )
            
            # تسجيل العملية
            log_action(COPY_LOGS_FILE, {
                'user_id': user.id,
                'user_name': user.full_name,
                'date': get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
                'action': 'copy_code',
                'copies_today': copies_today,
                'max_copies': max_copies
            })
            
        elif query.data.startswith('copy_'):
            code = query.data.split('_')[1]
            query.edit_message_text(
                text=f"✅ {MESSAGES[lang]['code_copied'].format(remaining='?', max_copies='?')}\n\n<code>{code}</code>",
                parse_mode='HTML'
            )
            
        elif query.data == 'change_lang':
            query.edit_message_text(
                "🌐 Please choose your language / يرجى اختيار اللغة",
                reply_markup=create_lang_keyboard(user.id)
            )
            
        elif query.data.startswith('set_lang_'):
            new_lang = query.data.split('_')[-1]
            if update_user_lang(user.id, new_lang):
                lang_name = "English" if new_lang == 'en' else "العربية"
                query.edit_message_text(
                    MESSAGES[new_lang]['lang_changed'].format(language=lang_name),
                    reply_markup=create_copy_button(new_lang)
                )
        
        elif query.data == 'change_max_copies' and is_admin(user.id):
            query.edit_message_text(MESSAGES[lang]['enter_max_copies'])
            context.user_data['admin_action'] = 'change_max_copies'
        
        elif query.data == 'manage_users' and is_admin(user.id):
            query.edit_message_text(
                "👥 User Management / إدارة المستخدمين",
                reply_markup=create_user_management_keyboard(lang)
            )
        
        elif query.data == 'add_user' and is_admin(user.id):
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_action'] = 'add_user'
        
        elif query.data == 'remove_user' and is_admin(user.id):
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_action'] = 'remove_user'
        
        elif query.data == 'view_logs' and is_admin(user.id):
            try:
                with open(COPY_LOGS_FILE, 'r') as f:
                    logs = json.load(f)
                    if not logs:
                        query.edit_message_text("No logs available yet / لا توجد سجلات متاحة بعد")
                        return
                    
                    # إرسال آخر 10 عمليات نسخ
                    recent_logs = logs[-10:]
                    log_text = "📋 Last 10 Copy Logs / آخر 10 عمليات نسخ:\n\n"
                    for log in reversed(recent_logs):
                        log_text += f"👤 {log['user_name']} (ID: {log['user_id']})\n"
                        log_text += f"📅 {log['date']}\n"
                        log_text += f"🔄 {log['copies_today']}/{log['max_copies']} copies\n\n"
                    
                    query.edit_message_text(log_text)
            except Exception as e:
                logger.error(f"Error viewing logs: {e}")
                query.edit_message_text("Error loading logs / حدث خطأ في تحميل السجلات")
        
        elif query.data == 'back_to_admin' and is_admin(user.id):
            admin_command(update, context)
    
    except Exception as e:
        logger.error(f"Error in button click: {e}")

def handle_message(update: Update, context: CallbackContext):
    """معالجة الرسائل النصية"""
    try:
        user = update.effective_user
        message = update.message.text
        lang = get_user_lang(user.id)
        
        if 'admin_action' in context.user_data:
            action = context.user_data['admin_action']
            
            if action == 'change_max_copies':
                try:
                    new_max = int(message)
                    if 1 <= new_max <= 20:
                        config = get_config()
                        config['max_copies_per_user'] = new_max
                        save_config(config)
                        
                        update.message.reply_text(
                            MESSAGES[lang]['max_copies_updated'].format(max_copies=new_max)
                        )
                        context.user_data.pop('admin_action', None)
                        admin_command(update, context)
                    else:
                        update.message.reply_text(MESSAGES[lang]['invalid_input'])
                except ValueError:
                    update.message.reply_text(MESSAGES[lang]['invalid_input'])
            
            elif action in ['add_user', 'remove_user']:
                try:
                    user_id = int(message)
                    config = get_config()
                    
                    if action == 'add_user':
                        if user_id not in config['allowed_users']:
                            config['allowed_users'].append(user_id)
                            save_config(config)
                            update.message.reply_text(
                                MESSAGES[lang]['user_added'].format(user_id=user_id))
                        else:
                            update.message.reply_text(
                                MESSAGES[lang]['user_not_found'])
                    
                    elif action == 'remove_user':
                        if user_id in config['allowed_users']:
                            config['allowed_users'].remove(user_id)
                            save_config(config)
                            update.message.reply_text(
                                MESSAGES[lang]['user_removed'].format(user_id=user_id))
                        else:
                            update.message.reply_text(
                                MESSAGES[lang]['user_not_found'])
                    
                    context.user_data.pop('admin_action', None)
                    admin_command(update, context)
                except ValueError:
                    update.message.reply_text(MESSAGES[lang]['invalid_input'])
        
        else:
            update.message.reply_text(MESSAGES[lang]['invalid_command'])
    
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    logger.error(f'Update "{update}" caused error "{context.error}"')

def main():
    """الدالة الرئيسية"""
    try:
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        job_queue = updater.job_queue

        # جدولة الإرسال التلقائي
        job_queue.run_repeating(send_auto_code, interval=300, first=0)

        # معالجات الأوامر
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("settings", settings_command))
        dp.add_handler(CommandHandler("admin", admin_command))
        
        # معالجات الأزرار والرسائل
        dp.add_handler(CallbackQueryHandler(button_click))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
        
        dp.add_error_handler(error)

        # بدء البوت
        updater.start_polling()
        logger.info("Bot started and running successfully!")
        updater.idle()
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()

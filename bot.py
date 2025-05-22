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
DEFAULT_MAX_COPIES = 5  # الحد الافتراضي لنسخ الرموز

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
        "user_settings": {}
    }
    
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(defaults, f, indent=2)

    if not os.path.exists(COPY_LOGS_FILE):
        with open(COPY_LOGS_FILE, 'w') as f:
            json.dump([], f)

init_files()

# دعم اللغات
MESSAGES = {
    'en': {
        'start': "👋 Welcome to ChatGPTPlus2FA Bot!\n\nI automatically send 2FA codes every 5 minutes to the group.",
        'help': "🤖 *Bot Help*\n\nCommands:\n/start - Start bot\n/help - Show help\n/settings - User settings\n/admin - Admin panel (admins only)",
        'settings': "⚙️ *Your Settings*\n\n📋 Copies today: {copies}/{max_copies}\n🌐 Language: {language}",
        'new_code': "🔑 New Authentication Code\n\nClick below to copy",
        'copy': "📋 Copy Code",
        'code_copied': "✅ Code copied!\n\n`{code}`\nValid for 10 minutes.\n📋 Copies left today: {remaining}/{max_copies}",
        'admin_panel': "👑 *Admin Panel*\n\n📋 Max copies per user: {max_copies}\n👥 Allowed users: {user_count}",
        'admin_only': "⚠️ This command is for admins only!",
        'limit_reached': "⚠️ Daily copy limit reached ({max_copies})",
        'change_lang': "🌐 Change Language",
        'lang_changed': "✅ Language changed to {language}",
        'user_log': "👤 User: {user_name} (ID: {user_id})\n📅 Date: {date}\n📋 Action: Code copy\n🔄 Copies today: {copies}/{max_copies}",
        'invalid_command': "⚠️ Invalid command. Use /help to see available commands."
    },
    'ar': {
        'start': "👋 مرحبًا ببوت المصادقة!\n\nسأرسل رموز المصادقة تلقائيًا كل 5 دقائق للمجموعة.",
        'help': "🤖 *مساعدة البوت*\n\nالأوامر:\n/start - بدء البوت\n/help - المساعدة\n/settings - الإعدادات\n/admin - لوحة التحكم (للمشرفين فقط)",
        'settings': "⚙️ *إعداداتك*\n\n📋 نسخ اليوم: {copies}/{max_copies}\n🌐 اللغة: {language}",
        'new_code': "🔑 رمز مصادقة جديد\n\nاضغط لنسخ الرمز",
        'copy': "📋 نسخ الرمز",
        'code_copied': "✅ تم النسخ!\n\n`{code}`\nصالح لمدة 10 دقائق.\n📋 المتبقي اليوم: {remaining}/{max_copies}",
        'admin_panel': "👑 *لوحة التحكم*\n\n📋 الحد الأقصى للنسخ: {max_copies}\n👥 المستخدمون المسموح لهم: {user_count}",
        'admin_only': "⚠️ هذا الأمر للمشرفين فقط!",
        'limit_reached': "⚠️ وصلت للحد اليومي ({max_copies})",
        'change_lang': "🌐 تغيير اللغة",
        'lang_changed': "✅ تم تغيير اللغة إلى {language}",
        'user_log': "👤 المستخدم: {user_name} (ID: {user_id})\n📅 التاريخ: {date}\n📋 الإجراء: نسخ رمز\n🔄 نسخ اليوم: {copies}/{max_copies}",
        'invalid_command': "⚠️ أمر غير صحيح. استخدم /help لرؤية الأوامر المتاحة."
    }
}

def is_admin(user_id):
    """التحقق من صلاحية المسؤول"""
    return user_id in ADMIN_CHAT_IDS

def get_config():
    """الحصول على إعدادات البوت"""
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    """حفظ إعدادات البوت"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

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

def log_copy_action(user, code):
    """تسجيل عملية النسخ"""
    try:
        with open(COPY_LOGS_FILE, 'r+') as f:
            logs = json.load(f)
            
            can_copy, max_copies, copies_today = can_user_copy(user.id)
            log_entry = {
                'user_id': user.id,
                'user_name': user.full_name,
                'date': get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
                'code': code,
                'copies_today': copies_today + 1,
                'max_copies': max_copies
            }
            
            logs.append(log_entry)
            f.seek(0)
            json.dump(logs, f, indent=2)
            
        # إرسال السجل للمسؤولين
        for admin_id in ADMIN_CHAT_IDS:
            try:
                lang = get_user_lang(admin_id)
                context.bot.send_message(
                    chat_id=admin_id,
                    text=MESSAGES[lang]['user_log'].format(
                        user_name=user.full_name,
                        user_id=user.id,
                        date=log_entry['date'],
                        copies=log_entry['copies_today'],
                        max_copies=max_copies
                    )
                )
            except Exception as e:
                logger.error(f"Error sending log to admin {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Error logging copy action: {e}")

def create_copy_button(lang='en'):
    """إنشاء زر النسخ"""
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

def send_auto_code(context: CallbackContext):
    """إرسال تلقائي للرمز"""
    try:
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=MESSAGES['en']['new_code'],
            reply_markup=create_copy_button('en')
        )
        logger.info("Sent auto code to group")
    except Exception as e:
        logger.error(f"Error in send_auto_code: {e}")

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    try:
        user = update.effective_user
        lang = get_user_lang(user.id)
        
        # إرسال رسالة الترحيب
        update.message.reply_text(
            MESSAGES[lang]['start'],
            parse_mode='Markdown'
        )
        
        # إرسال رسالة المساعدة إذا كان المستخدم جديدًا
        if str(user.id) not in get_config()['user_settings']:
            update.message.reply_text(
                MESSAGES[lang]['help'],
                parse_mode='Markdown'
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
        if settings.get('last_copy_date') != today:
            copies_today = 0
        else:
            copies_today = settings.get('copies_today', 0)
        
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
        
        keyboard = [
            [InlineKeyboardButton("✏️ Change Max Copies", callback_data='change_max_copies')],
            [InlineKeyboardButton("👥 View Copy Logs", callback_data='view_logs')]
        ]
        
        update.message.reply_text(
            MESSAGES[lang]['admin_panel'].format(
                max_copies=config['max_copies_per_user'],
                user_count=len(config['allowed_users'])
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
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
            
            # إرسال الرمز للمستخدم
            context.bot.send_message(
                chat_id=user.id,
                text=MESSAGES[lang]['code_copied'].format(
                    code=code,
                    remaining=remaining,
                    max_copies=max_copies
                ),
                parse_mode='Markdown'
            )
            
            # تسجيل العملية
            log_copy_action(user, code)
            
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
            query.edit_message_text("Please enter the new maximum copies per user (1-20):")
            context.user_data['waiting_for_max'] = True
        
        elif query.data == 'view_logs' and is_admin(user.id):
            try:
                with open(COPY_LOGS_FILE, 'r') as f:
                    logs = json.load(f)
                    if not logs:
                        query.edit_message_text("No copy logs available yet.")
                        return
                    
                    # إرسال آخر 10 عمليات نسخ
                    recent_logs = logs[-10:]
                    log_text = "📋 *Last 10 Copy Logs*\n\n" if lang == 'en' else "📋 *آخر 10 عمليات نسخ*\n\n"
                    for log in reversed(recent_logs):
                        log_text += f"👤 {log['user_name']} (ID: {log['user_id']})\n"
                        log_text += f"📅 {log['date']}\n"
                        log_text += f"🔄 {log['copies_today']}/{log['max_copies']} copies\n\n"
                    
                    query.edit_message_text(log_text, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error viewing logs: {e}")
                error_msg = "Error loading logs." if lang == 'en' else "حدث خطأ في تحميل السجلات."
                query.edit_message_text(error_msg)
    
    except Exception as e:
        logger.error(f"Error in button click: {e}")

def handle_admin_input(update: Update, context: CallbackContext):
    """معالجة إدخالات المسؤول"""
    try:
        user = update.effective_user
        if not is_admin(user.id):
            return
        
        if context.user_data.get('waiting_for_max'):
            try:
                new_max = int(update.message.text)
                if 1 <= new_max <= 20:
                    config = get_config()
                    config['max_copies_per_user'] = new_max
                    save_config(config)
                    
                    lang = get_user_lang(user.id)
                    success_msg = f"✅ Max copies per user set to {new_max}" if lang == 'en' else f"✅ تم تعيين الحد الأقصى للنسخ إلى {new_max}"
                    update.message.reply_text(success_msg)
                    
                    context.user_data['waiting_for_max'] = False
                    admin_command(update, context)
                else:
                    update.message.reply_text("Please enter a number between 1 and 20.")
            except ValueError:
                update.message.reply_text("Invalid input. Please enter a number between 1 and 20.")
    except Exception as e:
        logger.error(f"Error in handle_admin_input: {e}")

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
        
        # معالجات الأزرار والإدخال
        dp.add_handler(CallbackQueryHandler(button_click))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
        
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

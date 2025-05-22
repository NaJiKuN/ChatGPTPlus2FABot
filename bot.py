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
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f:
            json.dump([], f)

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({
                "max_copies_per_user": DEFAULT_MAX_COPIES,
                "allowed_users": [],
                "user_limits": {}
            }, f)

    if not os.path.exists(COPY_LOGS_FILE):
        with open(COPY_LOGS_FILE, 'w') as f:
            json.dump([], f)

init_files()

# دعم اللغات
MESSAGES = {
    'en': {
        'start': "👋 Welcome to ChatGPTPlus2FA Bot!",
        'help': "🤖 *Bot Help*\n\nCommands:\n/start - Start bot\n/help - Show help\n/settings - User settings",
        'settings': "⚙️ *Your Settings*\n\nCopies today: {copies_count}/{max_copies}\nLanguage: {language}",
        'new_code': "🔑 New Authentication Code\n\nClick below to copy",
        'copy': "📋 Copy Code",
        'code_copied': "✅ Code copied!\n\n`{code}`\nValid for 10 minutes.\nCopies left today: {remaining}/{max_copies}",
        'admin_panel': "👑 *Admin Panel*\n\nMax copies per user: {max_copies}\nAllowed users: {user_count}",
        'admin_only': "⚠️ Admins only!",
        'limit_reached': "⚠️ Daily copy limit reached ({max_copies})",
        'change_lang': "🌐 Change Language",
        'lang_changed': "✅ Language changed to {language}",
        'user_log': "👤 User: {user_name} (ID: {user_id})\n📅 Date: {date}\n📋 Action: Code copy\n🔄 Copies today: {copies}/{max_copies}"
    },
    'ar': {
        'start': "👋 مرحبًا ببوت المصادقة!",
        'help': "🤖 *مساعدة البوت*\n\nالأوامر:\n/start - بدء البوت\n/help - المساعدة\n/settings - الإعدادات",
        'settings': "⚙️ *إعداداتك*\n\nنسخ اليوم: {copies_count}/{max_copies}\nاللغة: {language}",
        'new_code': "🔑 رمز مصادقة جديد\n\nاضغط لنسخ الرمز",
        'copy': "📋 نسخ الرمز",
        'code_copied': "✅ تم النسخ!\n\n`{code}`\nصالح لمدة 10 دقائق.\nالمتبقي اليوم: {remaining}/{max_copies}",
        'admin_panel': "👑 *لوحة التحكم*\n\nالحد الأقصى للنسخ: {max_copies}\nالمستخدمون المسموح لهم: {user_count}",
        'admin_only': "⚠️ للمشرفين فقط!",
        'limit_reached': "⚠️ وصلت للحد اليومي ({max_copies})",
        'change_lang': "🌐 تغيير اللغة",
        'lang_changed': "✅ تم تغيير اللغة إلى {language}",
        'user_log': "👤 المستخدم: {user_name} (ID: {user_id})\n📅 التاريخ: {date}\n📋 الإجراء: نسخ رمز\n🔄 نسخ اليوم: {copies}/{max_copies}"
    }
}

def is_admin(user_id):
    """التحقق من صلاحية المسؤول"""
    return user_id in ADMIN_CHAT_IDS

def get_user_lang(user_id):
    """الحصول على لغة المستخدم"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            return config['user_limits'].get(str(user_id), {}).get('lang', 'en')
    except:
        return 'en'

def update_user_lang(user_id, lang):
    """تحديث لغة المستخدم"""
    try:
        with open(CONFIG_FILE, 'r+') as f:
            config = json.load(f)
            if 'user_limits' not in config:
                config['user_limits'] = {}
            if str(user_id) not in config['user_limits']:
                config['user_limits'][str(user_id)] = {}
            config['user_limits'][str(user_id)]['lang'] = lang
            f.seek(0)
            json.dump(config, f, indent=2)
            f.truncate()
        return True
    except Exception as e:
        logger.error(f"Error updating user lang: {e}")
        return False

def can_user_copy(user_id):
    """التحقق من إمكانية نسخ الرمز"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            max_copies = config.get('max_copies_per_user', DEFAULT_MAX_COPIES)
            
            today = get_palestine_time().strftime('%Y-%m-%d')
            
            if str(user_id) not in config['user_limits']:
                return True, max_copies, 0
            
            if config['user_limits'][str(user_id)].get('last_copy_date') != today:
                return True, max_copies, 0
                
            copies_today = config['user_limits'][str(user_id)].get('copies_today', 0)
            return copies_today < max_copies, max_copies, copies_today
    except:
        return True, DEFAULT_MAX_COPIES, 0

def update_copy_count(user_id):
    """تحديث عدد نسخ المستخدم"""
    try:
        with open(CONFIG_FILE, 'r+') as f:
            config = json.load(f)
            today = get_palestine_time().strftime('%Y-%m-%d')
            
            if 'user_limits' not in config:
                config['user_limits'] = {}
                
            if str(user_id) not in config['user_limits']:
                config['user_limits'][str(user_id)] = {
                    'last_copy_date': today,
                    'copies_today': 1
                }
            else:
                if config['user_limits'][str(user_id)].get('last_copy_date') != today:
                    config['user_limits'][str(user_id)] = {
                        'last_copy_date': today,
                        'copies_today': 1
                    }
                else:
                    config['user_limits'][str(user_id)]['copies_today'] += 1
            
            f.seek(0)
            json.dump(config, f, indent=2)
            f.truncate()
            
        return config['user_limits'][str(user_id)]['copies_today']
    except Exception as e:
        logger.error(f"Error updating copy count: {e}")
        return 1

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
            f.truncate()
            
        # إرسال السجل للمسؤولين
        for admin_id in ADMIN_CHAT_IDS:
            try:
                lang = get_user_lang(admin_id)
                context.bot.send_message(
                    chat_id=admin_id,
                    text=MESSAGES[lang]['user_log'].format(
                        user_name=user.full_name,
                        user_id=user.id,
                        date=get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
                        copies=copies_today + 1,
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
    except Exception as e:
        logger.error(f"Error in send_auto_code: {e}")

def start(update: Update, context: CallbackContext):
    """معالجة /start"""
    user = update.effective_user
    lang = get_user_lang(user.id)
    update.message.reply_text(MESSAGES[lang]['start'])

def help_command(update: Update, context: CallbackContext):
    """معالجة /help"""
    user = update.effective_user
    lang = get_user_lang(user.id)
    update.message.reply_text(MESSAGES[lang]['help'], parse_mode='Markdown')

def settings_command(update: Update, context: CallbackContext):
    """معالجة /settings"""
    user = update.effective_user
    lang = get_user_lang(user.id)
    
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        max_copies = config.get('max_copies_per_user', DEFAULT_MAX_COPIES)
        
        today = get_palestine_time().strftime('%Y-%m-%d')
        copies_today = config['user_limits'].get(str(user.id), {}).get('copies_today', 0) if config['user_limits'].get(str(user.id), {}).get('last_copy_date') == today else 0
    
    update.message.reply_text(
        MESSAGES[lang]['settings'].format(
            copies_count=copies_today,
            max_copies=max_copies,
            language="English" if lang == 'en' else "العربية"
        ),
        parse_mode='Markdown'
    )

def admin_command(update: Update, context: CallbackContext):
    """معالجة /admin"""
    user = update.effective_user
    if not is_admin(user.id):
        lang = get_user_lang(user.id)
        update.message.reply_text(MESSAGES[lang]['admin_only'])
        return
    
    lang = get_user_lang(user.id)
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    
    keyboard = [
        [InlineKeyboardButton("✏️ Change Max Copies", callback_data='change_max_copies')],
        [InlineKeyboardButton("👥 View Copy Logs", callback_data='view_logs')]
    ]
    
    update.message.reply_text(
        MESSAGES[lang]['admin_panel'].format(
            max_copies=config.get('max_copies_per_user', DEFAULT_MAX_COPIES),
            user_count=len(config.get('allowed_users', []))
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
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
            query.edit_message_text(
                MESSAGES[new_lang]['lang_changed'].format(language="English" if new_lang == 'en' else "العربية"),
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
                log_text = "📋 *Last 10 Copy Logs*\n\n"
                for log in reversed(recent_logs):
                    log_text += f"👤 {log['user_name']} (ID: {log['user_id']})\n"
                    log_text += f"📅 {log['date']}\n"
                    log_text += f"🔄 {log['copies_today']}/{log['max_copies']} copies\n\n"
                
                query.edit_message_text(log_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error viewing logs: {e}")
            query.edit_message_text("Error loading logs.")

def handle_admin_input(update: Update, context: CallbackContext):
    """معالجة إدخالات المسؤول"""
    user = update.effective_user
    if not is_admin(user.id):
        return
    
    if context.user_data.get('waiting_for_max'):
        try:
            new_max = int(update.message.text)
            if 1 <= new_max <= 20:
                with open(CONFIG_FILE, 'r+') as f:
                    config = json.load(f)
                    config['max_copies_per_user'] = new_max
                    f.seek(0)
                    json.dump(config, f, indent=2)
                    f.truncate()
                
                lang = get_user_lang(user.id)
                update.message.reply_text(
                    f"✅ Max copies per user set to {new_max}" if lang == 'en' else f"✅ تم تعيين الحد الأقصى للنسخ إلى {new_max}"
                )
                context.user_data['waiting_for_max'] = False
                admin_command(update, context)
            else:
                update.message.reply_text("Please enter a number between 1 and 20.")
        except ValueError:
            update.message.reply_text("Invalid input. Please enter a number between 1 and 20.")

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    logger.warning(f'Update "{update}" caused error "{context.error}"')

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
        logger.info("Bot started successfully!")
        updater.idle()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()

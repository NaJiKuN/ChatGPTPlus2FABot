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
ADMIN_CHAT_ID = 792534650  # Chat ID الخاص بالمسؤول
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
LOG_FILE = "code_requests.log"
CONFIG_FILE = "bot_config.json"
USER_LIMITS_FILE = "user_limits.json"
MAX_REQUESTS_PER_USER = 5

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تهيئة المنطقة الزمنية لفلسطين
PALESTINE_TZ = pytz.timezone('Asia/Gaza')

# تهيئة ملفات البيانات
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({
            "max_requests_per_user": MAX_REQUESTS_PER_USER,
            "code_visibility": False,
            "allowed_users": []
        }, f)

if not os.path.exists(USER_LIMITS_FILE):
    with open(USER_LIMITS_FILE, 'w') as f:
        json.dump({}, f)

# دعم اللغات
MESSAGES = {
    'en': {
        'start': "👋 Welcome to ChatGPTPlus2FA Bot!\n\nI automatically send 2FA codes every 5 minutes to the group.\n\nUse /help to see available commands.",
        'help': "🤖 *Bot Help*\n\nAvailable commands:\n\n/start - Start interaction with bot\n/help - Show this help message\n/settings - User settings\n\nFor group admins:\n/admin - Admin panel",
        'settings': "⚙️ *Your Settings*\n\nLanguage: English\nDaily code requests: {request_count}/{max_requests}",
        'new_code': "🔑 New Authentication Code\n\nClick the button below to copy the code",
        'copy': "📋 Copy Code",
        'code_copied': "✅ Code copied to clipboard!",
        'admin_panel': "👑 *Admin Panel*\n\n- Max requests per user: {max_requests}\n- Code visibility: {visibility}\n- Allowed users: {user_count}",
        'admin_only': "⚠️ This command is for admins only!",
        'request_count': "🔄 You have used {request_count} out of {max_requests} allowed requests today.",
        'limit_reached': "⚠️ You have reached your daily limit of {max_requests} code requests."
    },
    'ar': {
        'start': "👋 مرحبًا بكم في بوت ChatGPTPlus2FA!\n\nأقوم بإرسال رموز المصادقة تلقائيًا كل 5 دقائق إلى المجموعة.\n\nاستخدم /help لرؤية الأوامر المتاحة.",
        'help': "🤖 *مساعدة البوت*\n\nالأوامر المتاحة:\n\n/start - بدء التفاعل مع البوت\n/help - عرض رسالة المساعدة\n/settings - إعدادات المستخدم\n\nللمشرفين:\n/admin - لوحة التحكم",
        'settings': "⚙️ *إعداداتك*\n\nاللغة: العربية\nطلبات الرمز اليومية: {request_count}/{max_requests}",
        'new_code': "🔑 رمز مصادقة جديد\n\nاضغط على الزر أدناه لنسخ الرمز",
        'copy': "📋 نسخ الرمز",
        'code_copied': "✅ تم نسخ الرمز إلى الحافظة!",
        'admin_panel': "👑 *لوحة التحكم*\n\n- الحد الأقصى للطلبات لكل مستخدم: {max_requests}\n- إظهار الأكواد: {visibility}\n- المستخدمون المسموح لهم: {user_count}",
        'admin_only': "⚠️ هذا الأمر للمشرفين فقط!",
        'request_count': "🔄 لقد استخدمت {request_count} من أصل {max_requests} طلبات مسموحة اليوم.",
        'limit_reached': "⚠️ لقد وصلت إلى الحد الأقصى اليومي لطلبات الرموز ({max_requests})."
    }
}

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
    """توليد رمز المصادقة الثنائية"""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def get_expiry_time():
    """الحصول على وقت انتهاء صلاحية الرمز بتوقيت فلسطين"""
    expiry = get_palestine_time() + timedelta(minutes=10)
    return expiry.strftime('%Y-%m-%d %H:%M:%S')

def load_config():
    """تحميل إعدادات البوت"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {
            "max_requests_per_user": MAX_REQUESTS_PER_USER,
            "code_visibility": False,
            "allowed_users": []
        }

def save_config(config):
    """حفظ إعدادات البوت"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def can_user_request_code(user_id, max_requests):
    """التحقق مما إذا كان يمكن للمستخدم طلب رمز آخر"""
    try:
        with open(USER_LIMITS_FILE, 'r') as f:
            user_limits = json.load(f)
        
        today = get_palestine_time().strftime('%Y-%m-%d')
        
        if str(user_id) not in user_limits:
            return True
        
        if user_limits[str(user_id)]['date'] != today:
            return True
        
        return user_limits[str(user_id)]['count'] < max_requests
    except Exception as e:
        logger.error(f"Error checking user limits: {e}")
        return True

def update_user_request_count(user_id):
    """تحديث عدد طلبات المستخدم"""
    try:
        with open(USER_LIMITS_FILE, 'r+') as f:
            user_limits = json.load(f)
            today = get_palestine_time().strftime('%Y-%m-%d')
            
            if str(user_id) not in user_limits or user_limits[str(user_id)]['date'] != today:
                user_limits[str(user_id)] = {'date': today, 'count': 1}
            else:
                user_limits[str(user_id)]['count'] += 1
            
            f.seek(0)
            json.dump(user_limits, f, indent=2)
            f.truncate()
        
        return user_limits[str(user_id)]['count']
    except Exception as e:
        logger.error(f"Error updating user request count: {e}")
        return 1

def log_code_request(user, ip, device):
    """تسجيل طلب الرمز يدوياً"""
    try:
        request_count = update_user_request_count(user.id)
        
        log_entry = {
            'user_id': user.id,
            'user_name': user.full_name,
            'time': get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
            'ip': ip,
            'device': device,
            'request_count': request_count
        }
        
        with open(LOG_FILE, 'r+') as f:
            logs = json.load(f)
            logs.append(log_entry)
            f.seek(0)
            json.dump(logs, f, indent=2)
        
        return request_count
    except Exception as e:
        logger.error(f"Error logging code request: {e}")
        return 1

def is_user_allowed(user_id):
    """التحقق مما إذا كان المستخدم مسموح له"""
    try:
        config = load_config()
        return (user_id in config['allowed_users']) or (user_id == ADMIN_CHAT_ID)
    except Exception as e:
        logger.error(f"Error checking user permissions: {e}")
        return False

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مسؤولاً"""
    return user_id == ADMIN_CHAT_ID

def create_copy_button(lang='en'):
    """إنشاء زر النسخ"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code')]])

def create_settings_keyboard(lang='en'):
    """إنشاء لوحة مفاتيح الإعدادات"""
    keyboard = [
        [InlineKeyboardButton("🌐 Change Language", callback_data='change_language')],
        [InlineKeyboardButton("🔄 Request Code", callback_data='request_code')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_admin_keyboard(lang='en'):
    """إنشاء لوحة مفاتيح المسؤول"""
    keyboard = [
        [InlineKeyboardButton("👥 Manage Users", callback_data='manage_users')],
        [InlineKeyboardButton("🔙 Back", callback_data='back_to_main')]
    ]
    return InlineKeyboardMarkup(keyboard)

def send_auto_code(context: CallbackContext):
    """إرسال رمز المصادقة تلقائياً"""
    try:
        code = generate_2fa_code()
        
        message = MESSAGES['en']['new_code']  # اللغة الافتراضية للمجموعة
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            reply_markup=create_copy_button('en')
        )
        
        logger.info(f"تم إرسال الرمز تلقائياً في {get_palestine_time().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        logger.error(f"Error in send_auto_code: {e}")

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    try:
        user = update.effective_user
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        update.message.reply_text(
            MESSAGES[lang]['start'],
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help"""
    try:
        user = update.effective_user
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
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
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        config = load_config()
        
        with open(USER_LIMITS_FILE, 'r') as f:
            user_limits = json.load(f)
            today = get_palestine_time().strftime('%Y-%m-%d')
            request_count = user_limits.get(str(user.id), {}).get('count', 0) if user_limits.get(str(user.id), {}).get('date') == today else 0
        
        update.message.reply_text(
            MESSAGES[lang]['settings'].format(
                request_count=request_count,
                max_requests=config['max_requests_per_user']
            ),
            parse_mode='Markdown',
            reply_markup=create_settings_keyboard(lang)
        )
    except Exception as e:
        logger.error(f"Error in settings command: {e}")

def admin_command(update: Update, context: CallbackContext):
    """معالجة أمر /admin"""
    try:
        user = update.effective_user
        if not is_admin(user.id):
            lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
            update.message.reply_text(MESSAGES[lang]['admin_only'])
            return
        
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        config = load_config()
        
        visibility = "Enabled" if config['code_visibility'] else "Disabled"
        
        update.message.reply_text(
            MESSAGES[lang]['admin_panel'].format(
                max_requests=config['max_requests_per_user'],
                visibility=visibility,
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
        
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        if query.data == 'copy_code':
            code = generate_2fa_code()
            context.bot.send_message(
                chat_id=user.id,
                text=f"✅ {MESSAGES[lang]['code_copied']}\n\n`{code}`",
                parse_mode='Markdown'
            )
        
        elif query.data == 'request_code':
            config = load_config()
            if not can_user_request_code(user.id, config['max_requests_per_user']):
                query.edit_message_text(MESSAGES[lang]['limit_reached'].format(
                    max_requests=config['max_requests_per_user']))
                return
            
            ip = get_client_ip()
            device = get_user_device(query.message.effective_user._effective_user_agent)
            request_count = log_code_request(user, ip, device)
            
            code = generate_2fa_code()
            context.bot.send_message(
                chat_id=user.id,
                text=f"🔑 {MESSAGES[lang]['code_copied']}\n\n`{code}`\n\n{MESSAGES[lang]['request_count'].format(
                    request_count=request_count,
                    max_requests=config['max_requests_per_user'])}",
                parse_mode='Markdown'
            )
        
        elif query.data == 'change_language':
            # يمكن إضافة منطق تغيير اللغة هنا
            query.edit_message_text("Language change feature will be added soon.")
        
        elif query.data == 'manage_users' and is_admin(user.id):
            query.edit_message_text("User management feature will be added soon.")
        
        elif query.data == 'back_to_main' and is_admin(user.id):
            admin_command(update, context)
    except Exception as e:
        logger.error(f"Error in button click: {e}")

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    try:
        logger.warning(f'Update "{update}" caused error "{context.error}"')
    except Exception as e:
        logger.error(f'Error logging error: {e}')

def main():
    """الدالة الرئيسية"""
    try:
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        job_queue = updater.job_queue

        # جدولة إرسال الرموز كل 5 دقائق
        job_queue.run_repeating(send_auto_code, interval=300, first=0)

        # إضافة معالجات الأوامر
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("settings", settings_command))
        dp.add_handler(CommandHandler("admin", admin_command))
        
        # إضافة معالج الأزرار
        dp.add_handler(CallbackQueryHandler(button_click))
        
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

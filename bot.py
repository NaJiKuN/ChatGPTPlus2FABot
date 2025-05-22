#!/usr/bin/env python3
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
ADMIN_CHAT_ID = 792534650
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# مسارات الملفات المطلقة
HOME_DIR = os.path.expanduser("~")
BOT_DIR = os.path.join(HOME_DIR, "ChatGPTPlus2FABot")
os.makedirs(BOT_DIR, exist_ok=True)

LOG_FILE = os.path.join(BOT_DIR, "code_requests.log")
CONFIG_FILE = os.path.join(BOT_DIR, "bot_config.json")
USER_LIMITS_FILE = os.path.join(BOT_DIR, "user_limits.json")
MAX_REQUESTS_PER_USER = 5

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
        'start': "👋 Welcome to ChatGPTPlus2FA Bot!\n\nI automatically send 2FA codes every 5 minutes to the group.",
        'help': "🤖 *Bot Help*\n\nCommands:\n/start - Start bot\n/help - Show help\n/settings - User settings",
        'settings': "⚙️ *Your Settings*\n\nRequests today: {request_count}/{max_requests}",
        'new_code': "🔑 New Authentication Code\n\nClick below to copy",
        'copy': "📋 Copy Code",
        'code_copied': "✅ Code copied!\n\n`{code}`\nValid for 10 minutes.",
        'admin_panel': "👑 *Admin Panel*\n\nMax requests: {max_requests}\nAllowed users: {user_count}",
        'admin_only': "⚠️ Admins only!",
        'request_count': "🔄 Requests today: {request_count}/{max_requests}",
        'limit_reached': "⚠️ Daily limit reached ({max_requests})"
    },
    'ar': {
        'start': "👋 مرحبًا ببوت المصادقة!\n\nسأرسل رموز المصادقة كل 5 دقائق.",
        'help': "🤖 *مساعدة البوت*\n\nالأوامر:\n/start - بدء البوت\n/help - المساعدة\n/settings - الإعدادات",
        'settings': "⚙️ *إعداداتك*\n\nطلبات اليوم: {request_count}/{max_requests}",
        'new_code': "🔑 رمز مصادقة جديد\n\nاضغط لنسخ الرمز",
        'copy': "📋 نسخ الرمز",
        'code_copied': "✅ تم النسخ!\n\n`{code}`\nصالح لمدة 10 دقائق.",
        'admin_panel': "👑 *لوحة التحكم*\n\nالحد الأقصى: {max_requests}\nالمستخدمون: {user_count}",
        'admin_only': "⚠️ للمشرفين فقط!",
        'request_count': "🔄 طلبات اليوم: {request_count}/{max_requests}",
        'limit_reached': "⚠️ وصلت للحد اليومي ({max_requests})"
    }
}

def get_client_ip():
    """الحصول على IP السيرفر"""
    try:
        return requests.get('https://api.ipify.org').text
    except:
        return "Unknown"

def get_user_device(user_agent):
    """تحليل معلومات الجهاز"""
    try:
        ua = parse(user_agent)
        return f"{ua.device.family} {ua.os.family} {ua.browser.family}"
    except:
        return "Unknown device"

def get_palestine_time():
    """الوقت بتوقيت فلسطين"""
    return datetime.now(PALESTINE_TZ)

def generate_2fa_code():
    """توليد رمز المصادقة"""
    return pyotp.TOTP(TOTP_SECRET).now()

def get_expiry_time():
    """وقت انتهاء الصلاحية"""
    return (get_palestine_time() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

def load_config():
    """تحميل الإعدادات"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "max_requests_per_user": MAX_REQUESTS_PER_USER,
            "code_visibility": False,
            "allowed_users": []
        }

def save_config(config):
    """حفظ الإعدادات"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def can_user_request_code(user_id, max_requests):
    """التحقق من إمكانية طلب رمز"""
    try:
        with open(USER_LIMITS_FILE, 'r') as f:
            user_limits = json.load(f)
        
        today = get_palestine_time().strftime('%Y-%m-%d')
        
        if str(user_id) not in user_limits:
            return True
        
        if user_limits[str(user_id)]['date'] != today:
            return True
        
        return user_limits[str(user_id)]['count'] < max_requests
    except:
        return True

def update_user_request_count(user_id):
    """تحديث عدد الطلبات"""
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
        
        return user_limits[str(user_id)]['count']
    except:
        return 1

def is_admin(user_id):
    """التحقق إذا كان مسؤولاً"""
    return user_id == ADMIN_CHAT_ID

def create_copy_button(lang='en'):
    """زر النسخ"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code')]])

def send_auto_code(context: CallbackContext):
    """إرسال تلقائي للرمز"""
    try:
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=MESSAGES['en']['new_code'],
            reply_markup=create_copy_button('en')
        )
        logger.info("Sent auto code at %s", get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'))
    except Exception as e:
        logger.error("Auto code error: %s", str(e))

def start(update: Update, context: CallbackContext):
    """معالجة /start"""
    user = update.effective_user
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    update.message.reply_text(MESSAGES[lang]['start'])

def help_command(update: Update, context: CallbackContext):
    """معالجة /help"""
    user = update.effective_user
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    update.message.reply_text(MESSAGES[lang]['help'], parse_mode='Markdown')

def settings_command(update: Update, context: CallbackContext):
    """معالجة /settings"""
    user = update.effective_user
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    config = load_config()
    
    try:
        with open(USER_LIMITS_FILE, 'r') as f:
            user_limits = json.load(f)
            today = get_palestine_time().strftime('%Y-%m-%d')
            count = user_limits.get(str(user.id), {}).get('count', 0) if user_limits.get(str(user.id), {}).get('date') == today else 0
    except:
        count = 0
    
    update.message.reply_text(
        MESSAGES[lang]['settings'].format(
            request_count=count,
            max_requests=config['max_requests_per_user']
        ),
        parse_mode='Markdown'
    )

def admin_command(update: Update, context: CallbackContext):
    """معالجة /admin"""
    user = update.effective_user
    if not is_admin(user.id):
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        update.message.reply_text(MESSAGES[lang]['admin_only'])
        return
    
    config = load_config()
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    
    update.message.reply_text(
        MESSAGES[lang]['admin_panel'].format(
            max_requests=config['max_requests_per_user'],
            user_count=len(config['allowed_users'])
        ),
        parse_mode='Markdown'
    )

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
    query = update.callback_query
    query.answer()
    user = query.from_user
    lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
    
    if query.data == 'copy_code':
        code = generate_2fa_code()
        context.bot.send_message(
            chat_id=user.id,
            text=MESSAGES[lang]['code_copied'].format(code=code),
            parse_mode='Markdown'
        )

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    """الدالة الرئيسية"""
    try:
        logger.info("Starting bot...")
        
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
        dp.add_handler(CallbackQueryHandler(button_click))
        
        dp.add_error_handler(error)

        # بدء البوت
        updater.start_polling()
        logger.info("Bot is now running!")
        updater.idle()
        
    except Exception as e:
        logger.error("Fatal error: %s", str(e), exc_info=True)
        raise

if __name__ == '__main__':
    main()

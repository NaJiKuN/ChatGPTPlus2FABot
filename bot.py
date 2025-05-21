import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
import pyotp
from datetime import datetime, timedelta
import pytz
import json
import os

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
LOG_FILE = "code_requests.log"

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# دعم اللغات
MESSAGES = {
    'en': {
        'new_code': "🔑 New Authentication Code Received\n\nYou have received a new authentication code.\n\n`Code: {code}`\n\nThis code is valid until {expiry_time} (UTC).",
        'manual_code': "🔄 Manual Code Request\n\nYour requested authentication code:\n\n`Code: {code}`\n\nValid until: {expiry_time} (UTC)",
        'copy': "📋 Copy Code",
        'request': "🔄 Request New Code",
        'help': "🤖 *ChatGPTPlus2FA Bot Help*\n\n- I automatically send 2FA codes every 10 minutes\n- Click 'Request New Code' to get one immediately\n- Codes are valid for 10 minutes",
        'welcome': "👋 Welcome to ChatGPTPlus2FA Bot! I'll send you 2FA codes for authentication.",
        'language': "🌐 Language",
        'code_copied': "✅ Code copied to clipboard!",
        'admin_log': "👤 User {user_name} (ID: {user_id}) requested a manual code at {time} (UTC)"
    },
    'ar': {
        'new_code': "🔑 تم استلام رمز مصادقة جديد\n\nلقد تلقيت رمز مصادقة جديد.\n\n`الرمز: {code}`\n\nهذا الرمز صالح حتى {expiry_time} (التوقيت العالمي).",
        'manual_code': "🔄 طلب رمز يدوي\n\nرمز المصادقة الذي طلبته:\n\n`الرمز: {code}`\n\nصالح حتى: {expiry_time} (التوقيت العالمي)",
        'copy': "📋 نسخ الرمز",
        'request': "🔄 طلب رمز جديد",
        'help': "🤖 *مساعدة بوت ChatGPTPlus2FA*\n\n- أقوم بإرسال رموز المصادقة كل 10 دقائق تلقائياً\n- انقر على 'طلب رمز جديد' للحصول على رمز فوراً\n- الرموز صالحة لمدة 10 دقائق",
        'welcome': "👋 مرحباً بكم في بوت ChatGPTPlus2FA! سأرسل لكم رموز المصادقة الثنائية.",
        'language': "🌐 اللغة",
        'code_copied': "✅ تم نسخ الرمز إلى الحافظة!",
        'admin_log': "👤 المستخدم {user_name} (ID: {user_id}) طلب رمزاً يدوياً في {time} (التوقيت العالمي)"
    }
}

# إنشاء ملف السجل إذا لم يكن موجوداً
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        json.dump([], f)

def generate_2fa_code():
    """توليد رمز المصادقة الثنائية"""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def get_expiry_time():
    """الحصول على وقت انتهاء صلاحية الرمز"""
    now = datetime.now(pytz.utc)
    expiry = now.replace(second=0, microsecond=0) + timedelta(minutes=10)
    return expiry.strftime('%Y-%m-%d %H:%M:%S')

def log_code_request(user):
    """تسجيل طلب الرمز يدوياً"""
    with open(LOG_FILE, 'r+') as f:
        logs = json.load(f)
        logs.append({
            'user_id': user.id,
            'user_name': user.full_name,
            'time': datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        })
        f.seek(0)
        json.dump(logs, f, indent=2)

def create_keyboard(lang='en'):
    """إنشاء لوحة مفاتيح مع أزرار النسخ والطلب"""
    keyboard = [
        [
            InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code'),
            InlineKeyboardButton(MESSAGES[lang]['request'], callback_data='request_code')
        ],
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

def send_2fa_code(context: CallbackContext, manual_request=False, lang='en', user=None):
    """إرسال رمز المصادقة إلى المجموعة"""
    code = generate_2fa_code()
    expiry_time = get_expiry_time()
    
    if manual_request and user:
        log_code_request(user)
        admin_msg = MESSAGES['en']['admin_log'].format(
            user_name=user.full_name,
            user_id=user.id,
            time=datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        )
        context.bot.send_message(chat_id=GROUP_CHAT_ID, text=admin_msg)
    
    if manual_request:
        message = MESSAGES[lang]['manual_code'].format(code=code, expiry_time=expiry_time)
    else:
        message = MESSAGES[lang]['new_code'].format(code=code, expiry_time=expiry_time)
    
    # إرسال الرسالة مع زر النسخ الفعلي (using Telegram WebApp)
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=MESSAGES[lang]['copy'],
                callback_data=f'copy_{code}'
            )
        ]])
    )

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    user = update.effective_user
    user_lang = user.language_code or 'en'
    lang = 'ar' if user_lang.startswith('ar') else 'en'
    
    update.message.reply_text(
        MESSAGES[lang]['welcome'],
        parse_mode='Markdown',
        reply_markup=create_keyboard(lang)
    )

def help_command(update: Update, context: CallbackContext):
    """معالجة أمر /help"""
    user_lang = update.effective_user.language_code or 'en'
    lang = 'ar' if user_lang.startswith('ar') else 'en'
    
    update.message.reply_text(
        MESSAGES[lang]['help'],
        parse_mode='Markdown'
    )

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
    query = update.callback_query
    query.answer()
    
    user = query.from_user
    user_lang = user.language_code or 'en'
    lang = 'ar' if user_lang.startswith('ar') else 'en'
    
    if query.data.startswith('copy_'):
        code = query.data.split('_')[1]
        # في واجهة Telegram Web، هذا سيؤدي إلى نسخ الرمز تلقائياً
        query.edit_message_text(
            text=query.message.text + f"\n\n{MESSAGES[lang]['code_copied']}",
            parse_mode='Markdown'
        )
    elif query.data == 'request_code':
        send_2fa_code(context, manual_request=True, lang=lang, user=user)
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
            reply_markup=create_keyboard(new_lang)
        )

def error(update: Update, context: CallbackContext):
    """تسجيل الأخطاء"""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    """الدالة الرئيسية"""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # إضافة معالجات الأوامر
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CallbackQueryHandler(button_click))
    
    # تسجيل معالج الأخطاء
    dp.add_error_handler(error)

    # بدء البوت
    updater.start_polling()

    # جدولة إرسال الرمز كل 10 دقائق
    jq = updater.job_queue
    jq.run_repeating(
        lambda ctx: send_2fa_code(ctx, lang='en'),
        interval=600,
        first=0
    )

    # تشغيل البوت حتى الضغط على Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
import pyotp
from datetime import datetime
import pytz

# تكوين البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# دعم اللغات
MESSAGES = {
    'en': {
        'new_code': "🔑 New Authentication Code Received\n\nYou have received a new authentication code.\n\n`Code: {code}`\n\nThis code is valid for the next 10 minutes. Please use it promptly.",
        'manual_code': "🔄 Manual Code Request\n\nYour requested authentication code:\n\n`Code: {code}`\n\nValid until: {expiry_time}",
        'copy': "📋 Copy Code",
        'request': "🔄 Request New Code",
        'help': "🤖 *ChatGPTPlus2FA Bot Help*\n\n- I automatically send 2FA codes every 10 minutes\n- Click 'Request New Code' to get one immediately\n- Codes are valid for 10 minutes",
        'welcome': "👋 Welcome to ChatGPTPlus2FA Bot! I'll send you 2FA codes for authentication."
    },
    'ar': {
        'new_code': "🔑 تم استلام رمز مصادقة جديد\n\nلقد تلقيت رمز مصادقة جديد.\n\n`الرمز: {code}`\n\nهذا الرمز صالح للاستخدام خلال الـ 10 دقائق القادمة. يرجى استخدامه فوراً.",
        'manual_code': "🔄 طلب رمز يدوي\n\nرمز المصادقة الذي طلبته:\n\n`الرمز: {code}`\n\nصالح حتى: {expiry_time}",
        'copy': "📋 نسخ الرمز",
        'request': "🔄 طلب رمز جديد",
        'help': "🤖 *مساعدة بوت ChatGPTPlus2FA*\n\n- أقوم بإرسال رموز المصادقة كل 10 دقائق تلقائياً\n- انقر على 'طلب رمز جديد' للحصول على رمز فوراً\n- الرموز صالحة لمدة 10 دقائق",
        'welcome': "👋 مرحباً بكم في بوت ChatGPTPlus2FA! سأرسل لكم رموز المصادقة الثنائية."
    }
}

def generate_2fa_code():
    """توليد رمز المصادقة الثنائية"""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.now()

def get_expiry_time():
    """الحصول على وقت انتهاء صلاحية الرمز"""
    now = datetime.now(pytz.utc)
    expiry = now.replace(second=0, microsecond=0) + timedelta(minutes=10)
    return expiry.strftime('%H:%M:%S')

def create_keyboard(lang='en'):
    """إنشاء لوحة مفاتيح مع أزرار النسخ والطلب"""
    keyboard = [
        [InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code')],
        [InlineKeyboardButton(MESSAGES[lang]['request'], callback_data='request_code')]
    ]
    return InlineKeyboardMarkup(keyboard)

def send_2fa_code(context: CallbackContext, manual_request=False, lang='en'):
    """إرسال رمز المصادقة إلى المجموعة"""
    code = generate_2fa_code()
    expiry_time = get_expiry_time()
    
    if manual_request:
        message = MESSAGES[lang]['manual_code'].format(code=code, expiry_time=expiry_time)
    else:
        message = MESSAGES[lang]['new_code'].format(code=code)
    
    context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=message,
        parse_mode='Markdown',
        reply_markup=create_keyboard(lang)
    )

def start(update: Update, context: CallbackContext):
    """معالجة أمر /start"""
    # تحديد اللغة بناءً على لغة المستخدم
    user_lang = update.effective_user.language_code or 'en'
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
    
    user_lang = query.from_user.language_code or 'en'
    lang = 'ar' if user_lang.startswith('ar') else 'en'
    
    if query.data == 'copy_code':
        # يمكن إضافة رد بأن الرمز جاهز للنسخ
        query.edit_message_text(
            text=query.message.text + "\n\n📋 يمكنك الآن نسخ الرمز من الأعلى",
            parse_mode='Markdown'
        )
    elif query.data == 'request_code':
        send_2fa_code(context, manual_request=True, lang=lang)

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
        lambda ctx: send_2fa_code(ctx, lang='en'),  # اللغة الافتراضية للإرسال التلقائي
        interval=600,
        first=0
    )

    # تشغيل البوت حتى الضغط على Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()

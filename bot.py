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
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
LOG_FILE = "code_requests.log"
USER_LIMITS_FILE = "user_limits.json"
MAX_REQUESTS_PER_USER = 5  # الحد الأقصى لطلبات الرموز لكل مستخدم

# تهيئة المنطقة الزمنية لفلسطين
PALESTINE_TZ = pytz.timezone('Asia/Gaza')

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تهيئة ملفات البيانات
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f:
        json.dump([], f)

if not os.path.exists(USER_LIMITS_FILE):
    with open(USER_LIMITS_FILE, 'w') as f:
        json.dump({}, f)

# دعم اللغات
MESSAGES = {
    'en': {
        'new_code': "🔑 New Authentication Code Received\n\nYou have received a new authentication code.\n\n`Code: {code}`\n\nThis code is valid until {expiry_time} (Palestine Time).",
        'manual_code': "🔄 Manual Code Request\n\nYour requested authentication code:\n\n`Code: {code}`\n\nValid until: {expiry_time} (Palestine Time)",
        'copy': "📋 Copy Code",
        'request': "🔄 Request New Code",
        'help': "🤖 *ChatGPTPlus2FA Bot Help*\n\n- I automatically send 2FA codes every 10 minutes\n- Click 'Request New Code' to get one immediately\n- Codes are valid for 10 minutes\n- Each user can request up to {max_requests} codes per day",
        'welcome': "👋 Welcome to ChatGPTPlus2FA Bot! I'll send you 2FA codes for authentication.",
        'language': "🌐 Language",
        'code_copied': "✅ Code copied to clipboard!",
        'admin_log': "👤 User {user_name} (ID: {user_id}) requested a manual code at {time} (Palestine Time)\n📱 Device: {device}\n🌐 IP: {ip}\n🔢 Total requests today: {request_count}/{max_requests}",
        'limit_reached': "⚠️ You have reached your daily limit of {max_requests} code requests. Please wait until tomorrow.",
        'request_count': "🔄 You have used {request_count} out of {max_requests} allowed requests today."
    },
    'ar': {
        'new_code': "🔑 تم استلام رمز مصادقة جديد\n\nلقد تلقيت رمز مصادقة جديد.\n\n`الرمز: {code}`\n\nهذا الرمز صالح حتى {expiry_time} (توقيت فلسطين).",
        'manual_code': "🔄 طلب رمز يدوي\n\nرمز المصادقة الذي طلبته:\n\n`الرمز: {code}`\n\nصالح حتى: {expiry_time} (توقيت فلسطين)",
        'copy': "📋 نسخ الرمز",
        'request': "🔄 طلب رمز جديد",
        'help': "🤖 *مساعدة بوت ChatGPTPlus2FA*\n\n- أقوم بإرسال رموز المصادقة كل 10 دقائق تلقائياً\n- انقر على 'طلب رمز جديد' للحصول على رمز فوراً\n- الرموز صالحة لمدة 10 دقائق\n- يمكن لكل مستخدم طلب حتى {max_requests} رموز في اليوم",
        'welcome': "👋 مرحباً بكم في بوت ChatGPTPlus2FA! سأرسل لكم رموز المصادقة الثنائية.",
        'language': "🌐 اللغة",
        'code_copied': "✅ تم نسخ الرمز إلى الحافظة!",
        'admin_log': "👤 المستخدم {user_name} (ID: {user_id}) طلب رمزاً يدوياً في {time} (توقيت فلسطين)\n📱 الجهاز: {device}\n🌐 IP: {ip}\n🔢 إجمالي الطلبات اليوم: {request_count}/{max_requests}",
        'limit_reached': "⚠️ لقد وصلت إلى الحد الأقصى اليومي لطلبات الرموز ({max_requests}). يرجى الانتظار حتى الغد.",
        'request_count': "🔄 لقد استخدمت {request_count} من أصل {max_requests} طلبات مسموحة اليوم."
    }
}

def get_client_ip():
    """الحصول على IP السيرفر (لأغراض التوضيح، في الإنتاج تحتاج لتنفيذ مختلف)"""
    try:
        return requests.get('https://api.ipify.org').text
    except:
        return "Unknown"

def get_user_device(user_agent):
    """تحليل معلومات جهاز المستخدم"""
    try:
        ua = parse(user_agent)
        return f"{ua.device.family} {ua.os.family} {ua.browser.family}"
    except:
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

def can_user_request_code(user_id):
    """التحقق مما إذا كان يمكن للمستخدم طلب رمز آخر"""
    with open(USER_LIMITS_FILE, 'r') as f:
        user_limits = json.load(f)
    
    today = get_palestine_time().strftime('%Y-%m-%d')
    
    if str(user_id) not in user_limits:
        return True
    
    if user_limits[str(user_id)]['date'] != today:
        return True
    
    return user_limits[str(user_id)]['count'] < MAX_REQUESTS_PER_USER

def update_user_request_count(user_id):
    """تحديث عدد طلبات المستخدم"""
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

def log_code_request(user, ip, device):
    """تسجيل طلب الرمز يدوياً"""
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

def send_2fa_code(context: CallbackContext, manual_request=False, lang='en', user=None, ip=None, device=None):
    """إرسال رمز المصادقة إلى المجموعة"""
    if manual_request and user:
        if not can_user_request_code(user.id):
            context.bot.send_message(
                chat_id=user.id,
                text=MESSAGES[lang]['limit_reached'].format(max_requests=MAX_REQUESTS_PER_USER)
            )
            return
        
        request_count = log_code_request(user, ip, device)
        admin_msg = MESSAGES['en']['admin_log'].format(
            user_name=user.full_name,
            user_id=user.id,
            time=get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
            device=device,
            ip=ip,
            request_count=request_count,
            max_requests=MAX_REQUESTS_PER_USER
        )
        context.bot.send_message(chat_id=GROUP_CHAT_ID, text=admin_msg)
        
        # إرسال إشعار بعدد الطلبات المتبقية للمستخدم
        context.bot.send_message(
            chat_id=user.id,
            text=MESSAGES[lang]['request_count'].format(
                request_count=request_count,
                max_requests=MAX_REQUESTS_PER_USER
            )
        )
    
    code = generate_2fa_code()
    expiry_time = get_expiry_time()
    
    if manual_request:
        message = MESSAGES[lang]['manual_code'].format(code=code, expiry_time=expiry_time)
    else:
        message = MESSAGES[lang]['new_code'].format(code=code, expiry_time=expiry_time)
    
    # إرسال الرسالة مع زر النسخ الفعلي
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
        MESSAGES[lang]['help'].format(max_requests=MAX_REQUESTS_PER_USER),
        parse_mode='Markdown'
    )

def button_click(update: Update, context: CallbackContext):
    """معالجة النقر على الأزرار"""
    query = update.callback_query
    query.answer()
    
    user = query.from_user
    user_lang = user.language_code or 'en'
    lang = 'ar' if user_lang.startswith('ar') else 'en'
    
    # الحصول على معلومات المستخدم للأمان
    ip = get_client_ip()
    device = get_user_device(query.message._effective_user_agent())
    
    if query.data.startswith('copy_'):
        code = query.data.split('_')[1]
        query.edit_message_text(
            text=query.message.text + f"\n\n{MESSAGES[lang]['code_copied']}",
            parse_mode='Markdown'
        )
    elif query.data == 'request_code':
        send_2fa_code(
            context,
            manual_request=True,
            lang=lang,
            user=user,
            ip=ip,
            device=device
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

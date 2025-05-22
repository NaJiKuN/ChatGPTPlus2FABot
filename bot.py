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
ADMIN_CHAT_ID = 792534650  # Chat ID الخاص بك كلوحة تحكم
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
            "code_visibility": False,  # تم تعطيل إظهار الأكواد افتراضياً
            "allowed_users": [],
            "admins": [ADMIN_CHAT_ID]  # قائمة بالمشرفين
        }, f)

if not os.path.exists(USER_LIMITS_FILE):
    with open(USER_LIMITS_FILE, 'w') as f:
        json.dump({}, f)

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

def get_client_ip():
    """الحصول على IP السيرفر (للاستخدام الداخلي فقط)"""
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
            "allowed_users": [],
            "admins": [ADMIN_CHAT_ID]
        }

def save_config(config):
    """حفظ إعدادات البوت"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مشرف"""
    config = load_config()
    return user_id in config.get('admins', [ADMIN_CHAT_ID])

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

def log_code_request(user, device):
    """تسجيل طلب الرمز يدوياً (بدون IP)"""
    try:
        request_count = update_user_request_count(user.id)
        
        log_entry = {
            'user_id': user.id,
            'user_name': user.full_name,
            'time': get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
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
    """التحقق مما إذا كان المستخدم مسموح له بطلب الأكواد"""
    try:
        config = load_config()
        return (user_id in config['allowed_users']) or (user_id == ADMIN_CHAT_ID) or is_admin(user_id)
    except Exception as e:
        logger.error(f"Error checking user permissions: {e}")
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
        code = generate_2fa_code()
        expiry_time = get_expiry_time()
        device = "Unknown"
        
        try:
            updates = context.bot.get_updates(limit=1)
            if updates:
                device = get_user_device(updates[-1].effective_user._effective_user_agent)
        except Exception as e:
            logger.error(f"Error getting device info: {e}")
        
        # إرسال الرمز للمستخدم
        context.bot.send_message(
            chat_id=user.id,
            text=MESSAGES[lang]['private_code'].format(code=code, expiry_time=expiry_time),
            parse_mode='Markdown'
        )
        
        # تسجيل الطلب (للمشرفين فقط)
        if is_admin(user.id):
            ip = get_client_ip()
            admin_msg = MESSAGES['en']['admin_log'].format(
                user_name=user.full_name,
                user_id=user.id,
                time=get_palestine_time().strftime('%Y-%m-%d %H:%M:%S'),
                device=device,
                request_count=log_code_request(user, device),
                max_requests=load_config()['max_requests_per_user']
            )
            if ip != "Unknown":
                admin_msg += f"\n🌐 IP: {ip}"
            
            context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg)
        else:
            log_code_request(user, device)
            
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
        config = load_config()
        
        update.message.reply_text(
            MESSAGES[lang]['help'].format(max_requests=config['max_requests_per_user']),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in help command: {e}")

def show_admin_panel(update: Update, context: CallbackContext):
    """عرض لوحة التحكم الإدارية"""
    try:
        user = update.effective_user
        if not is_admin(user.id):
            return
        
        config = load_config()
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        keyboard = [
            [InlineKeyboardButton(MESSAGES[lang]['change_max_requests'], callback_data='change_max')],
            [InlineKeyboardButton(MESSAGES[lang]['manage_users'], callback_data='manage_users')]
        ]
        
        update.message.reply_text(
            MESSAGES[lang]['admin_panel'].format(
                max_requests=config['max_requests_per_user'],
                user_count=len(config['allowed_users'])
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error showing admin panel: {e}")

def handle_admin_callback(update: Update, context: CallbackContext):
    """معالجة أحداث لوحة التحكم"""
    try:
        query = update.callback_query
        query.answer()
        user = query.from_user
        
        if not is_admin(user.id):
            return
        
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        config = load_config()
        
        if query.data == 'change_max':
            query.edit_message_text(MESSAGES[lang]['enter_new_max'])
            context.user_data['admin_state'] = 'WAITING_FOR_MAX'
        
        elif query.data == 'manage_users':
            keyboard = [
                [InlineKeyboardButton(MESSAGES[lang]['add_user'], callback_data='add_user')],
                [InlineKeyboardButton(MESSAGES[lang]['remove_user'], callback_data='remove_user')],
                [InlineKeyboardButton("🔙 Back", callback_data='back_to_panel')]
            ]
            query.edit_message_text(
                "👥 User Management",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data == 'add_user':
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_state'] = 'WAITING_FOR_USER_ADD'
        
        elif query.data == 'remove_user':
            query.edit_message_text(MESSAGES[lang]['enter_user_id'])
            context.user_data['admin_state'] = 'WAITING_FOR_USER_REMOVE'
        
        elif query.data == 'back_to_panel':
            show_admin_panel(update, context)
    except Exception as e:
        logger.error(f"Error in admin callback: {e}")

def handle_admin_input(update: Update, context: CallbackContext):
    """معالجة إدخالات لوحة التحكم"""
    try:
        user = update.effective_user
        if not is_admin(user.id):
            return
        
        text = update.message.text
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        config = load_config()
        
        if context.user_data.get('admin_state') == 'WAITING_FOR_MAX':
            try:
                new_max = int(text)
                if 1 <= new_max <= 20:
                    config['max_requests_per_user'] = new_max
                    save_config(config)
                    update.message.reply_text(
                        MESSAGES[lang]['max_updated'].format(max_requests=new_max)
                    )
                    show_admin_panel(update, context)
                    context.user_data['admin_state'] = None
                else:
                    update.message.reply_text(MESSAGES[lang]['invalid_max'])
            except ValueError:
                update.message.reply_text(MESSAGES[lang]['invalid_max'])
        
        elif context.user_data.get('admin_state') == 'WAITING_FOR_USER_ADD':
            try:
                user_id = int(text)
                if user_id not in config['allowed_users']:
                    config['allowed_users'].append(user_id)
                    save_config(config)
                    update.message.reply_text(
                        MESSAGES[lang]['user_added'].format(user_id=user_id))
                else:
                    update.message.reply_text(MESSAGES[lang]['user_not_found'])
                show_admin_panel(update, context)
                context.user_data['admin_state'] = None
            except ValueError:
                update.message.reply_text("Invalid user ID!")
        
        elif context.user_data.get('admin_state') == 'WAITING_FOR_USER_REMOVE':
            try:
                user_id = int(text)
                if user_id in config['allowed_users']:
                    config['allowed_users'].remove(user_id)
                    save_config(config)
                    update.message.reply_text(
                        MESSAGES[lang]['user_removed'].format(user_id=user_id))
                else:
                    update.message.reply_text(MESSAGES[lang]['user_not_found'])
                show_admin_panel(update, context)
                context.user_data['admin_state'] = None
            except ValueError:
                update.message.reply_text("Invalid user ID!")
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
            config = load_config()
            
            if not is_user_allowed(user.id):
                query.edit_message_text(text=MESSAGES[lang]['user_not_found'])
                return
                
            if not can_user_request_code(user.id, config['max_requests_per_user']):
                query.edit_message_text(
                    text=MESSAGES[lang]['limit_reached'].format(max_requests=config['max_requests_per_user'])
                )
                return
            
            send_private_code(context, user, lang)
            request_count = log_code_request(user, "Unknown")
            
            query.edit_message_text(
                text=MESSAGES[lang]['manual_code'] + "\n\n" + 
                MESSAGES[lang]['request_count'].format(
                    request_count=request_count,
                    max_requests=config['max_requests_per_user']
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
    except Exception as e:
        print(f'Error logging error: {e}')

def main():
    """الدالة الرئيسية"""
    try:
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher

        # إضافة معالجات الأوامر
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("help", help_command))
        dp.add_handler(CommandHandler("admin", show_admin_panel))
        dp.add_handler(CallbackQueryHandler(button_click))
        dp.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(change_max|manage_users|add_user|remove_user|back_to_panel)$'))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
        
        # تسجيل معالج الأخطاء
        dp.add_error_handler(error)

        # بدء البوت بدون إرسال تلقائي للرموز
        updater.start_polling()
        logger.info("Bot started and polling...")
        updater.idle()
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == '__main__':
    main()

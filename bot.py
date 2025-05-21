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
            "code_visibility": True,
            "allowed_users": []
        }, f)

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
        'request_count': "🔄 You have used {request_count} out of {max_requests} allowed requests today.",
        'admin_panel': "👑 *Admin Panel*\n\n- Max requests per user: {max_requests}\n- Code visibility: {visibility}\n- Allowed users: {user_count}",
        'visibility_on': "ON ✅",
        'visibility_off': "OFF ❌",
        'change_max_requests': "✏️ Change max requests",
        'toggle_visibility': "👁️ Toggle code visibility",
        'manage_users': "👥 Manage allowed users",
        'enter_new_max': "Please enter the new maximum requests per user (1-20):",
        'invalid_max': "Invalid input! Please enter a number between 1 and 20.",
        'max_updated': "✅ Max requests updated to {max_requests} per user.",
        'visibility_updated': "✅ Code visibility updated to {status}.",
        'add_user': "➕ Add user",
        'remove_user': "➖ Remove user",
        'enter_user_id': "Please enter the user ID to add/remove:",
        'user_added': "✅ User {user_id} added to allowed list.",
        'user_removed': "✅ User {user_id} removed from allowed list.",
        'user_not_found': "⚠️ User not found in the allowed list."
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
        'request_count': "🔄 لقد استخدمت {request_count} من أصل {max_requests} طلبات مسموحة اليوم.",
        'admin_panel': "👑 *لوحة التحكم*\n\n- الحد الأقصى للطلبات لكل مستخدم: {max_requests}\n- إظهار الأكواد: {visibility}\n- المستخدمون المسموح لهم: {user_count}",
        'visibility_on': "مفعل ✅",
        'visibility_off': "معطل ❌",
        'change_max_requests': "✏️ تغيير الحد الأقصى للطلبات",
        'toggle_visibility': "👁️ تبديل إظهار الأكواد",
        'manage_users': "👥 إدارة المستخدمين المسموح لهم",
        'enter_new_max': "الرجاء إدخال الحد الأقصى الجديد للطلبات لكل مستخدم (1-20):",
        'invalid_max': "إدخال غير صحيح! الرجاء إدخال رقم بين 1 و 20.",
        'max_updated': "✅ تم تحديث الحد الأقصى للطلبات إلى {max_requests} لكل مستخدم.",
        'visibility_updated': "✅ تم تحديث إظهار الأكواد إلى {status}.",
        'add_user': "➕ إضافة مستخدم",
        'remove_user': "➖ إزالة مستخدم",
        'enter_user_id': "الرجاء إدخال معرف المستخدم للإضافة/الإزالة:",
        'user_added': "✅ تمت إضافة المستخدم {user_id} إلى القائمة المسموح بها.",
        'user_removed': "✅ تمت إزالة المستخدم {user_id} من القائمة المسموح بها.",
        'user_not_found': "⚠️ المستخدم غير موجود في القائمة المسموح بها."
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
            "code_visibility": True,
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
    """التحقق مما إذا كان المستخدم مسموح له برؤية الأكواد"""
    try:
        config = load_config()
        return config['code_visibility'] or (user_id in config['allowed_users']) or (user_id == ADMIN_CHAT_ID)
    except Exception as e:
        logger.error(f"Error checking user permissions: {e}")
        return True

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
    try:
        ip = get_client_ip()
        device = "Unknown"
        
        # الحصول على معلومات الجهاز بطريقة أكثر أماناً
        try:
            updates = context.bot.get_updates(limit=1)
            if updates:
                device = get_user_device(updates[-1].effective_user._effective_user_agent)
        except Exception as e:
            logger.error(f"Error getting device info: {e}")
        
        config = load_config()
        
        if manual_request and user:
            if not can_user_request_code(user.id, config['max_requests_per_user']):
                context.bot.send_message(
                    chat_id=user.id,
                    text=MESSAGES[lang]['limit_reached'].format(max_requests=config['max_requests_per_user'])
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
                max_requests=config['max_requests_per_user']
            )
            context.bot.send_message(chat_id=GROUP_CHAT_ID, text=admin_msg)
            
            context.bot.send_message(
                chat_id=user.id,
                text=MESSAGES[lang]['request_count'].format(
                    request_count=request_count,
                    max_requests=config['max_requests_per_user']
                )
            )
        
        code = generate_2fa_code()
        expiry_time = get_expiry_time()
        
        if manual_request:
            message = MESSAGES[lang]['manual_code'].format(code=code, expiry_time=expiry_time)
        else:
            message = MESSAGES[lang]['new_code'].format(code=code, expiry_time=expiry_time)
        
        # إرسال الرسالة مع التحكم في الرؤية
        if is_user_allowed(user.id if user else None):
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    text=MESSAGES[lang]['copy'],
                    callback_data=f'copy_{code}'
                )
            ]])
        else:
            message = "🔒 You need permission to view authentication codes."
            reply_markup = None
        
        context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in send_2fa_code: {e}")
        if user:
            context.bot.send_message(
                chat_id=user.id,
                text="⚠️ An error occurred while processing your request. Please try again later."
            )

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
        if user.id != ADMIN_CHAT_ID:
            return
        
        config = load_config()
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        
        visibility = MESSAGES[lang]['visibility_on'] if config['code_visibility'] else MESSAGES[lang]['visibility_off']
        
        keyboard = [
            [InlineKeyboardButton(MESSAGES[lang]['change_max_requests'], callback_data='change_max')],
            [InlineKeyboardButton(MESSAGES[lang]['toggle_visibility'], callback_data='toggle_visibility')],
            [InlineKeyboardButton(MESSAGES[lang]['manage_users'], callback_data='manage_users')]
        ]
        
        update.message.reply_text(
            MESSAGES[lang]['admin_panel'].format(
                max_requests=config['max_requests_per_user'],
                visibility=visibility,
                user_count=len(config['allowed_users'])
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
    except Exception as e:
        logger.error(f"Error showing admin panel: {e}")

def handle_admin_callback(update: Update, context: CallbackContext):
    """معالجة أحداث لوحة التحكم"""
    try:
        query = update.callback_query
        query.answer()
        user = query.from_user
        
        if user.id != ADMIN_CHAT_ID:
            return
        
        lang = 'ar' if user.language_code and user.language_code.startswith('ar') else 'en'
        config = load_config()
        
        if query.data == 'change_max':
            query.edit_message_text(MESSAGES[lang]['enter_new_max'])
            context.user_data['admin_state'] = 'WAITING_FOR_MAX'
        
        elif query.data == 'toggle_visibility':
            config['code_visibility'] = not config['code_visibility']
            save_config(config)
            
            status = MESSAGES[lang]['visibility_on'] if config['code_visibility'] else MESSAGES[lang]['visibility_off']
            query.edit_message_text(
                MESSAGES[lang]['visibility_updated'].format(status=status)
            )
            show_admin_panel(update, context)
        
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
        if user.id != ADMIN_CHAT_ID:
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
                user=user
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
        dp.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(change_max|toggle_visibility|manage_users|add_user|remove_user|back_to_panel)$'))
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

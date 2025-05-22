import json
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
from datetime import datetime, timedelta
import pytz

# إعدادات البوت
TOKEN = 'YOUR_BOT_TOKEN'
ADMIN_CHAT_ID = 123456789
GROUP_CHAT_ID = -1001234567890
CONFIG_FILE = 'config.json'
USER_LIMITS_FILE = 'user_limits.json'
LOG_FILE = 'logs.json'
MAX_REQUESTS_PER_USER = 5

# إعدادات اللغة
MESSAGES = {
    'en': {
        'welcome': 'Welcome to the bot!',
        'help': 'Help message',
        'manual_code': 'Your manual code is: {code}. It expires at {expiry_time}.',
        'new_code': 'Your new code is: {code}. It expires at {expiry_time}.',
        'copy': 'Copy',
        'request': 'Request Code',
        'language': 'Change Language',
        'limit_reached': 'You have reached the maximum number of requests today.',
        'request_count': 'You have made {request_count} requests today out of {max_requests}.',
        'admin_log': 'User {user_name} ({user_id}) requested a code at {time} from IP {ip} using device {device}. Request count: {request_count}/{max_requests}.',
        'visibility_on': 'Code visibility is ON',
        'visibility_off': 'Code visibility is OFF',
        'visibility_updated': 'Visibility status updated: {status}',
        'max_updated': 'Max requests per user updated to {max_requests}.',
        'invalid_max': 'Invalid max requests value. Please enter a number between 1 and 20.',
        'user_added': 'User {user_id} added to allowed users.',
        'user_removed': 'User {user_id} removed from allowed users.',
        'user_not_found': 'User not found.',
        'enter_new_max': 'Please enter the new max requests per user (1-20):',
        'enter_user_id': 'Please enter the user ID to add/remove:',
        'admin_panel': 'Admin Panel:\nMax Requests: {max_requests}\nVisibility: {visibility}\nAllowed Users: {user_count}',
        'change_max_requests': 'Change Max Requests',
        'toggle_visibility': 'Toggle Visibility',
        'manage_users': 'Manage Users',
        'add_user': 'Add User',
        'remove_user': 'Remove User',
        'back_to_panel': 'Back to Panel',
        'code_copied': 'Code copied to clipboard!',
    },
    'ar': {
        'welcome': 'مرحبًا بك في البوت!',
        'help': 'رسالة المساعدة',
        'manual_code': 'رمزك اليدوي هو: {code}. ينتهي صلاحيته في {expiry_time}.',
        'new_code': 'رمزك الجديد هو: {code}. ينتهي صلاحيته في {expiry_time}.',
        'copy': 'نسخ',
        'request': 'طلب رمز',
        'language': 'تغيير اللغة',
        'limit_reached': 'لقد وصلت إلى الحد الأقصى لعدد الطلبات اليوم.',
        'request_count': 'لقد قمت بعمل {request_count} طلبات اليوم من أصل {max_requests}.',
        'admin_log': 'المستخدم {user_name} ({user_id}) طلب رمزًا في {time} من IP {ip} باستخدام الجهاز {device}. عدد الطلبات: {request_count}/{max_requests}.',
        'visibility_on': 'رؤية الأكواد مفعل',
        'visibility_off': 'رؤية الأكواد غير مفعل',
        'visibility_updated': 'تم تحديث حالة الرؤية: {status}',
        'max_updated': 'تم تحديث الحد الأقصى للطلبات لكل مستخدم إلى {max_requests}.',
        'invalid_max': 'قيمة الحد الأقصى غير صالحة. يرجى إدخال رقم بين 1 و 20.',
        'user_added': 'تم إضافة المستخدم {user_id} إلى المستخدمين المسموح لهم.',
        'user_removed': 'تم إزالة المستخدم {user_id} من المستخدمين المسموح لهم.',
        'user_not_found': 'المستخدم غير موجود.',
        'enter_new_max': 'يرجى إدخال الحد الأقصى الجديد للطلبات لكل مستخدم (1-20):',
        'enter_user_id': 'يرجى إدخال معرف المستخدم للإضافة/الإزالة:',
        'admin_panel': 'لوحة التحكم الإدارية:\nالحد الأقصى للطلبات: {max_requests}\nالرؤية: {visibility}\nعدد المستخدمين المسموح لهم: {user_count}',
        'change_max_requests': 'تغيير الحد الأقصى للطلبات',
        'toggle_visibility': 'تبديل الرؤية',
        'manage_users': 'إدارة المستخدمين',
        'add_user': 'إضافة مستخدم',
        'remove_user': 'إزالة مستخدم',
        'back_to_panel': 'العودة إلى اللوحة',
        'code_copied': 'تم نسخ الرمز إلى الحافظة!',
    }
}

# إعدادات السجل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تحميل الإعدادات
def load_config():
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
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def get_palestine_time():
    palestine_tz = pytz.timezone('Asia/Hebron')
    return datetime.now(palestine_tz)

def generate_2fa_code():
    return '123456'

def get_expiry_time():
    return (get_palestine_time() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

def get_client_ip():
    return '192.168.1.1'

def get_user_device(user_agent):
    return 'Unknown Device'

def can_user_request_code(user_id, max_requests):
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
    try:
        config = load_config()
        return config['code_visibility'] or (user_id in config['allowed_users']) or (user_id == ADMIN_CHAT_ID)
    except Exception as e:
        logger.error(f"Error checking user permissions: {e}")
        return True

def create_keyboard(lang='en'):
    keyboard = [
        [
            InlineKeyboardButton(MESSAGES[lang]['copy'], callback_data='copy_code'),
            InlineKeyboardButton(MESSAGES[lang]['request'], callback_data='request_code')
        ],
        [InlineKeyboardButton(MESSAGES[lang]['language'], callback_data='change_language')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_language_keyboard():
    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data='lang_en')],
        [InlineKeyboardButton("العربية 🇸🇦", callback_data='lang_ar')]
    ]
    return InlineKeyboardMarkup(keyboard)

def send_2fa_code(context: CallbackContext, manual_request=False, lang='en', user=None):
    try:
        ip = get_client_ip()
        device = "Unknown"
        
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
            context.bot.send_message(chat_id=GROUP
::contentReference[oaicite:4]{index=4}
 

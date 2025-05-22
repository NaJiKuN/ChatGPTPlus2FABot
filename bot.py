import os
import time
import pyotp
import pytz
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
import logging
import requests
from functools import wraps

# تكوين الأساسيات
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
BOT_CHAT_ID = 792534650
GROUP_CHAT_ID = -1002329495586
TOTP_SECRET = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
ADMIN_ID = BOT_CHAT_ID  # يمكن تغييره إذا كان هناك مشرفون آخرون

# إعدادات النسخ
MAX_COPIES_PER_DAY = 5
current_copies = 0
last_reset_time = datetime.now()
allowed_users = set()  # مجموعة المستخدمين المسموح لهم بنسخ الرمز

# إعدادات اللغة
LANGUAGES = {
    'en': {
        'copy_button': '📋 Copy Code',
        'code_expires': 'The code is valid for 30 seconds from the time of copying.',
        'copies_remaining': 'Copies remaining today: {}',
        'no_copies_left': 'No copies left for today.',
        'admin_panel': 'Admin Panel',
        'add_user': '➕ Add User',
        'remove_user': '➖ Remove User',
        'increase_copies': '➕ Increase Copies',
        'decrease_copies': '➖ Decrease Copies',
        'user_added': 'User added successfully.',
        'user_removed': 'User removed successfully.',
        'copies_increased': 'Daily copies increased to {}.',
        'copies_decreased': 'Daily copies decreased to {}.',
        'next_code_at': 'Next code at {}',
        'language_button': '🌐 Change Language',
        'select_language': 'Select Language:',
        'language_changed': 'Language changed to {}.',
        'unauthorized': 'You are not authorized to perform this action.',
        'copy_alert_admin': 'User {} (IP: {}) copied the 2FA code. Remaining copies: {}'
    },
    'ar': {
        'copy_button': '📋 نسخ الرمز',
        'code_expires': 'الرمز صالح لمدة 30 ثانية من وقت النسخ.',
        'copies_remaining': 'عدد مرات النسخ المتبقية اليوم: {}',
        'no_copies_left': 'لا توجد محاولات نسخ متبقية لليوم.',
        'admin_panel': 'لوحة التحكم',
        'add_user': '➕ إضافة عضو',
        'remove_user': '➖ إزالة عضو',
        'increase_copies': '➕ زيادة النسخ',
        'decrease_copies': '➖ تقليل النسخ',
        'user_added': 'تمت إضافة العضو بنجاح.',
        'user_removed': 'تمت إزالة العضو بنجاح.',
        'copies_increased': 'تم زيادة عدد النسخ اليومية إلى {}.',
        'copies_decreased': 'تم تقليل عدد النسخ اليومية إلى {}.',
        'next_code_at': 'الرمز التالي عند {}',
        'language_button': '🌐 تغيير اللغة',
        'select_language': 'اختر اللغة:',
        'language_changed': 'تم تغيير اللغة إلى {}.',
        'unauthorized': 'غير مسموح لك بتنفيذ هذا الإجراء.',
        'copy_alert_admin': 'العضو {} (IP: {}) قام بنسخ رمز المصادقة. النسخ المتبقية: {}'
    }
}

user_language = {}  # تخزين تفضيلات اللغة للمستخدمين

# إعداد التسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# تهيئة TOTP
totp = pyotp.TOTP(TOTP_SECRET)

# وظيفة المسؤول
def admin_required(func):
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            lang = user_language.get(user_id, 'en')
            update.message.reply_text(LANGUAGES[lang]['unauthorized'])
            return
        return func(update, context, *args, **kwargs)
    return wrapped

# الحصول على عنوان IP للمستخدم
def get_user_ip(user_id):
    # هذه وظيفة وهمية - في الواقع تحتاج إلى طريقة للحصول على IP
    # يمكنك استخدام webhook أو طلب من المستخدم إدخال IP يدوياً
    return "192.168.1.{}".format(user_id % 255)  # مثال فقط

# إرسال رمز المصادقة
def send_2fa_code(context: CallbackContext):
    global current_copies, last_reset_time
    
    # إعادة تعيين العداد إذا كان يوم جديد
    now = datetime.now()
    if now.date() != last_reset_time.date():
        current_copies = 0
        last_reset_time = now
    
    # إنشاء الرمز
    code = totp.now()
    
    # حساب وقت الرمز التالي
    next_code_time = (now + timedelta(minutes=5)).strftime("%I:%M:%S %p")
    
    # إعداد لوحة المفاتيح
    keyboard = [
        [InlineKeyboardButton(LANGUAGES['ar']['copy_button'], callback_data='copy_code')],
        [InlineKeyboardButton(LANGUAGES['ar']['language_button'], callback_data='change_language')]
    ]
    
    if context.job.context.get('is_admin', False):
        keyboard.append([InlineKeyboardButton(LANGUAGES['ar']['admin_panel'], callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال الرسالة
    message_text = f"رمز المصادقة الثنائية الجاهز.\n\n{LANGUAGES['ar']['next_code_at'].format(next_code_time)}"
    context.bot.send_message(chat_id=GROUP_CHAT_ID, text=message_text, reply_markup=reply_markup)

# معالج نسخ الرمز
def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    lang = user_language.get(user_id, 'en')
    
    if query.data == 'copy_code':
        global current_copies
        
        if user_id not in allowed_users and user_id != ADMIN_ID:
            query.answer(text=LANGUAGES[lang]['no_copies_left'], show_alert=True)
            return
        
        if current_copies >= MAX_COPIES_PER_DAY:
            query.answer(text=LANGUAGES[lang]['no_copies_left'], show_alert=True)
            return
        
        # إنشاء الرمز
        code = totp.now()
        
        # زيادة العداد
        current_copies += 1
        
        # إعلام المستخدم
        remaining_copies = MAX_COPIES_PER_DAY - current_copies
        alert_text = f"{code}\n\n{LANGUAGES[lang]['code_expires']}\n{LANGUAGES[lang]['copies_remaining'].format(remaining_copies)}"
        query.answer(text=alert_text, show_alert=True)
        
        # إعلام المسؤول
        if user_id != ADMIN_ID:
            user_ip = get_user_ip(user_id)
            user_name = query.from_user.full_name
            admin_alert = LANGUAGES[lang]['copy_alert_admin'].format(user_name, user_ip, remaining_copies)
            context.bot.send_message(chat_id=ADMIN_ID, text=admin_alert)
    
    elif query.data == 'admin_panel':
        if user_id == ADMIN_ID:
            show_admin_panel(query, context)
        else:
            query.answer(text=LANGUAGES[lang]['unauthorized'], show_alert=True)
    
    elif query.data == 'change_language':
        show_language_selection(query, context)
    
    elif query.data.startswith('lang_'):
        selected_lang = query.data.split('_')[1]
        user_language[user_id] = selected_lang
        query.answer(text=LANGUAGES[selected_lang]['language_changed'].format(selected_lang.upper()))
    
    elif query.data == 'add_user':
        if user_id == ADMIN_ID:
            context.user_data['action'] = 'add_user'
            query.edit_message_text(text="Please forward a message from the user you want to add or send their user ID.")
        else:
            query.answer(text=LANGUAGES[lang]['unauthorized'], show_alert=True)
    
    elif query.data == 'remove_user':
        if user_id == ADMIN_ID:
            context.user_data['action'] = 'remove_user'
            query.edit_message_text(text="Please forward a message from the user you want to remove or send their user ID.")
        else:
            query.answer(text=LANGUAGES[lang]['unauthorized'], show_alert=True)
    
    elif query.data == 'increase_copies':
        if user_id == ADMIN_ID:
            increase_copies(update, context)
        else:
            query.answer(text=LANGUAGES[lang]['unauthorized'], show_alert=True)
    
    elif query.data == 'decrease_copies':
        if user_id == ADMIN_ID:
            decrease_copies(update, context)
        else:
            query.answer(text=LANGUAGES[lang]['unauthorized'], show_alert=True)

# عرض لوحة التحكم للمسؤول
def show_admin_panel(query, context):
    lang = user_language.get(query.from_user.id, 'en')
    
    keyboard = [
        [InlineKeyboardButton(LANGUAGES[lang]['add_user'], callback_data='add_user')],
        [InlineKeyboardButton(LANGUAGES[lang]['remove_user'], callback_data='remove_user')],
        [InlineKeyboardButton(LANGUAGES[lang]['increase_copies'], callback_data='increase_copies')],
        [InlineKeyboardButton(LANGUAGES[lang]['decrease_copies'], callback_data='decrease_copies')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text=LANGUAGES[lang]['admin_panel'], reply_markup=reply_markup)

# عرض خيارات اللغة
def show_language_selection(query, context):
    lang = user_language.get(query.from_user.id, 'en')
    
    keyboard = [
        [InlineKeyboardButton("English", callback_data='lang_en')],
        [InlineKeyboardButton("العربية", callback_data='lang_ar')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text=LANGUAGES[lang]['select_language'], reply_markup=reply_markup)

# زيادة عدد النسخ اليومية
def increase_copies(update: Update, context: CallbackContext):
    global MAX_COPIES_PER_DAY
    MAX_COPIES_PER_DAY += 1
    lang = user_language.get(update.effective_user.id, 'en')
    update.callback_query.answer(text=LANGUAGES[lang]['copies_increased'].format(MAX_COPIES_PER_DAY))

# تقليل عدد النسخ اليومية
def decrease_copies(update: Update, context: CallbackContext):
    global MAX_COPIES_PER_DAY
    if MAX_COPIES_PER_DAY > 1:
        MAX_COPIES_PER_DAY -= 1
        lang = user_language.get(update.effective_user.id, 'en')
        update.callback_query.answer(text=LANGUAGES[lang]['copies_decreased'].format(MAX_COPIES_PER_DAY))
    else:
        lang = user_language.get(update.effective_user.id, 'en')
        update.callback_query.answer(text="Cannot decrease below 1.")

# معالج أمر المسؤول
@admin_required
def admin_command(update: Update, context: CallbackContext):
    show_admin_panel(update.callback_query, context)

# معالج الرسائل للمسؤول (لإضافة/إزالة الأعضاء)
def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    if 'action' in context.user_data:
        action = context.user_data['action']
        target_user_id = None
        
        # الحصول على معرف المستخدم الهدف
        if update.message.forward_from:
            target_user_id = update.message.forward_from.id
        elif update.message.text and update.message.text.isdigit():
            target_user_id = int(update.message.text)
        
        if target_user_id:
            lang = user_language.get(user_id, 'en')
            
            if action == 'add_user':
                allowed_users.add(target_user_id)
                update.message.reply_text(LANGUAGES[lang]['user_added'])
            elif action == 'remove_user':
                if target_user_id in allowed_users:
                    allowed_users.remove(target_user_id)
                    update.message.reply_text(LANGUAGES[lang]['user_removed'])
            
            del context.user_data['action']
        else:
            update.message.reply_text("Please forward a user's message or send their user ID.")

# بدء البوت
def start_bot():
    # إنشاء Updater وإرسال المهام
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # إضافة المعالجات
    dp.add_handler(CommandHandler("admin", admin_command))
    dp.add_handler(CallbackQueryHandler(button_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    # بدء المهمة الدورية
    job_queue = updater.job_queue
    job_queue.run_repeating(send_2fa_code, interval=300, first=0, context={'is_admin': True})
    
    # بدء البوت
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    # إضافة المسؤول إلى القائمة المسموح لهم
    allowed_users.add(ADMIN_ID)
    start_bot()

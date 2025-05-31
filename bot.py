import logging
import sqlite3
import pytz
import pyotp
import re
import os
from datetime import datetime, timedelta
from threading import Lock
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,
    MessageHandler,
    Filters,
    ConversationHandler,
    JobQueue
)
from telegram.constants import ParseMode  # التعديل الرئيسي هنا

# إعدادات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chatgptplus2fabot.db')

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_errors.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# حالات المحادثة
(
    GROUP_ID, TOTP_SECRET, 
    GROUP_INTERVAL, SELECT_INTERVAL,
    GROUP_MSG_FORMAT, SELECT_MSG_FORMAT,
    SELECT_GROUP_FOR_ATTEMPTS, SELECT_USER_FOR_ATTEMPTS, USER_ACTION, 
    ADD_ATTEMPTS, REMOVE_ATTEMPTS,
    ADMIN_ACTION, ADMIN_USER_ID
) = range(12)

# قفل لقاعدة البيانات
db_lock = Lock()

# تهيئة قاعدة البيانات
def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # جدول المجموعات
        c.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                totp_secret TEXT NOT NULL,
                interval_minutes INTEGER DEFAULT 10,
                message_format INTEGER DEFAULT 1,
                timezone TEXT DEFAULT 'Asia/Gaza',
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        # جدول المستخدمين (المحاولات)
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                group_id TEXT,
                attempts INTEGER DEFAULT 3,
                last_attempt DATETIME,
                PRIMARY KEY (user_id, group_id),
                FOREIGN KEY (group_id) REFERENCES groups(group_id)
            )
        ''')
        # جدول المسؤولين
        c.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        # جدول سجل المحاولات
        c.execute('''
            CREATE TABLE IF NOT EXISTS attempts_log (
                user_id INTEGER,
                group_id TEXT,
                used_at DATETIME,
                code TEXT
            )
        ''')
        # إضافة المسؤول الافتراضي
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ADMIN_ID,))
        conn.commit()
        conn.close()

init_db()

# دوال مساعدة لقاعدة البيانات
def add_admin(user_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()

def is_admin(user_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        result = c.fetchone() is not None
        conn.close()
        return result

def add_group(group_id: str, totp_secret: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO groups (group_id, totp_secret) VALUES (?, ?)", (group_id, totp_secret))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

def get_groups():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT group_id FROM groups")
        groups = [row[0] for row in c.fetchall()]
        conn.close()
        return groups

def get_group_info(group_id: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM groups WHERE group_id=?", (group_id,))
        group_info = c.fetchone()
        conn.close()
        return group_info

def update_group_interval(group_id: str, interval: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE groups SET interval_minutes=? WHERE group_id=?", (interval, group_id))
        conn.commit()
        conn.close()

def update_group_active(group_id: str, active: bool):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE groups SET is_active=? WHERE group_id=?", (active, group_id))
        conn.commit()
        conn.close()

def update_message_format(group_id: str, msg_format: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE groups SET message_format=? WHERE group_id=?", (msg_format, group_id))
        conn.commit()
        conn.close()

def get_user_attempts(user_id: int, group_id: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT attempts FROM users WHERE user_id=? AND group_id=?", (user_id, group_id))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 3

def update_user_attempts(user_id: int, group_id: str, delta: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # إنشاء المستخدم إذا لم يكن موجوداً
        c.execute("""
            INSERT OR IGNORE INTO users (user_id, group_id, attempts) 
            VALUES (?, ?, 3)
        """, (user_id, group_id))
        # تحديث المحاولات
        c.execute("""
            UPDATE users SET attempts = MAX(0, attempts + ?) 
            WHERE user_id=? AND group_id=?
        """, (delta, user_id, group_id))
        conn.commit()
        conn.close()

def reset_daily_attempts(context: CallbackContext):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET attempts = 3")
        conn.commit()
        conn.close()

# دوال البوت الأساسية
def start(update: Update, context: CallbackContext):
    update.message.reply_text("مرحباً! أنا بوت المصادقة الثنائية ChatGPTPlus2FABot. للأمر الإداري استخدم /admin")

def admin(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("❌ ليس لديك صلاحية الوصول.")
        return

    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data='manage_groups')],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data='manage_interval')],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data='manage_msg_format')],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data='manage_user_attempts')],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data='manage_admins')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("👑 لوحة تحكم المسؤول:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    
    if not is_admin(user_id):
        query.edit_message_text(text="❌ ليس لديك صلاحية الوصول.")
        return

    data = query.data
    
    if data == 'manage_groups':
        keyboard = [
            [InlineKeyboardButton("إضافة مجموعة", callback_data='add_group')],
            [InlineKeyboardButton("حذف مجموعة", callback_data='delete_group')],
            [InlineKeyboardButton("تعديل مجموعة", callback_data='edit_group')],
            [InlineKeyboardButton("رجوع", callback_data='back_admin')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="🔧 إدارة Groups/TOTP_SECRET:", reply_markup=reply_markup)
    
    elif data == 'add_group':
        query.edit_message_text(text="📤 أرسل معرف المجموعة (Group ID):")
        return GROUP_ID
    
    elif data == 'back_admin':
        admin(update, context)
        return ConversationHandler.END
    
    elif data == 'manage_interval':
        groups = get_groups()
        if not groups:
            query.edit_message_text(text="⚠️ لا توجد مجموعات مسجلة.")
            return
        
        keyboard = []
        for group_id in groups:
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f'set_interval_{group_id}')])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="⏱ اختر مجموعة لإدارة فترة التكرار:", reply_markup=reply_markup)
    
    elif data.startswith('set_interval_'):
        group_id = data.split('_', 2)[2]
        context.user_data['group_id'] = group_id
        intervals = [1, 5, 10, 15, 30, 60, 180, 720, 1440]
        interval_names = {
            1: "1 دقيقة",
            5: "5 دقائق",
            10: "10 دقائق",
            15: "15 دقيقة",
            30: "30 دقيقة",
            60: "ساعة",
            180: "3 ساعات",
            720: "12 ساعة",
            1440: "24 ساعة"
        }
        
        keyboard = []
        row = []
        for i, interval in enumerate(intervals):
            row.append(InlineKeyboardButton(interval_names[interval], callback_data=f'interval_{interval}'))
            if (i+1) % 3 == 0 or i == len(intervals)-1:
                keyboard.append(row)
                row = []
        
        group_info = get_group_info(group_id)
        is_active = group_info[5] if group_info else True
        active_text = "⏹ إيقاف التكرار" if is_active else "▶ بدء التكرار"
        keyboard.append([InlineKeyboardButton(active_text, callback_data=f'toggle_active_{group_id}')])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data='manage_interval')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            text=f"⏱ اختر فترة التكرار للمجموعة {group_id}:",
            reply_markup=reply_markup
        )
    
    elif data.startswith('interval_'):
        interval = int(data.split('_')[1])
        group_id = context.user_data['group_id']
        update_group_interval(group_id, interval)
        
        # إعادة جدولة المهمة
        job_name = f"group_job_{group_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        if get_group_info(group_id)[5]:  # إذا كانت المجموعة نشطة
            context.job_queue.run_repeating(
                send_group_message, 
                interval=interval * 60, 
                first=0, 
                context=group_id, 
                name=job_name
            )
        
        query.edit_message_text(text=f"✅ تم تحديث فترة التكرار لـ {interval} دقيقة للمجموعة {group_id}")
    
    elif data.startswith('toggle_active_'):
        group_id = data.split('_', 2)[2]
        group_info = get_group_info(group_id)
        if group_info:
            new_status = not group_info[5]
            update_group_active(group_id, new_status)
            
            job_name = f"group_job_{group_id}"
            current_jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in current_jobs:
                job.schedule_removal()
            
            if new_status:
                interval = group_info[2] or 10
                context.job_queue.run_repeating(
                    send_group_message, 
                    interval=interval * 60, 
                    first=0, 
                    context=group_id, 
                    name=job_name
                )
                query.edit_message_text(text=f"✅ تم تفعيل الإرسال الدوري للمجموعة {group_id}")
            else:
                query.edit_message_text(text=f"⏸ تم إيقاف الإرسال الدوري للمجموعة {group_id}")
    
    elif data == 'manage_msg_format':
        groups = get_groups()
        if not groups:
            query.edit_message_text(text="⚠️ لا توجد مجموعات مسجلة.")
            return
        
        keyboard = []
        for group_id in groups:
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f'set_format_{group_id}')])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="🎨 اختر مجموعة لإدارة شكل الرسالة:", reply_markup=reply_markup)
    
    elif data.startswith('set_format_'):
        group_id = data.split('_', 2)[2]
        context.user_data['group_id'] = group_id
        
        keyboard = [
            [InlineKeyboardButton("الشكل الأول", callback_data='format_1')],
            [InlineKeyboardButton("الشكل الثاني", callback_data='format_2')],
            [InlineKeyboardButton("الشكل الثالث", callback_data='format_3')],
            [InlineKeyboardButton("رجوع", callback_data='manage_msg_format')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            text=f"🎨 اختر شكل الرسالة للمجموعة {group_id}:\n\n"
                 "1. 🔐 2FA Verification Code\nNext code at: 07:05:34 PM\n\n"
                 "2. 🔐 2FA Verification Code\nNext code in: 10 minutes\nNext code at: 07:05:34 PM\n\n"
                 "3. 🔐 2FA Verification Code\nNext code in: 10 minutes\nCorrect Time: 06:55:34 PM\nNext Code at: 07:05:34 PM",
            reply_markup=reply_markup
        )
    
    elif data.startswith('format_'):
        msg_format = int(data.split('_')[1])
        group_id = context.user_data['group_id']
        update_message_format(group_id, msg_format)
        query.edit_message_text(text=f"✅ تم تحديث شكل الرسالة للشكل {msg_format} للمجموعة {group_id}")
    
    elif data == 'manage_user_attempts':
        groups = get_groups()
        if not groups:
            query.edit_message_text(text="⚠️ لا توجد مجموعات مسجلة.")
            return
        
        keyboard = []
        for group_id in groups:
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f'select_group_{group_id}')])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_admin')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="👥 اختر مجموعة لإدارة محاولات المستخدمين:", reply_markup=reply_markup)
    
    elif data.startswith('select_group_'):
        group_id = data.split('_', 2)[2]
        context.user_data['group_id'] = group_id
        
        # الحصول على المستخدمين في هذه المجموعة
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT u.user_id, u.attempts, u.last_attempt 
                FROM users u
                WHERE u.group_id=?
            """, (group_id,))
            users = c.fetchall()
            conn.close()
        
        if not users:
            query.edit_message_text(text=f"⚠️ لا يوجد مستخدمين في المجموعة {group_id}.")
            return
        
        keyboard = []
        for user_id, attempts, last_attempt in users:
            last_attempt = last_attempt or "لم يستخدم"
            try:
                user = context.bot.get_chat(user_id)
                username = user.username or f"User {user_id}"
            except:
                username = f"User {user_id}"
            keyboard.append([
                InlineKeyboardButton(
                    f"{username} - المحاولات: {attempts}",
                    callback_data=f'select_user_{user_id}'
                )
            ])
        keyboard.append([InlineKeyboardButton("رجوع", callback_data='manage_user_attempts')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            text=f"👤 اختر مستخدم لإدارة المحاولات في المجموعة {group_id}:",
            reply_markup=reply_markup
        )
    
    elif data.startswith('select_user_'):
        user_id = int(data.split('_', 2)[2])
        group_id = context.user_data['group_id']
        context.user_data['user_id'] = user_id
        
        attempts = get_user_attempts(user_id, group_id)
        try:
            user = context.bot.get_chat(user_id)
            username = user.username or f"User {user_id}"
        except:
            username = f"User {user_id}"
        
        keyboard = [
            [InlineKeyboardButton("حظر المستخدم", callback_data='ban_user')],
            [InlineKeyboardButton("إضافة محاولات", callback_data='add_attempts')],
            [InlineKeyboardButton("حذف محاولات", callback_data='remove_attempts')],
            [InlineKeyboardButton("رجوع", callback_data=f'select_group_{group_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            text=f"👤 إدارة المستخدم: {username}\n"
                 f"🔢 المحاولات المتبقية: {attempts}\n"
                 f"🆔 User ID: {user_id}\n"
                 f"📌 المجموعة: {group_id}",
            reply_markup=reply_markup
        )
    
    elif data == 'add_attempts':
        query.edit_message_text(text="➕ أدخل عدد المحاولات التي تريد إضافتها:")
        return ADD_ATTEMPTS
    
    elif data == 'remove_attempts':
        query.edit_message_text(text="➖ أدخل عدد المحاولات التي تريد حذفها:")
        return REMOVE_ATTEMPTS
    
    elif data == 'ban_user':
        user_id = context.user_data['user_id']
        group_id = context.user_data['group_id']
        update_user_attempts(user_id, group_id, -999)  # حظر فعلي
        query.edit_message_text(text="✅ تم حظر المستخدم من استخدام النظام.")
    
    elif data == 'manage_admins':
        keyboard = [
            [InlineKeyboardButton("إضافة مسؤول", callback_data='add_admin')],
            [InlineKeyboardButton("حذف مسؤول", callback_data='remove_admin')],
            [InlineKeyboardButton("عرض المسؤولين", callback_data='list_admins')],
            [InlineKeyboardButton("رجوع", callback_data='back_admin')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="👑 إدارة المسؤولين:", reply_markup=reply_markup)
    
    elif data == 'add_admin':
        query.edit_message_text(text="👤 أرسل User ID للمسؤول الجديد:")
        return ADMIN_USER_ID
    
    elif data == 'list_admins':
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT user_id FROM admins")
            admins = [str(row[0]) for row in c.fetchall()]
            conn.close()
        
        if admins:
            query.edit_message_text(text="👑 قائمة المسؤولين:\n" + "\n".join(admins))
        else:
            query.edit_message_text(text="⚠️ لا يوجد مسؤولين مسجلين.")

def group_id_input(update: Update, context: CallbackContext):
    group_id = update.message.text.strip()
    
    # التحقق من صيغة معرف المجموعة
    if not re.match(r'^-100\d+$', group_id):
        update.message.reply_text("❌ معرف المجموعة غير صالح. يجب أن يبدأ بـ '-100' ويتبعه أرقام.")
        return GROUP_ID
    
    context.user_data['group_id'] = group_id
    update.message.reply_text("🔑 أرسل الـ TOTP_SECRET:")
    return TOTP_SECRET

def totp_secret_input(update: Update, context: CallbackContext):
    totp_secret = update.message.text.strip()
    group_id = context.user_data['group_id']
    
    # محاولة توليد TOTP للتحقق من صحة السر
    try:
        pyotp.TOTP(totp_secret).now()
    except:
        update.message.reply_text("❌ TOTP_SECRET غير صالح. يرجى إرسال سر صالح.")
        return TOTP_SECRET
    
    if add_group(group_id, totp_secret):
        # جدولة الإرسال الدوري
        interval = 10  # 10 دقائق افتراضياً
        job_name = f"group_job_{group_id}"
        context.job_queue.run_repeating(
            send_group_message, 
            interval=interval * 60, 
            first=0, 
            context=group_id, 
            name=job_name
        )
        update.message.reply_text(f"✅ تمت إضافة المجموعة {group_id} بنجاح!")
    else:
        update.message.reply_text("❌ فشل إضافة المجموعة. قد تكون مسجلة مسبقاً.")
    
    return ConversationHandler.END

def send_group_message(context: CallbackContext):
    group_id = context.job.context
    group_info = get_group_info(group_id)
    
    if not group_info or not group_info[5]:  # إذا لم تكن المجموعة نشطة
        return
    
    totp_secret, interval, msg_format, tz, _, _ = group_info
    
    # الحصول على الوقت الحالي بالنطاق الزمني
    tz_obj = pytz.timezone(tz)
    now = datetime.now(tz_obj)
    next_time = now + timedelta(minutes=interval)
    
    # توليد النص حسب الشكل المختار
    if msg_format == 1:
        message_text = (
            "🔐 2FA Verification Code\n\n"
            f"Next code at: {next_time.strftime('%I:%M:%S %p')}"
        )
    elif msg_format == 2:
        message_text = (
            "🔐 2FA Verification Code\n\n"
            f"Next code in: {interval} minutes\n"
            f"Next code at: {next_time.strftime('%I:%M:%S %p')}"
        )
    else:  # الشكل الثالث
        message_text = (
            "🔐 2FA Verification Code\n"
            f"Next code in: {interval} minutes\n"
            f"Correct Time: {now.strftime('%I:%M:%S %p')}\n"
            f"Next Code at: {next_time.strftime('%I:%M:%S %p')}"
        )
    
    # إرسال الرسالة مع زر النسخ
    keyboard = [[InlineKeyboardButton("📋 Copy Code", callback_data=f'copy_code_{group_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        context.bot.send_message(
            chat_id=group_id, 
            text=message_text, 
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending message to group {group_id}: {str(e)}")

def copy_code_button(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    group_id = query.data.split('_')[2]  # copy_code_<group_id>
    
    # التحقق من وجود المجموعة
    group_info = get_group_info(group_id)
    if not group_info:
        query.answer(text="❌ هذه المجموعة لم تعد مسجلة.", show_alert=True)
        return
    
    # التحقق من المحاولات
    attempts = get_user_attempts(user_id, group_id)
    if attempts <= 0:
        query.answer(
            text="❌ لا توجد محاولات متبقية. يرجى الانتظار حتى منتصف الليل لتجديد المحاولات.",
            show_alert=True
        )
        return
    
    # توليد الرمز
    totp_secret = group_info[1]
    totp = pyotp.TOTP(totp_secret)
    code = totp.now()
    valid_until = datetime.utcnow() + timedelta(seconds=30)
    
    # تحديث المحاولات
    update_user_attempts(user_id, group_id, -1)
    new_attempts = get_user_attempts(user_id, group_id)
    
    # إرسال الرسالة الخاصة
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=(
                "🔑 رمز المصادقة:\n"
                f"`{code}`\n\n"
                f"⏳ صالح لمدة: 30 ثانية فقط (حتى {valid_until.strftime('%H:%M:%S')} UTC)\n"
                f"🔢 المحاولات المتبقية: {new_attempts}\n\n"
                "⚠️ لا تشارك هذا الرمز مع أي أحد!"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        query.answer("✅ تم إرسال الرمز إلى رسائلك الخاصة!", show_alert=False)
    except Exception as e:
        logger.error(f"Failed to send DM to {user_id}: {str(e)}")
        query.answer("❌ فشل إرسال الرسالة. تأكد من بدء محادثة مع البوت.", show_alert=True)

def add_attempts_input(update: Update, context: CallbackContext):
    try:
        amount = int(update.message.text)
        user_id = context.user_data['user_id']
        group_id = context.user_data['group_id']
        
        update_user_attempts(user_id, group_id, amount)
        new_attempts = get_user_attempts(user_id, group_id)
        
        update.message.reply_text(
            f"✅ تمت إضافة {amount} محاولة. المحاولات الجديدة: {new_attempts}"
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("❌ يرجى إدخال رقم صحيح.")
        return ADD_ATTEMPTS

def remove_attempts_input(update: Update, context: CallbackContext):
    try:
        amount = int(update.message.text)
        user_id = context.user_data['user_id']
        group_id = context.user_data['group_id']
        
        update_user_attempts(user_id, group_id, -amount)
        new_attempts = get_user_attempts(user_id, group_id)
        
        update.message.reply_text(
            f"✅ تم حذف {amount} محاولة. المحاولات الجديدة: {new_attempts}"
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("❌ يرجى إدخال رقم صحيح.")
        return REMOVE_ATTEMPTS

def admin_user_id_input(update: Update, context: CallbackContext):
    try:
        user_id = int(update.message.text)
        add_admin(user_id)
        update.message.reply_text(f"✅ تمت إضافة المسؤول الجديد: {user_id}")
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("❌ يرجى إدخال User ID صحيح (أرقام فقط).")
        return ADMIN_USER_ID

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("❌ تم إلغاء العملية.")
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="حدث خطأ في البوت:", exc_info=context.error)
    if update.effective_message:
        update.effective_message.reply_text("❌ حدث خطأ غير متوقع. يرجى المحاولة لاحقاً.")

def main():
    # إعداد البوت
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    job_queue = updater.job_queue

    # جدولة إعادة تعيين المحاولات يومياً
    job_queue.run_daily(reset_daily_attempts, time=datetime.strptime("00:00", "%H:%M").time())

    # إعداد الأوامر
    commands = [
        BotCommand("admin", "لوحة تحكم المسؤول")
    ]
    updater.bot.set_my_commands(commands)

    # معالجات المحادثة
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin)],
        states={
            GROUP_ID: [MessageHandler(Filters.text & ~Filters.command, group_id_input)],
            TOTP_SECRET: [MessageHandler(Filters.text & ~Filters.command, totp_secret_input)],
            ADD_ATTEMPTS: [MessageHandler(Filters.text & ~Filters.command, add_attempts_input)],
            REMOVE_ATTEMPTS: [MessageHandler(Filters.text & ~Filters.command, remove_attempts_input)],
            ADMIN_USER_ID: [MessageHandler(Filters.text & ~Filters.command, admin_user_id_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # تسجيل المعالجات
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(CallbackQueryHandler(copy_code_button, pattern='^copy_code_'))
    dp.add_error_handler(error_handler)

    # بدء البوت
    updater.start_polling()
    logger.info("تم بدء البوت بنجاح")
    updater.idle()

if __name__ == '__main__':
    main()

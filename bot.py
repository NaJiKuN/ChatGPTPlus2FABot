import os
import time
import pytz
from datetime import datetime, timedelta
import threading
from typing import Dict, List, Tuple, Optional
import secrets
import string
import pyotp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
)
import logging
import json
from collections import defaultdict

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466  # يمكن تحويله إلى قائمة إذا كان هناك عدة مسؤولين

# مسارات الملفات
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# حالات المحادثة
(
    ADMIN_MENU,
    MANAGE_GROUPS,
    ADD_GROUP,
    EDIT_GROUP,
    DELETE_GROUP,
    MANAGE_TOTP,
    ADD_TOTP,
    EDIT_TOTP,
    DELETE_TOTP,
    SET_INTERVAL,
    SET_MESSAGE_STYLE,
    SET_TIMEZONE,
    MANAGE_ADMINS,
    ADD_ADMIN,
    REMOVE_ADMIN,
    MANAGE_ATTEMPTS,
    SELECT_GROUP_ATTEMPTS,
    SELECT_USER_ATTEMPTS,
    ADD_ATTEMPTS,
    REMOVE_ATTEMPTS,
    BAN_USER,
) = range(21)

# إنشاء مجلد البيانات إذا لم يكن موجوداً
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# تهيئة ملفات البيانات إذا لم تكن موجودة
def init_data_files():
    default_data = {
        "groups": {},
        "admins": [ADMIN_ID],
        "message_style": 1,
        "timezone": "Asia/Gaza",
        "user_attempts": {},
        "banned_users": [],
    }
    
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_data, f, indent=4)
    
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump({}, f, indent=4)

init_data_files()

# وظائف مساعدة للتعامل مع الملفات
def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

# وظائف مساعدة للوقت
def get_current_time(timezone_str="Asia/Gaza"):
    tz = pytz.timezone(timezone_str)
    return datetime.now(tz)

def format_time(dt, time_format="%I:%M:%S %p"):
    return dt.strftime(time_format)

# وظائف مساعدة لـ 2FA
def generate_2fa_code(secret: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.now()

def is_valid_secret(secret: str) -> bool:
    try:
        pyotp.TOTP(secret).now()
        return True
    except:
        return False

# وظائف مساعدة للواجهة
def admin_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("إدارة المجموعات/الأسرار", callback_data="manage_groups"),
            InlineKeyboardButton("إدارة فترة التكرار", callback_data="set_interval"),
        ],
        [
            InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="set_message_style"),
            InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_attempts"),
        ],
        [
            InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins"),
            InlineKeyboardButton("إغلاق القائمة", callback_data="close_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def groups_keyboard():
    config = load_config()
    keyboard = []
    for group_id in config["groups"]:
        keyboard.append([
            InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f"group_{group_id}"),
        ])
    keyboard.append([
        InlineKeyboardButton("إضافة مجموعة", callback_data="add_group"),
        InlineKeyboardButton("رجوع", callback_data="back_to_admin"),
    ])
    return InlineKeyboardMarkup(keyboard)

def group_management_keyboard(group_id):
    keyboard = [
        [
            InlineKeyboardButton("إضافة/تعديل TOTP_SECRET", callback_data=f"add_totp_{group_id}"),
            InlineKeyboardButton("حذف المجموعة", callback_data=f"delete_group_{group_id}"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="manage_groups"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def interval_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("1 دقيقة", callback_data="interval_1"),
            InlineKeyboardButton("5 دقائق", callback_data="interval_5"),
            InlineKeyboardButton("10 دقائق", callback_data="interval_10"),
        ],
        [
            InlineKeyboardButton("15 دقيقة", callback_data="interval_15"),
            InlineKeyboardButton("30 دقيقة", callback_data="interval_30"),
            InlineKeyboardButton("1 ساعة", callback_data="interval_60"),
        ],
        [
            InlineKeyboardButton("3 ساعات", callback_data="interval_180"),
            InlineKeyboardButton("12 ساعة", callback_data="interval_720"),
            InlineKeyboardButton("24 ساعة", callback_data="interval_1440"),
        ],
        [
            InlineKeyboardButton("إيقاف التكرار", callback_data="interval_0"),
            InlineKeyboardButton("بدء التكرار", callback_data="start_interval"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="back_to_admin"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def message_style_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("الشكل الأول", callback_data="style_1"),
            InlineKeyboardButton("الشكل الثاني", callback_data="style_2"),
        ],
        [
            InlineKeyboardButton("الشكل الثالث", callback_data="style_3"),
        ],
        [
            InlineKeyboardButton("تغيير المنطقة الزمنية", callback_data="change_timezone"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="back_to_admin"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def timezone_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("توقيت غرينتش (UTC)", callback_data="tz_UTC"),
            InlineKeyboardButton("توقيت غزة (Asia/Gaza)", callback_data="tz_Asia/Gaza"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="set_message_style"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def admins_management_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin"),
            InlineKeyboardButton("حذف مسؤول", callback_data="remove_admin"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="back_to_admin"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def attempts_management_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("حدد عدد مرات النسخ", callback_data="set_attempts_limit"),
        ],
        [
            InlineKeyboardButton("اختيار المجموعة", callback_data="select_group_attempts"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="back_to_admin"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def user_attempts_keyboard(group_id, user_id):
    keyboard = [
        [
            InlineKeyboardButton("حظر المستخدم", callback_data=f"ban_user_{group_id}_{user_id}"),
            InlineKeyboardButton("إضافة محاولات", callback_data=f"add_attempts_{group_id}_{user_id}"),
        ],
        [
            InlineKeyboardButton("حذف محاولات", callback_data=f"remove_attempts_{group_id}_{user_id}"),
        ],
        [
            InlineKeyboardButton("رجوع", callback_data="select_group_attempts"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

# وظائف البوت الأساسية
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID or user_id in load_config()["admins"]:
        update.message.reply_text(
            "مرحباً بك في نظام إدارة 2FA\nاستخدم الأمر /admin للوصول إلى لوحة التحكم.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        update.message.reply_text(
            "مرحباً! هذا البوت مخصص لإدارة رموز المصادقة الثنائية.",
            reply_markup=ReplyKeyboardRemove(),
        )

def admin_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    config = load_config()
    
    if user_id == ADMIN_ID or user_id in config["admins"]:
        update.message.reply_text(
            "لوحة تحكم المسؤول:",
            reply_markup=admin_menu_keyboard(),
        )
        return ADMIN_MENU
    else:
        update.message.reply_text("ليس لديك صلاحية الوصول إلى هذه الأداة.")
        return ConversationHandler.END

def back_to_admin(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="لوحة تحكم المسؤول:",
        reply_markup=admin_menu_keyboard(),
    )
    return ADMIN_MENU

def close_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="تم إغلاق القائمة.")
    return ConversationHandler.END

# إدارة المجموعات و TOTP_SECRET
def manage_groups(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="إدارة المجموعات والأسرار:",
        reply_markup=groups_keyboard(),
    )
    return MANAGE_GROUPS

def add_group(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="أرسل معرف المجموعة الذي تريد إضافته (يجب أن يبدأ بـ -100):")
    return ADD_GROUP

def process_add_group(update: Update, context: CallbackContext):
    group_id = update.message.text.strip()
    
    try:
        group_id_int = int(group_id)
        if group_id_int >= 0:
            update.message.reply_text("معرف المجموعة يجب أن يبدأ بـ -100. الرجاء إدخال معرف صحيح.")
            return ADD_GROUP
    except ValueError:
        update.message.reply_text("معرف المجموعة يجب أن يكون رقماً. الرجاء إدخال معرف صحيح.")
        return ADD_GROUP
    
    config = load_config()
    if group_id in config["groups"]:
        update.message.reply_text("هذه المجموعة مضافه بالفعل.")
    else:
        config["groups"][group_id] = {
            "totp_secret": "",
            "interval": 10,  # 10 دقائق افتراضياً
            "active": False,
            "next_run": None,
        }
        save_config(config)
        update.message.reply_text(f"تمت إضافة المجموعة {group_id} بنجاح.")
    
    return back_to_admin(update, context)

def group_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    group_id = query.data.split("_")[1]
    
    config = load_config()
    group_info = config["groups"].get(group_id, {})
    
    text = f"إدارة المجموعة: {group_id}\n"
    text += f"TOTP_SECRET: {'*****' if group_info.get('totp_secret') else 'غير مضبوط'}\n"
    text += f"فترة التكرار: كل {group_info.get('interval', 10)} دقائق\n"
    text += f"الحالة: {'نشط' if group_info.get('active', False) else 'غير نشط'}"
    
    query.edit_message_text(
        text=text,
        reply_markup=group_management_keyboard(group_id),
    )
    return MANAGE_TOTP

def add_totp(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    group_id = query.data.split("_")[2]
    context.user_data["current_group"] = group_id
    query.edit_message_text(text=f"أرسل TOTP_SECRET للمجموعة {group_id}:")
    return ADD_TOTP

def process_add_totp(update: Update, context: CallbackContext):
    totp_secret = update.message.text.strip()
    group_id = context.user_data["current_group"]
    
    if not is_valid_secret(totp_secret):
        update.message.reply_text("TOTP_SECRET غير صالح. الرجاء إدخال سر صالح.")
        return ADD_TOTP
    
    config = load_config()
    if group_id in config["groups"]:
        config["groups"][group_id]["totp_secret"] = totp_secret
        save_config(config)
        update.message.reply_text(f"تمت إضافة TOTP_SECRET للمجموعة {group_id} بنجاح.")
    else:
        update.message.reply_text("المجموعة غير موجودة. الرجاء إضافتها أولاً.")
    
    return back_to_admin(update, context)

def delete_group(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    group_id = query.data.split("_")[2]
    
    config = load_config()
    if group_id in config["groups"]:
        del config["groups"][group_id]
        save_config(config)
        query.edit_message_text(f"تم حذف المجموعة {group_id} بنجاح.")
    else:
        query.edit_message_text("المجموعة غير موجودة.")
    
    return back_to_admin(update, context)

# إدارة فترة التكرار
def set_interval(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="اختر فترة تكرار إرسال رمز المصادقة:",
        reply_markup=interval_keyboard(),
    )
    return SET_INTERVAL

def process_interval(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    interval = int(query.data.split("_")[1])
    
    config = load_config()
    for group_id in config["groups"]:
        config["groups"][group_id]["interval"] = interval
    save_config(config)
    
    query.edit_message_text(
        text=f"تم ضبط فترة التكرار على كل {interval} دقائق لجميع المجموعات.",
        reply_markup=interval_keyboard(),
    )
    return SET_INTERVAL

def start_interval(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    config = load_config()
    for group_id in config["groups"]:
        config["groups"][group_id]["active"] = True
        config["groups"][group_id]["next_run"] = time.time()
    save_config(config)
    
    query.edit_message_text(
        text="تم تفعيل الإرسال الدوري لجميع المجموعات.",
        reply_markup=interval_keyboard(),
    )
    return SET_INTERVAL

# إدارة شكل الرسالة والتوقيت
def set_message_style(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="اختر شكل الرسالة التي تريد عرضها في المجموعة:",
        reply_markup=message_style_keyboard(),
    )
    return SET_MESSAGE_STYLE

def process_message_style(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    style = int(query.data.split("_")[1])
    
    config = load_config()
    config["message_style"] = style
    save_config(config)
    
    query.edit_message_text(
        text=f"تم تغيير شكل الرسالة إلى النمط {style}.",
        reply_markup=message_style_keyboard(),
    )
    return SET_MESSAGE_STYLE

def change_timezone(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="اختر المنطقة الزمنية:",
        reply_markup=timezone_keyboard(),
    )
    return SET_TIMEZONE

def process_timezone(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    tz = query.data.split("_")[1]
    
    config = load_config()
    config["timezone"] = tz
    save_config(config)
    
    query.edit_message_text(
        text=f"تم تغيير المنطقة الزمنية إلى {tz}.",
        reply_markup=message_style_keyboard(),
    )
    return SET_MESSAGE_STYLE

# إدارة المسؤولين
def manage_admins(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="إدارة المسؤولين:",
        reply_markup=admins_management_keyboard(),
    )
    return MANAGE_ADMINS

def add_admin(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="أرسل معرف المستخدم (User ID) الذي تريد إضافته كمسؤول:")
    return ADD_ADMIN

def process_add_admin(update: Update, context: CallbackContext):
    try:
        new_admin_id = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("معرف المستخدم يجب أن يكون رقماً. الرجاء إدخال معرف صحيح.")
        return ADD_ADMIN
    
    config = load_config()
    if new_admin_id in config["admins"]:
        update.message.reply_text("هذا المستخدم مسؤول بالفعل.")
    else:
        config["admins"].append(new_admin_id)
        save_config(config)
        update.message.reply_text(f"تمت إضافة المستخدم {new_admin_id} كمسؤول بنجاح.")
    
    return back_to_admin(update, context)

def remove_admin(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(text="أرسل معرف المستخدم (User ID) الذي تريد إزالته من المسؤولين:")
    return REMOVE_ADMIN

def process_remove_admin(update: Update, context: CallbackContext):
    try:
        admin_id = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("معرف المستخدم يجب أن يكون رقماً. الرجاء إدخال معرف صحيح.")
        return REMOVE_ADMIN
    
    config = load_config()
    if admin_id == ADMIN_ID:
        update.message.reply_text("لا يمكن إزالة المسؤول الرئيسي.")
    elif admin_id in config["admins"]:
        config["admins"].remove(admin_id)
        save_config(config)
        update.message.reply_text(f"تمت إزالة المستخدم {admin_id} من المسؤولين بنجاح.")
    else:
        update.message.reply_text("هذا المستخدم ليس مسؤولاً.")
    
    return back_to_admin(update, context)

# إدارة محاولات المستخدمين
def manage_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="إدارة محاولات المستخدمين:",
        reply_markup=attempts_management_keyboard(),
    )
    return MANAGE_ATTEMPTS

def select_group_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    config = load_config()
    users = load_users()
    
    keyboard = []
    for group_id in config["groups"]:
        # حساب عدد المستخدمين في هذه المجموعة
        user_count = sum(1 for user_data in users.values() if group_id in user_data.get("attempts", {}))
        keyboard.append([
            InlineKeyboardButton(
                f"المجموعة: {group_id} ({user_count} مستخدم)",
                callback_data=f"select_group_{group_id}",
            ),
        ])
    
    keyboard.append([
        InlineKeyboardButton("رجوع", callback_data="manage_attempts"),
    ])
    
    query.edit_message_text(
        text="اختر المجموعة لعرض مستخدميها:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_GROUP_ATTEMPTS

def process_select_group_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    group_id = query.data.split("_")[2]
    context.user_data["current_group_attempts"] = group_id
    
    users = load_users()
    group_users = []
    
    for user_id, user_data in users.items():
        if group_id in user_data.get("attempts", {}):
            attempts = user_data["attempts"][group_id]
            group_users.append((user_id, attempts))
    
    if not group_users:
        query.edit_message_text(
            text="لا يوجد مستخدمين في هذه المجموعة.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("رجوع", callback_data="select_group_attempts")],
            ]),
        )
        return SELECT_GROUP_ATTEMPTS
    
    keyboard = []
    for user_id, attempts in group_users:
        try:
            user = context.bot.get_chat(user_id)
            name = user.first_name or user.username or str(user_id)
        except:
            name = str(user_id)
        
        keyboard.append([
            InlineKeyboardButton(
                f"{name} (المحاولات: {attempts})",
                callback_data=f"select_user_{group_id}_{user_id}",
            ),
        ])
    
    keyboard.append([
        InlineKeyboardButton("رجوع", callback_data="select_group_attempts"),
    ])
    
    query.edit_message_text(
        text=f"مستخدمي المجموعة {group_id}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_USER_ATTEMPTS

def process_select_user_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, _, group_id, user_id = query.data.split("_")
    user_id = int(user_id)
    
    users = load_users()
    attempts = users.get(str(user_id), {}).get("attempts", {}).get(group_id, 0)
    
    try:
        user = context.bot.get_chat(user_id)
        name = user.first_name or user.username or str(user_id)
    except:
        name = str(user_id)
    
    config = load_config()
    banned = user_id in config.get("banned_users", [])
    
    text = f"إدارة محاولات المستخدم:\n"
    text += f"الاسم: {name}\n"
    text += f"المعرف: {user_id}\n"
    text += f"المجموعة: {group_id}\n"
    text += f"المحاولات المتبقية: {attempts}\n"
    text += f"الحالة: {'محظور' if banned else 'نشط'}"
    
    query.edit_message_text(
        text=text,
        reply_markup=user_attempts_keyboard(group_id, user_id),
    )
    return SELECT_USER_ATTEMPTS

def ban_user(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, _, group_id, user_id = query.data.split("_")
    user_id = int(user_id)
    
    config = load_config()
    if user_id not in config.get("banned_users", []):
        config["banned_users"].append(user_id)
        save_config(config)
        query.edit_message_text(text=f"تم حظر المستخدم {user_id} بنجاح.")
    else:
        config["banned_users"].remove(user_id)
        save_config(config)
        query.edit_message_text(text=f"تم إلغاء حظر المستخدم {user_id} بنجاح.")
    
    return process_select_user_attempts(update, context)

def add_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, _, group_id, user_id = query.data.split("_")
    context.user_data["current_user_attempts"] = (group_id, int(user_id))
    query.edit_message_text(text="أرسل عدد المحاولات التي تريد إضافتها:")
    return ADD_ATTEMPTS

def process_add_attempts(update: Update, context: CallbackContext):
    try:
        attempts = int(update.message.text.strip())
        if attempts <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("الرجاء إدخال عدد صحيح موجب.")
        return ADD_ATTEMPTS
    
    group_id, user_id = context.user_data["current_user_attempts"]
    
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {"attempts": {}}
    
    if group_id not in users[str(user_id)]["attempts"]:
        users[str(user_id)]["attempts"][group_id] = 0
    
    users[str(user_id)]["attempts"][group_id] += attempts
    save_users(users)
    
    update.message.reply_text(f"تمت إضافة {attempts} محاولة للمستخدم {user_id} في المجموعة {group_id} بنجاح.")
    return back_to_admin(update, context)

def remove_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    _, _, group_id, user_id = query.data.split("_")
    context.user_data["current_user_attempts"] = (group_id, int(user_id))
    query.edit_message_text(text="أرسل عدد المحاولات التي تريد حذفها:")
    return REMOVE_ATTEMPTS

def process_remove_attempts(update: Update, context: CallbackContext):
    try:
        attempts = int(update.message.text.strip())
        if attempts <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("الرجاء إدخال عدد صحيح موجب.")
        return REMOVE_ATTEMPTS
    
    group_id, user_id = context.user_data["current_user_attempts"]
    
    users = load_users()
    if str(user_id) not in users or group_id not in users[str(user_id)].get("attempts", {}):
        update.message.reply_text("هذا المستخدم ليس لديه محاولات في هذه المجموعة.")
        return back_to_admin(update, context)
    
    current_attempts = users[str(user_id)]["attempts"][group_id]
    if attempts > current_attempts:
        attempts = current_attempts
    
    users[str(user_id)]["attempts"][group_id] -= attempts
    
    if users[str(user_id)]["attempts"][group_id] <= 0:
        del users[str(user_id)]["attempts"][group_id]
        if not users[str(user_id)]["attempts"]:
            del users[str(user_id)]["attempts"]
    
    save_users(users)
    
    update.message.reply_text(f"تم حذف {attempts} محاولة من المستخدم {user_id} في المجموعة {group_id} بنجاح.")
    return back_to_admin(update, context)

# إرسال الرسائل الدورية
def send_periodic_messages(context: CallbackContext):
    config = load_config()
    users = load_users()
    current_time = time.time()
    
    for group_id, group_data in config["groups"].items():
        if not group_data["active"] or not group_data["totp_secret"]:
            continue
        
        if group_data["next_run"] is None or current_time >= group_data["next_run"]:
            # توليد وإرسال الرسالة
            send_2fa_message(context.bot, group_id, group_data["totp_secret"], config)
            
            # تحديث وقت التشغيل التالي
            interval_seconds = group_data["interval"] * 60
            config["groups"][group_id]["next_run"] = current_time + interval_seconds
            save_config(config)

def send_2fa_message(bot, group_id, totp_secret, config):
    try:
        # توليد رمز المصادقة
        code = generate_2fa_code(totp_secret)
        
        # حساب الوقت المتبقي والوقت التالي
        current_time = get_current_time(config["timezone"])
        remaining_seconds = 30 - (current_time.second % 30)
        next_time = current_time + timedelta(seconds=remaining_seconds)
        
        # بناء الرسالة حسب النمط المختار
        if config["message_style"] == 1:
            message = "🔐 2FA Verification Code\n\n"
            message += f"Next code at: {format_time(next_time)}"
        elif config["message_style"] == 2:
            message = "🔐 2FA Verification Code\n\n"
            minutes = config["groups"][group_id]["interval"]
            message += f"Next code in: {minutes} minutes\n"
            message += f"Next code at: {format_time(next_time)}"
        else:  # النمط 3
            message = "🔐 2FA Verification Code\n"
            minutes = config["groups"][group_id]["interval"]
            message += f"Next code in: {minutes} minutes\n"
            message += f"Correct Time: {format_time(current_time)}\n"
            message += f"Next Code at: {format_time(next_time)}"
        
        # إضافة زر النسخ
        keyboard = [[
            InlineKeyboardButton("Copy Code", callback_data=f"get_code_{group_id}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال الرسالة إلى المجموعة
        bot.send_message(
            chat_id=group_id,
            text=message,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Error sending 2FA message to group {group_id}: {e}")

def handle_code_request(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    # استخراج بيانات الطلب
    _, _, group_id = query.data.split("_")
    user_id = query.from_user.id
    
    # التحقق من الحظر
    config = load_config()
    if user_id in config.get("banned_users", []):
        query.edit_message_text(text="تم حظرك من استخدام هذه الميزة.")
        return
    
    # التحقق من المحاولات المتبقية
    users = load_users()
    user_data = users.get(str(user_id), {})
    attempts = user_data.get("attempts", {}).get(group_id, 0)
    
    if attempts <= 0:
        query.edit_message_text(text="لا يوجد لديك محاولات متبقية. الرجاء الانتظار حتى منتصف الليل.")
        return
    
    # توليد وإرسال الرمز
    group_data = config["groups"].get(group_id, {})
    if not group_data or not group_data.get("totp_secret"):
        query.edit_message_text(text="حدث خطأ في توليد الرمز. الرجاء إعلام المسؤول.")
        return
    
    code = generate_2fa_code(group_data["totp_secret"])
    remaining_time = 30 - (get_current_time(config["timezone"]).second % 30)
    
    # تحديث المحاولات المتبقية
    users[str(user_id)] = users.get(str(user_id), {})
    users[str(user_id)]["attempts"] = users[str(user_id)].get("attempts", {})
    users[str(user_id)]["attempts"][group_id] = attempts - 1
    save_users(users)
    
    # إرسال الرسالة الخاصة
    try:
        context.bot.send_message(
            chat_id=user_id,
            text=f"🔐 رمز المصادقة:\n\n"
                 f"`{code}`\n\n"
                 f"المحاولات المتبقية: {attempts - 1}\n"
                 f"تحذير: هذا الرمز صالح لمدة {remaining_time} ثانية فقط!\n\n"
                 f"الوقت المتبقي: {remaining_time} ثانية",
            parse_mode="Markdown",
        )
        query.edit_message_text(text="تم إرسال رمز المصادقة إليك في الرسائل الخاصة.")
    except Exception as e:
        logger.error(f"Error sending private message to user {user_id}: {e}")
        query.edit_message_text(text="لا يمكن إرسال الرسالة الخاصة. الرجاء التأكد من أنك بدأت محادثة مع البوت.")

# إعادة تعيين المحاولات اليومية
def reset_daily_attempts(context: CallbackContext):
    users = load_users()
    for user_data in users.values():
        if "attempts" in user_data:
            del user_data["attempts"]
    save_users(users)
    logger.info("تم إعادة تعيين المحاولات اليومية لجميع المستخدمين.")

# تهيئة البوت
def main():
    # إنشاء المحدث وتحديث البيانات
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # إعداد المحادثة مع المسؤول
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_command)],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(manage_groups, pattern="^manage_groups$"),
                CallbackQueryHandler(set_interval, pattern="^set_interval$"),
                CallbackQueryHandler(set_message_style, pattern="^set_message_style$"),
                CallbackQueryHandler(manage_attempts, pattern="^manage_attempts$"),
                CallbackQueryHandler(manage_admins, pattern="^manage_admins

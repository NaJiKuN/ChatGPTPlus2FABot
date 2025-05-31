#!/usr/bin/env python3
import os
import time
import pytz
from datetime import datetime, timedelta
import threading
from typing import Dict, List, Tuple, Optional
import logging
import json
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
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)

# تكوين التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMIN_ID = 764559466  # يمكن تحويله إلى قائمة إذا كان هناك عدة مسؤولين

# حالات المحادثة
(
    GROUP_ID_INPUT,
    TOTP_SECRET_INPUT,
    GROUP_MANAGEMENT,
    TOTP_MANAGEMENT,
    INTERVAL_MANAGEMENT,
    MESSAGE_STYLE_MANAGEMENT,
    USER_ATTEMPTS_MANAGEMENT,
    ADMIN_MANAGEMENT,
    SELECT_GROUP_FOR_ATTEMPTS,
    SELECT_USER_FOR_ATTEMPTS,
    ADD_ATTEMPTS,
    REMOVE_ATTEMPTS,
    BAN_USER,
    TIMEZONE_SELECTION,
    ADD_ADMIN,
    REMOVE_ADMIN,
) = range(16)

# مسار ملف البيانات
DATA_FILE = "chatgptplus2fabot_data.json"

# تهيئة البيانات
def load_data() -> Dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "groups": {},
        "admins": [ADMIN_ID],
        "user_attempts": {},
        "message_style": 1,
        "timezone": "Asia/Gaza",
        "banned_users": [],
    }

def save_data(data: Dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# فئة لإدارة TOTP
class TOTPManager:
    def __init__(self):
        self.data = load_data()
        self.lock = threading.Lock()
        self.active_timers = {}

    def get_totp_code(self, group_id: str) -> Optional[str]:
        with self.lock:
            group = self.data["groups"].get(group_id)
            if group and "totp_secret" in group:
                totp = pyotp.TOTP(group["totp_secret"])
                return totp.now()
        return None

    def get_next_code_time(self, group_id: str) -> Optional[datetime]:
        with self.lock:
            group = self.data["groups"].get(group_id)
            if group and "totp_secret" in group:
                totp = pyotp.TOTP(group["totp_secret"])
                now = datetime.now(pytz.timezone(self.data.get("timezone", "Asia/Gaza")))
                return now + timedelta(seconds=30 - (now.timestamp() % 30))
        return None

    def get_next_scheduled_time(self, group_id: str) -> Optional[datetime]:
        with self.lock:
            group = self.data["groups"].get(group_id)
            if group and "interval" in group and group["interval"] > 0:
                last_sent = datetime.fromisoformat(group.get("last_sent", datetime.min.isoformat()))
                interval = timedelta(minutes=group["interval"])
                next_time = last_sent + interval
                return next_time if next_time > datetime.now() else datetime.now()
        return None

    def update_group(self, group_id: str, updates: Dict):
        with self.lock:
            if group_id not in self.data["groups"]:
                self.data["groups"][group_id] = {}
            self.data["groups"][group_id].update(updates)
            save_data(self.data)
            self.schedule_group_message(group_id)

    def schedule_group_message(self, group_id: str):
        with self.lock:
            group = self.data["groups"].get(group_id)
            if not group or "interval" not in group or group["interval"] <= 0:
                if group_id in self.active_timers:
                    self.active_timers[group_id].cancel()
                    del self.active_timers[group_id]
                return

            next_time = self.get_next_scheduled_time(group_id)
            if not next_time:
                return

            delay = (next_time - datetime.now()).total_seconds()
            if delay <= 0:
                delay = 0.1  # تأخير صغير لإرسال الرسالة فوراً

            if group_id in self.active_timers:
                self.active_timers[group_id].cancel()

            timer = threading.Timer(delay, self.send_group_message, args=[group_id])
            timer.start()
            self.active_timers[group_id] = timer

    def send_group_message(self, group_id: str):
        with self.lock:
            group = self.data["groups"].get(group_id)
            if not group:
                return

            # تحديث وقت الإرسال الأخير
            group["last_sent"] = datetime.now().isoformat()
            save_data(self.data)

            # إرسال الرسالة إلى المجموعة
            bot = Bot(TOKEN)
            try:
                message = self.format_group_message(group_id)
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Copy Code", callback_data=f"copy_code:{group_id}")]
                ])
                bot.send_message(chat_id=group_id, text=message, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error sending message to group {group_id}: {e}")

            # جدولة الرسالة التالية
            self.schedule_group_message(group_id)

    def format_group_message(self, group_id: str) -> str:
        group = self.data["groups"].get(group_id, {})
        interval = group.get("interval", 10)
        timezone = pytz.timezone(self.data.get("timezone", "Asia/Gaza"))
        now = datetime.now(timezone)
        next_code_time = self.get_next_code_time(group_id)
        next_scheduled_time = self.get_next_scheduled_time(group_id)

        if self.data["message_style"] == 1:
            return f"""🔐 2FA Verification Code

Next code at: {next_code_time.strftime('%I:%M:%S %p') if next_code_time else 'N/A'}"""
        elif self.data["message_style"] == 2:
            if next_scheduled_time:
                time_remaining = next_scheduled_time - now
                minutes = int(time_remaining.total_seconds() // 60)
                return f"""🔐 2FA Verification Code

Next code in: {minutes} minutes

Next code at: {next_scheduled_time.strftime('%I:%M:%S %p')}"""
        else:
            if next_scheduled_time:
                time_remaining = next_scheduled_time - now
                minutes = int(time_remaining.total_seconds() // 60)
                return f"""🔐 2FA Verification Code
Next code in: {minutes} minutes
Current Time: {now.strftime('%I:%M:%S %p')}
Next Code at: {next_scheduled_time.strftime('%I:%M:%S %p')}"""

        return "🔐 2FA Verification Code"

    def get_user_attempts(self, user_id: int) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        if str(user_id) not in self.data["user_attempts"]:
            self.data["user_attempts"][str(user_id)] = {}
        if today not in self.data["user_attempts"][str(user_id)]:
            self.data["user_attempts"][str(user_id)][today] = {"used": 0, "allowed": 5}
            save_data(self.data)
        return self.data["user_attempts"][str(user_id)][today]

    def update_user_attempts(self, user_id: int, added: int = 0, removed: int = 0):
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            if str(user_id) not in self.data["user_attempts"]:
                self.data["user_attempts"][str(user_id)] = {}
            if today not in self.data["user_attempts"][str(user_id)]:
                self.data["user_attempts"][str(user_id)][today] = {"used": 0, "allowed": 5}
            
            attempts = self.data["user_attempts"][str(user_id)][today]
            attempts["allowed"] += added
            attempts["allowed"] -= removed
            if attempts["allowed"] < 0:
                attempts["allowed"] = 0
            save_data(self.data)

    def use_user_attempt(self, user_id: int) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            if str(user_id) not in self.data["user_attempts"]:
                self.data["user_attempts"][str(user_id)] = {}
            if today not in self.data["user_attempts"][str(user_id)]:
                self.data["user_attempts"][str(user_id)][today] = {"used": 0, "allowed": 5}
            
            attempts = self.data["user_attempts"][str(user_id)][today]
            if attempts["used"] >= attempts["allowed"]:
                return False
            
            attempts["used"] += 1
            save_data(self.data)
            return True

    def ban_user(self, user_id: int):
        with self.lock:
            if user_id not in self.data["banned_users"]:
                self.data["banned_users"].append(user_id)
                save_data(self.data)

    def unban_user(self, user_id: int):
        with self.lock:
            if user_id in self.data["banned_users"]:
                self.data["banned_users"].remove(user_id)
                save_data(self.data)

    def is_user_banned(self, user_id: int) -> bool:
        return user_id in self.data["banned_users"]

    def add_admin(self, user_id: int):
        with self.lock:
            if user_id not in self.data["admins"]:
                self.data["admins"].append(user_id)
                save_data(self.data)

    def remove_admin(self, user_id: int):
        with self.lock:
            if user_id in self.data["admins"] and user_id != ADMIN_ID:
                self.data["admins"].remove(user_id)
                save_data(self.data)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.data["admins"]

# تهيئة المدير
totp_manager = TOTPManager()

# وظائف المساعدين
def is_admin(user_id: int) -> bool:
    return totp_manager.is_admin(user_id)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("إدارة Groups/TOTP_SECRET", callback_data="manage_groups")],
        [InlineKeyboardButton("إدارة فترة التكرار", callback_data="manage_interval")],
        [InlineKeyboardButton("إدارة شكل/توقيت الرسالة", callback_data="manage_message_style")],
        [InlineKeyboardButton("إدارة محاولات المستخدمين", callback_data="manage_user_attempts")],
        [InlineKeyboardButton("إدارة المسؤولين", callback_data="manage_admins")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_management_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("إضافة مجموعة", callback_data="add_group")],
        [InlineKeyboardButton("حذف مجموعة", callback_data="remove_group")],
        [InlineKeyboardButton("تعديل TOTP_SECRET", callback_data="edit_totp")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_interval_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("1 دقيقة", callback_data="interval_1")],
        [InlineKeyboardButton("5 دقائق", callback_data="interval_5")],
        [InlineKeyboardButton("10 دقائق", callback_data="interval_10")],
        [InlineKeyboardButton("15 دقيقة", callback_data="interval_15")],
        [InlineKeyboardButton("30 دقيقة", callback_data="interval_30")],
        [InlineKeyboardButton("ساعة", callback_data="interval_60")],
        [InlineKeyboardButton("3 ساعات", callback_data="interval_180")],
        [InlineKeyboardButton("12 ساعة", callback_data="interval_720")],
        [InlineKeyboardButton("24 ساعة", callback_data="interval_1440")],
        [InlineKeyboardButton("إيقاف التكرار", callback_data="interval_0")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_message_style_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("الشكل الأول", callback_data="style_1")],
        [InlineKeyboardButton("الشكل الثاني", callback_data="style_2")],
        [InlineKeyboardButton("الشكل الثالث", callback_data="style_3")],
        [InlineKeyboardButton("تغيير التوقيت", callback_data="change_timezone")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timezone_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("توقيت غرينتش (UTC)", callback_data="timezone_UTC")],
        [InlineKeyboardButton("توقيت غزة (Asia/Gaza)", callback_data="timezone_Asia/Gaza")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_message_style")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_attempts_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("حدد عدد مرات النسخ", callback_data="set_copy_attempts")],
        [InlineKeyboardButton("حظر مستخدم", callback_data="ban_user")],
        [InlineKeyboardButton("إلغاء حظر مستخدم", callback_data="unban_user")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_management_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("إضافة مسؤول", callback_data="add_admin")],
        [InlineKeyboardButton("إزالة مسؤول", callback_data="remove_admin")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_admin")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_groups_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for group_id in totp_manager.data["groups"]:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id}", callback_data=f"select_group:{group_id}")])
    keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_user_attempts")])
    return InlineKeyboardMarkup(keyboard)

def get_users_keyboard(group_id: str) -> InlineKeyboardMarkup:
    keyboard = []
    # هذه وظيفة مبسطة، في التطبيق الحقيقي قد تحتاج إلى تسجيل المستخدمين الذين تفاعلوا مع البوت
    keyboard.append([InlineKeyboardButton("جميع المستخدمين", callback_data=f"all_users:{group_id}")])
    keyboard.append([InlineKeyboardButton("رجوع", callback_data="back_to_select_group")])
    return InlineKeyboardMarkup(keyboard)

def get_user_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("حظر المستخدم", callback_data=f"ban:{user_id}")],
        [InlineKeyboardButton("إضافة محاولات", callback_data=f"add_attempts:{user_id}")],
        [InlineKeyboardButton("حذف محاولات", callback_data=f"remove_attempts:{user_id}")],
        [InlineKeyboardButton("رجوع", callback_data="back_to_select_user")],
    ]
    return InlineKeyboardMarkup(keyboard)

# معالجات الأوامر
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if is_admin(user_id):
        update.message.reply_text(
            "مرحباً بك في ChatGPTPlus2FABot!\nاستخدم الأمر /admin للوصول إلى لوحة التحكم.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        update.message.reply_text(
            "مرحباً! هذا البوت مخصص لإرسال رموز المصادقة الثنائية. لا يمكنك الوصول إلى لوحة التحكم.",
            reply_markup=ReplyKeyboardRemove(),
        )

def admin_panel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return

    update.message.reply_text(
        "لوحة تحكم المسؤول:",
        reply_markup=get_admin_keyboard(),
    )

# معالجات الاستدعاء
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if not is_admin(query.from_user.id):
        query.edit_message_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return

    if data == "manage_groups":
        query.edit_message_text(
            "إدارة المجموعات ورموز TOTP_SECRET:",
            reply_markup=get_group_management_keyboard(),
        )
    elif data == "manage_interval":
        query.edit_message_text(
            "إدارة فترة التكرار:",
            reply_markup=get_interval_keyboard(),
        )
    elif data == "manage_message_style":
        query.edit_message_text(
            "إدارة شكل/توقيت الرسالة:",
            reply_markup=get_message_style_keyboard(),
        )
    elif data == "manage_user_attempts":
        query.edit_message_text(
            "إدارة محاولات المستخدمين:",
            reply_markup=get_user_attempts_keyboard(),
        )
    elif data == "manage_admins":
        query.edit_message_text(
            "إدارة المسؤولين:",
            reply_markup=get_admin_management_keyboard(),
        )
    elif data == "back_to_admin":
        query.edit_message_text(
            "لوحة تحكم المسؤول:",
            reply_markup=get_admin_keyboard(),
        )
    elif data == "add_group":
        context.user_data["management_action"] = "add_group"
        query.edit_message_text(
            "أدخل معرف المجموعة (GROUP_ID) التي تريد إضافتها:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_groups")]]),
        )
        return GROUP_ID_INPUT
    elif data == "remove_group":
        context.user_data["management_action"] = "remove_group"
        query.edit_message_text(
            "أدخل معرف المجموعة (GROUP_ID) التي تريد حذفها:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_groups")]]),
        )
        return GROUP_ID_INPUT
    elif data == "edit_totp":
        context.user_data["management_action"] = "edit_totp"
        query.edit_message_text(
            "أدخل معرف المجموعة (GROUP_ID) التي تريد تعديل TOTP_SECRET لها:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_groups")]]),
        )
        return GROUP_ID_INPUT
    elif data.startswith("interval_"):
        interval = int(data.split("_")[1])
        if "selected_group" in context.user_data:
            group_id = context.user_data["selected_group"]
            totp_manager.update_group(group_id, {"interval": interval})
            query.edit_message_text(
                f"تم تعيين فترة التكرار لـ {interval} دقيقة للمجموعة {group_id}.",
                reply_markup=get_interval_keyboard(),
            )
        else:
            query.edit_message_text(
                "الرجاء تحديد مجموعة أولاً عن طريق إدارة المجموعات.",
                reply_markup=get_interval_keyboard(),
            )
    elif data.startswith("style_"):
        style = int(data.split("_")[1])
        with totp_manager.lock:
            totp_manager.data["message_style"] = style
            save_data(totp_manager.data)
        query.edit_message_text(
            f"تم تغيير شكل الرسالة إلى النمط {style}.",
            reply_markup=get_message_style_keyboard(),
        )
    elif data == "change_timezone":
        query.edit_message_text(
            "اختر المنطقة الزمنية:",
            reply_markup=get_timezone_keyboard(),
        )
    elif data.startswith("timezone_"):
        timezone = data.split("_")[1]
        with totp_manager.lock:
            totp_manager.data["timezone"] = timezone
            save_data(totp_manager.data)
        query.edit_message_text(
            f"تم تغيير المنطقة الزمنية إلى {timezone}.",
            reply_markup=get_message_style_keyboard(),
        )
    elif data == "back_to_message_style":
        query.edit_message_text(
            "إدارة شكل/توقيت الرسالة:",
            reply_markup=get_message_style_keyboard(),
        )
    elif data == "set_copy_attempts":
        query.edit_message_text(
            "اختر المجموعة:",
            reply_markup=get_groups_keyboard(),
        )
        return SELECT_GROUP_FOR_ATTEMPTS
    elif data == "ban_user":
        context.user_data["management_action"] = "ban_user"
        query.edit_message_text(
            "أدخل معرف المستخدم (User ID) الذي تريد حظره:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_user_attempts")]]),
        )
        return BAN_USER
    elif data == "unban_user":
        context.user_data["management_action"] = "unban_user"
        query.edit_message_text(
            "أدخل معرف المستخدم (User ID) الذي تريد إلغاء حظره:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_user_attempts")]]),
        )
        return BAN_USER
    elif data == "add_admin":
        context.user_data["management_action"] = "add_admin"
        query.edit_message_text(
            "أدخل معرف المستخدم (User ID) الذي تريد إضافته كمسؤول:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_admins")]]),
        )
        return ADD_ADMIN
    elif data == "remove_admin":
        context.user_data["management_action"] = "remove_admin"
        query.edit_message_text(
            "أدخل معرف المستخدم (User ID) الذي تريد إزالته من المسؤولين:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="manage_admins")]]),
        )
        return REMOVE_ADMIN
    elif data.startswith("select_group:"):
        group_id = data.split(":")[1]
        context.user_data["selected_group"] = group_id
        query.edit_message_text(
            f"اختر المستخدم من المجموعة {group_id}:",
            reply_markup=get_users_keyboard(group_id),
        )
        return SELECT_USER_FOR_ATTEMPTS
    elif data.startswith("all_users:"):
        group_id = data.split(":")[1]
        context.user_data["selected_group"] = group_id
        query.edit_message_text(
            f"جميع مستخدمي المجموعة {group_id}. أدخل معرف المستخدم (User ID) الذي تريد إدارة محاولاته:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="set_copy_attempts")]]),
        )
        return SELECT_USER_FOR_ATTEMPTS
    elif data.startswith("ban:"):
        user_id = int(data.split(":")[1])
        totp_manager.ban_user(user_id)
        query.edit_message_text(
            f"تم حظر المستخدم {user_id} بنجاح.",
            reply_markup=get_user_attempts_keyboard(),
        )
        return ConversationHandler.END
    elif data.startswith("add_attempts:"):
        user_id = int(data.split(":")[1])
        context.user_data["selected_user"] = user_id
        context.user_data["attempt_action"] = "add"
        query.edit_message_text(
            f"أدخل عدد المحاولات التي تريد إضافتها للمستخدم {user_id}:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="set_copy_attempts")]]),
        )
        return ADD_ATTEMPTS
    elif data.startswith("remove_attempts:"):
        user_id = int(data.split(":")[1])
        context.user_data["selected_user"] = user_id
        context.user_data["attempt_action"] = "remove"
        query.edit_message_text(
            f"أدخل عدد المحاولات التي تريد حذفها من المستخدم {user_id}:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="set_copy_attempts")]]),
        )
        return REMOVE_ATTEMPTS
    elif data == "back_to_select_group":
        query.edit_message_text(
            "اختر المجموعة:",
            reply_markup=get_groups_keyboard(),
        )
        return SELECT_GROUP_FOR_ATTEMPTS
    elif data == "back_to_select_user":
        if "selected_group" in context.user_data:
            group_id = context.user_data["selected_group"]
            query.edit_message_text(
                f"اختر المستخدم من المجموعة {group_id}:",
                reply_markup=get_users_keyboard(group_id),
            )
            return SELECT_USER_FOR_ATTEMPTS
    elif data == "back_to_user_attempts":
        query.edit_message_text(
            "إدارة محاولات المستخدمين:",
            reply_markup=get_user_attempts_keyboard(),
        )
        return ConversationHandler.END
    elif data.startswith("copy_code:"):
        group_id = data.split(":")[1]
        user_id = query.from_user.id
        
        if totp_manager.is_user_banned(user_id):
            query.answer("تم حظرك من استخدام هذه الخدمة.", show_alert=True)
            return
        
        attempts = totp_manager.get_user_attempts(user_id)
        if attempts["used"] >= attempts["allowed"]:
            query.answer(
                f"لقد استنفذت جميع محاولاتك اليومية ({attempts['used']}/{attempts['allowed']}). يرجى المحاولة مرة أخرى بعد منتصف الليل.",
                show_alert=True,
            )
            return
        
        code = totp_manager.get_totp_code(group_id)
        if not code:
            query.answer("خطأ في توليد الرمز. يرجى إعلام المسؤول.", show_alert=True)
            return
        
        if totp_manager.use_user_attempt(user_id):
            remaining = attempts["allowed"] - attempts["used"] - 1
            message = f"""🔐 رمز المصادقة الثنائية:
            
{code}

❗ هذا الرمز صالح لمدة 30 ثانية فقط.
🔄 المحاولات المتبقية اليوم: {remaining}"""
            
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                )
                query.answer("تم إرسال الرمز إليك في الرسائل الخاصة.", show_alert=True)
            except Exception as e:
                query.answer("فشل إرسال الرسالة. يرجى التأكد من أنك بدأت محادثة مع البوت.", show_alert=True)
                logger.error(f"Failed to send DM to user {user_id}: {e}")
        else:
            query.answer("خطأ في استخدام المحاولة. يرجى المحاولة مرة أخرى.", show_alert=True)

    return ConversationHandler.END

# معالجات المحادثة
def group_id_input(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return ConversationHandler.END

    group_id = update.message.text
    action = context.user_data.get("management_action")

    if action == "add_group":
        if group_id in totp_manager.data["groups"]:
            update.message.reply_text(f"المجموعة {group_id} موجودة بالفعل.")
        else:
            totp_manager.update_group(group_id, {})
            update.message.reply_text(f"تمت إضافة المجموعة {group_id} بنجاح.")
        return ConversationHandler.END
    elif action == "remove_group":
        if group_id in totp_manager.data["groups"]:
            with totp_manager.lock:
                del totp_manager.data["groups"][group_id]
                save_data(totp_manager.data)
            update.message.reply_text(f"تم حذف المجموعة {group_id} بنجاح.")
        else:
            update.message.reply_text(f"المجموعة {group_id} غير موجودة.")
        return ConversationHandler.END
    elif action == "edit_totp":
        context.user_data["selected_group"] = group_id
        update.message.reply_text(
            f"أدخل TOTP_SECRET الجديد للمجموعة {group_id}:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TOTP_SECRET_INPUT

def totp_secret_input(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return ConversationHandler.END

    totp_secret = update.message.text
    group_id = context.user_data.get("selected_group")

    try:
        # التحقق من أن الرمز صالح
        totp = pyotp.TOTP(totp_secret)
        totp.now()
        
        totp_manager.update_group(group_id, {"totp_secret": totp_secret})
        update.message.reply_text(f"تم تحديث TOTP_SECRET للمجموعة {group_id} بنجاح.")
    except Exception as e:
        update.message.reply_text(f"خطأ في TOTP_SECRET: {e}. يرجى إدخال رمز صالح.")

    return ConversationHandler.END

def select_group_for_attempts(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data.startswith("select_group:"):
        group_id = query.data.split(":")[1]
        context.user_data["selected_group"] = group_id
        query.edit_message_text(
            f"اختر المستخدم من المجموعة {group_id}:",
            reply_markup=get_users_keyboard(group_id),
        )
    elif query.data == "back_to_user_attempts":
        query.edit_message_text(
            "إدارة محاولات المستخدمين:",
            reply_markup=get_user_attempts_keyboard(),
        )
        return ConversationHandler.END
    
    return SELECT_USER_FOR_ATTEMPTS

def select_user_for_attempts(update: Update, context: CallbackContext):
    if update.callback_query:
        query = update.callback_query
        query.answer()
        
        if query.data.startswith("all_users:"):
            group_id = query.data.split(":")[1]
            context.user_data["selected_group"] = group_id
            query.edit_message_text(
                f"جميع مستخدمي المجموعة {group_id}. أدخل معرف المستخدم (User ID) الذي تريد إدارة محاولاته:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="set_copy_attempts")]]),
            )
        elif query.data == "back_to_select_group":
            query.edit_message_text(
                "اختر المجموعة:",
                reply_markup=get_groups_keyboard(),
            )
            return SELECT_GROUP_FOR_ATTEMPTS
    else:
        try:
            user_id = int(update.message.text)
            context.user_data["selected_user"] = user_id
            
            attempts = totp_manager.get_user_attempts(user_id)
            update.message.reply_text(
                f"إدارة محاولات المستخدم {user_id}:\n\n"
                f"المحاولات المستخدمة اليوم: {attempts['used']}\n"
                f"المحاولات المسموحة اليوم: {attempts['allowed']}\n\n"
                "اختر الإجراء:",
                reply_markup=get_user_actions_keyboard(user_id),
            )
            return USER_ATTEMPTS_MANAGEMENT
        except ValueError:
            update.message.reply_text("يرجى إدخال معرف مستخدم صحيح (أرقام فقط).")
            return SELECT_USER_FOR_ATTEMPTS
    
    return USER_ATTEMPTS_MANAGEMENT

def add_attempts(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply_text("ليس لديك صلاحية الوصول إلى لوحة التحكم.")
        return ConversationHandler.END

    try:
        attempts = int(update.message.text)
        selected_user = context.user_data.get("selected_user")
        
        if selected_user:
            totp_manager.update_user_attempts(selected_user, added=attempts)
            user_attempts = totp_manager.get_user_attempts(selected_user)
            update.message.reply_text(
                f"تمت إضافة {attempts} محاولة للمستخدم {selected_user}.\n\n"
                f"المحاولات المستخدمة اليوم: {user_attempts['used']}\n"
                f"المحاولات المسموحة اليوم: {user_attempts['allowed']}",
                reply_markup=get_user_attempts_keyboard(),
            )
        else:
            update.message.reply_text("لم يتم تحديد مستخدم.", reply_markup=get_user_attempts_keyboard())
    except ValueError:
        update.message.reply_text("يرجى إدخال عدد صحيح من المحاولات.")
        return ADD_ATTEMPTS
    
    return ConversationHandler.END

def remove_attempts(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        update.message.reply

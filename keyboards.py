# /home/ec2-user/projects/ChatGPTPlus2FABot/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import database as db
import math

# --- Admin Main Menu ---
def admin_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 إدارة Groups/TOTP_SECRET", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("⏰ إدارة فترة التكرار", callback_data="admin_manage_interval")],
        [InlineKeyboardButton("✉️ إدارة شكل/توقيت الرسالة", callback_data="admin_manage_format")],
        [InlineKeyboardButton("👤 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Group Management Keyboards ---
def manage_groups_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة جديدة", callback_data="group_add")],
        [InlineKeyboardButton("✏️ تعديل مجموعة حالية", callback_data="group_select_edit")],
        [InlineKeyboardButton("➖ حذف مجموعة", callback_data="group_select_delete")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def select_group_keyboard(action_prefix):
    groups = db.get_all_groups()
    keyboard = []
    if not groups:
        keyboard.append([InlineKeyboardButton("لا توجد مجموعات مضافة حالياً", callback_data="no_op")])
    else:
        for group in groups:
            group_id_str = str(group["group_id"])
            keyboard.append([InlineKeyboardButton(f"المجموعة: {group_id_str}", callback_data=f"{action_prefix}:{group_id_str}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع لإدارة المجموعات", callback_data="admin_manage_groups")])
    return InlineKeyboardMarkup(keyboard)

def edit_group_options_keyboard(group_id):
    keyboard = [
        [InlineKeyboardButton("🔑 تعديل TOTP Secret", callback_data=f"group_edit_secret:{group_id}")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="group_select_edit")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Interval Management Keyboards ---
def select_group_for_interval_keyboard():
    return select_group_keyboard("interval_select_group")

def interval_options_keyboard(group_id):
    group = db.get_group_settings(group_id)
    current_interval = group["interval_minutes"] if group else "غير محدد"
    is_active = group["is_active"] if group else False
    status_text = "✅ إيقاف الإرسال الدوري" if is_active else "▶️ بدء الإرسال الدوري"
    status_action = "interval_deactivate" if is_active else "interval_activate"

    intervals = [1, 5, 10, 15, 30, 60, 180, 720, 1440] # in minutes
    keyboard = []
    row = []
    for interval in intervals:
        label = f"{interval} دقيقة"
        if interval == 60:
            label = "ساعة"
        elif interval == 180:
            label = "3 ساعات"
        elif interval == 720:
            label = "12 ساعة"
        elif interval == 1440:
            label = "24 ساعة"

        if interval == current_interval:
            label = f"✅ {label}"

        row.append(InlineKeyboardButton(label, callback_data=f"interval_set:{group_id}:{interval}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row: # Add remaining buttons
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(status_text, callback_data=f"{status_action}:{group_id}")])
    keyboard.append([InlineKeyboardButton(f"الفترة الحالية: {current_interval} دقيقة", callback_data="no_op")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_interval")])
    return InlineKeyboardMarkup(keyboard)

# --- Format/Timing Management Keyboards ---
def select_group_for_format_keyboard():
    return select_group_keyboard("format_select_group")

def format_options_keyboard(group_id):
    group = db.get_group_settings(group_id)
    current_format = group["message_format"] if group else 1
    current_tz = group["timezone"] if group else "GMT"
    current_time_format = group["time_format"] if group else 24

    keyboard = [
        [InlineKeyboardButton("-- اختر شكل الرسالة --", callback_data="no_op")],
        [InlineKeyboardButton(f"{'✅ ' if current_format == 1 else ''}الشكل 1: وقت الكود التالي فقط", callback_data=f"format_set:{group_id}:1")],
        [InlineKeyboardButton(f"{'✅ ' if current_format == 2 else ''}الشكل 2: + المدة المتبقية", callback_data=f"format_set:{group_id}:2")],
        [InlineKeyboardButton(f"{'✅ ' if current_format == 3 else ''}الشكل 3: + الوقت الحالي", callback_data=f"format_set:{group_id}:3")],
        [InlineKeyboardButton("-- اختر نظام الوقت --", callback_data="no_op")],
        [InlineKeyboardButton(f"{'✅ ' if current_time_format == 24 else ''}نظام 24 ساعة", callback_data=f"format_set_time_format:{group_id}:24")],
        [InlineKeyboardButton(f"{'✅ ' if current_time_format == 12 else ''}نظام 12 ساعة", callback_data=f"format_set_time_format:{group_id}:12")],
        [InlineKeyboardButton("-- اختر المنطقة الزمنية --", callback_data="no_op")],
        [InlineKeyboardButton(f"{'✅ ' if current_tz == 'GMT' else ''}توقيت غرينتش (GMT)", callback_data=f"format_set_tz:{group_id}:GMT")],
        [InlineKeyboardButton(f"{'✅ ' if current_tz == 'Asia/Gaza' else ''}توقيت غزة (Asia/Gaza)", callback_data=f"format_set_tz:{group_id}:Asia/Gaza")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_format")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- User Attempt Management Keyboards ---
def select_group_for_attempts_keyboard():
    return select_group_keyboard("attempts_select_group")

def select_user_for_attempts_keyboard(group_id, page=1):
    users_data = db.get_users_in_group(group_id)
    keyboard = []
    users_per_page = 5
    start_index = (page - 1) * users_per_page
    end_index = start_index + users_per_page
    paginated_users = users_data[start_index:end_index]

    if not users_data:
        keyboard.append([InlineKeyboardButton("لا يوجد مستخدمون مسجلون لهذه المجموعة بعد", callback_data="no_op")])
    else:
        keyboard.append([InlineKeyboardButton("اختر مستخدم لإدارة محاولاته:", callback_data="no_op")])
        for user in paginated_users:
            user_id = user["user_id"]
            attempts = user["attempts_left"]
            banned = user["is_banned"]
            status = "[محظور]" if banned else f"[{attempts} محاولة]"
            button_text = f"👤 {user_id} {status}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"attempts_select_user:{group_id}:{user_id}")])

        total_pages = math.ceil(len(users_data) / users_per_page)
        pagination_row = []
        if page > 1:
            pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"attempts_user_page:{group_id}:{page-1}"))
        if page < total_pages:
            pagination_row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"attempts_user_page:{group_id}:{page+1}"))
        if pagination_row:
            keyboard.append(pagination_row)

    keyboard.append([InlineKeyboardButton("⚙️ تعديل الحد الافتراضي للمحاولات للمجموعة", callback_data=f"attempts_set_default:{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع لاختيار مجموعة", callback_data="admin_manage_attempts")])
    return InlineKeyboardMarkup(keyboard)

def manage_user_attempts_keyboard(group_id, user_id):
    attempts_left, is_banned = db.get_user_attempts(user_id, group_id)
    ban_text = "🔓 إلغاء حظر المستخدم" if is_banned else "🚫 حظر المستخدم"
    ban_action = "attempts_unban" if is_banned else "attempts_ban"
    keyboard = [
        [InlineKeyboardButton(f"المستخدم: {user_id} | المحاولات: {attempts_left} | محظور: {'نعم' if is_banned else 'لا'}", callback_data="no_op")],
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data=f"attempts_add:{group_id}:{user_id}")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data=f"attempts_remove:{group_id}:{user_id}")],
        [InlineKeyboardButton(ban_text, callback_data=f"{ban_action}:{group_id}:{user_id}")],
        [InlineKeyboardButton("🔙 رجوع لاختيار مستخدم", callback_data=f"attempts_select_group:{group_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Admin Management Keyboards ---
def manage_admins_keyboard():
    admins = db.get_all_admins()
    keyboard = [[InlineKeyboardButton("👑 قائمة المسؤولين الحاليين:", callback_data="no_op")]]
    for admin_id in admins:
        keyboard.append([InlineKeyboardButton(f"👤 {admin_id}", callback_data="no_op")])

    keyboard.extend([
        [InlineKeyboardButton("➕ إضافة مسؤول جديد", callback_data="admin_add")],
        [InlineKeyboardButton("➖ إزالة مسؤول", callback_data="admin_select_remove")],
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="admin_main")]
    ])
    return InlineKeyboardMarkup(keyboard)

def select_admin_to_remove_keyboard():
    admins = db.get_all_admins()
    keyboard = []
    initial_admin = db.INITIAL_ADMIN_ID
    removable_admins = [admin for admin in admins if admin != initial_admin]

    if not removable_admins:
        keyboard.append([InlineKeyboardButton("لا يوجد مسؤولون آخرون لإزالتهم", callback_data="no_op")])
    else:
        keyboard.append([InlineKeyboardButton("اختر المسؤول لإزالته:", callback_data="no_op")])
        for admin_id in removable_admins:
            keyboard.append([InlineKeyboardButton(f"👤 {admin_id}", callback_data=f"admin_remove:{admin_id}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع لإدارة المسؤولين", callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(keyboard)

# --- Code Request Keyboard ---
def request_code_keyboard(group_id):
    keyboard = [
        [InlineKeyboardButton("🔑 نسخ الرمز (Copy Code)", callback_data=f"copy_code:{group_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- General Back Keyboard ---
def back_keyboard(callback_data):
    keyboard = [
        [InlineKeyboardButton("🔙 رجوع", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(keyboard)

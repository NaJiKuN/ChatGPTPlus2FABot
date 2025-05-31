# /home/ec2-user/projects/ChatGPTPlus2FABot/keyboards.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import database as db
import pytz

# لوحات المفاتيح الرئيسية
def admin_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 إدارة Groups/TOTP_SECRET", callback_data="admin_manage_groups")],
        [InlineKeyboardButton("⏰ إدارة فترة التكرار", callback_data="admin_manage_interval")],
        [InlineKeyboardButton("✉️ إدارة شكل وتوقيت الرسالة", callback_data="admin_manage_format")],
        [InlineKeyboardButton("👤 إدارة محاولات المستخدمين", callback_data="admin_manage_attempts")],
        [InlineKeyboardButton("👑 إدارة المسؤولين", callback_data="admin_manage_admins")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard(callback_data):
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data=callback_data)]]
    return InlineKeyboardMarkup(keyboard)

# لوحات مفاتيح إدارة المجموعات
def manage_groups_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مجموعة", callback_data="group_add")],
        [InlineKeyboardButton("✏️ تعديل مجموعة", callback_data="group_select_edit")],
        [InlineKeyboardButton("➖ حذف مجموعة", callback_data="group_select_delete")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def select_group_keyboard(action_prefix):
    groups = db.get_all_groups()
    keyboard = []
    for group in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group["group_id"]}", callback_data=f"{action_prefix}:{group["group_id"]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_groups")])
    return InlineKeyboardMarkup(keyboard)

def edit_group_options_keyboard(group_id):
    keyboard = [
        [InlineKeyboardButton("🔑 تعديل TOTP Secret", callback_data=f"group_edit_secret:{group_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="group_select_edit")]
    ]
    return InlineKeyboardMarkup(keyboard)

# لوحات مفاتيح إدارة فترة التكرار
def select_group_for_interval_keyboard():
    groups = db.get_all_groups()
    keyboard = []
    for group in groups:
        status = "✅ مفعل" if group["is_active"] else "❌ معطل"
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group["group_id"]} ({status})", callback_data=f"interval_select_group:{group["group_id"]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_main")])
    return InlineKeyboardMarkup(keyboard)

def interval_options_keyboard(group_id):
    group_settings = db.get_group_settings(group_id)
    current_interval = group_settings["interval_minutes"]
    is_active = group_settings["is_active"]
    
    intervals = [5, 10, 15, 30, 60] # دقائق
    keyboard = []
    row = []
    for interval in intervals:
        text = f"{interval} دقيقة"
        if interval == current_interval:
            text = f"✅ {text}"
        row.append(InlineKeyboardButton(text, callback_data=f"interval_set:{group_id}:{interval}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row: # Add remaining buttons if any
        keyboard.append(row)
        
    if is_active:
        keyboard.append([InlineKeyboardButton("❌ إيقاف إرسال الرموز لهذه المجموعة", callback_data=f"interval_deactivate:{group_id}")])
    else:
        keyboard.append([InlineKeyboardButton("✅ تفعيل إرسال الرموز لهذه المجموعة", callback_data=f"interval_activate:{group_id}")])
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_interval")])
    return InlineKeyboardMarkup(keyboard)

# لوحات مفاتيح إدارة شكل الرسالة
def select_group_for_format_keyboard():
    groups = db.get_all_groups()
    keyboard = []
    for group in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group["group_id"]}", callback_data=f"format_select_group:{group["group_id"]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_main")])
    return InlineKeyboardMarkup(keyboard)

def format_options_keyboard(group_id):
    group_settings = db.get_group_settings(group_id)
    current_format = group_settings["message_format"]
    current_timezone = group_settings["timezone"]
    
    formats = {
        1: "الوقت المتبقي للرمز التالي",
        2: "الوقت المتبقي + مدة الصلاحية",
        3: "الوقت المتبقي + الوقت الحالي",
        4: "رسالة بسيطة (متاح الآن)"
    }
    
    keyboard = [[InlineKeyboardButton("📝 اختيار شكل الرسالة:", callback_data="no_op")]]
    for format_id, description in formats.items():
        text = description
        if format_id == current_format:
            text = f"✅ {text}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"format_set:{group_id}:{format_id}")])
        
    keyboard.append([InlineKeyboardButton("🌍 اختيار المنطقة الزمنية:", callback_data="no_op")])
    # عرض بعض المناطق الزمنية الشائعة
    common_timezones = ["GMT", "UTC", "Asia/Riyadh", "Europe/Istanbul", "Africa/Cairo", "America/New_York"]
    row = []
    for tz in common_timezones:
        text = tz
        if tz == current_timezone:
            text = f"✅ {text}"
        row.append(InlineKeyboardButton(text, callback_data=f"format_set_tz:{group_id}:{tz}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_format")])
    return InlineKeyboardMarkup(keyboard)

# لوحات مفاتيح إدارة محاولات المستخدمين
def select_group_for_attempts_keyboard():
    groups = db.get_all_groups()
    keyboard = []
    for group in groups:
        keyboard.append([InlineKeyboardButton(f"المجموعة: {group["group_id"]}", callback_data=f"attempts_select_group:{group["group_id"]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_main")])
    return InlineKeyboardMarkup(keyboard)

def select_user_for_attempts_keyboard(group_id, page=1):
    users_per_page = 5
    users = db.get_users_in_group(group_id)
    
    start_index = (page - 1) * users_per_page
    end_index = start_index + users_per_page
    paginated_users = users[start_index:end_index]
    
    keyboard = []
    for user in paginated_users:
        user_id = user["user_id"]
        attempts_left = user["attempts_left"]
        is_banned = user["is_banned"]
        status = "(محظور)" if is_banned else f"({attempts_left} محاولة)"
        # Attempt to get user info (might fail if user not accessible)
        # In a real scenario, you might want to store usernames when they interact
        # For now, just use User ID
        display_name = f"المستخدم: {user_id} {status}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"attempts_select_user:{group_id}:{user_id}")])
        
    # Pagination controls
    pagination_row = []
    if page > 1:
        pagination_row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"attempts_user_page:{group_id}:{page-1}"))
    if end_index < len(users):
        pagination_row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"attempts_user_page:{group_id}:{page+1}"))
    if pagination_row:
        keyboard.append(pagination_row)
        
    keyboard.append([InlineKeyboardButton("⚙️ تعديل الحد الافتراضي للمحاولات للمجموعة", callback_data=f"attempts_set_default:{group_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_attempts")])
    return InlineKeyboardMarkup(keyboard)

def manage_user_attempts_keyboard(group_id, user_id):
    attempts_left, is_banned = db.get_user_attempts(user_id, group_id)
    keyboard = [
        [InlineKeyboardButton(f"المحاولات المتبقية: {attempts_left}", callback_data="no_op")],
        [InlineKeyboardButton("➕ إضافة محاولات", callback_data=f"attempts_add:{group_id}:{user_id}")],
        [InlineKeyboardButton("➖ حذف محاولات", callback_data=f"attempts_remove:{group_id}:{user_id}")],
    ]
    if is_banned:
        keyboard.append([InlineKeyboardButton("🔓 إلغاء حظر المستخدم", callback_data=f"attempts_unban:{group_id}:{user_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🚫 حظر المستخدم", callback_data=f"attempts_ban:{group_id}:{user_id}")])
        
    keyboard.append([InlineKeyboardButton("🔙 رجوع لقائمة المستخدمين", callback_data=f"attempts_select_group:{group_id}")])
    return InlineKeyboardMarkup(keyboard)

# لوحات مفاتيح إدارة المسؤولين
def manage_admins_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة مسؤول", callback_data="admin_add")],
        [InlineKeyboardButton("➖ إزالة مسؤول", callback_data="admin_select_remove")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def select_admin_to_remove_keyboard():
    admins = db.get_all_admins()
    keyboard = []
    for admin_id in admins:
        if admin_id != config.INITIAL_ADMIN_ID: # لا تسمح بإزالة المسؤول الأولي
            # Ideally, fetch admin username here if possible
            keyboard.append([InlineKeyboardButton(f"المسؤول: {admin_id}", callback_data=f"admin_remove:{admin_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(keyboard)

# لوحة مفاتيح طلب الرمز
def request_code_keyboard(group_id):
    keyboard = [[InlineKeyboardButton("🔑 نسخ الرمز", callback_data=f"copy_code:{group_id}")]]
    return InlineKeyboardMarkup(keyboard)

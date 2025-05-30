import sqlite3
import logging
from config import DB_NAME, INITIAL_ADMIN_ID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """Initializes the database by creating necessary tables if they don't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Admins table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY
                )
            """)
            logger.info("Admins table checked/created.")

            # Add initial admin if table is empty
            cursor.execute("SELECT COUNT(*) FROM admins")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO admins (user_id) VALUES (?)", (INITIAL_ADMIN_ID,))
                logger.info(f"Initial admin {INITIAL_ADMIN_ID} added.")

            # Groups table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id INTEGER PRIMARY KEY,
                    totp_secret TEXT NOT NULL,
                    interval_minutes INTEGER DEFAULT 10,
                    message_format INTEGER DEFAULT 1,
                    timezone TEXT DEFAULT 'GMT',
                    max_attempts INTEGER DEFAULT 3,
                    is_active BOOLEAN DEFAULT TRUE,
                    job_id TEXT UNIQUE,
                    time_format TEXT DEFAULT '24' -- '24' or '12' for time format
                )
            """)
            logger.info("Groups table checked/created.")

            # User Attempts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_attempts (
                    user_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    attempts_left INTEGER NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (user_id, group_id),
                    FOREIGN KEY (group_id) REFERENCES groups(group_id) ON DELETE CASCADE
                )
            """)
            logger.info("User Attempts table checked/created.")

            conn.commit()
            logger.info("Database initialized successfully.")
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Database initialization error: {e}")
            return False, "حدث خطأ أثناء تهيئة قاعدة البيانات. يرجى المحاولة مرة أخرى لاحقًا."

# --- Admin Management ---
def is_admin(user_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        is_admin_flag = cursor.fetchone() is not None
        return is_admin_flag

def add_admin(user_id):
    if is_admin(user_id):
        return False, "المستخدم مسؤول بالفعل."
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
            conn.commit()
            logger.info(f"Admin {user_id} added.")
            return True, "تمت إضافة المسؤول بنجاح."
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.warning(f"محاولة إضافة مسؤول موجود مسبقًا: {user_id}")
            return False, "المستخدم مسؤول بالفعل أو حدث خطأ في التكرار."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"خطأ في إضافة المسؤول {user_id}: {e}")
            return False, "حدث خطأ أثناء إضافة المسؤول. يرجى المحاولة مرة أخرى لاحقًا."

def remove_admin(user_id):
    if not is_admin(user_id):
        return False, "المستخدم ليس مسؤولاً."
    if user_id == INITIAL_ADMIN_ID:
        return False, "لا يمكن إزالة المسؤول الأولي."
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Admin {user_id} removed.")
                return True, "تمت إزالة المسؤول بنجاح."
            else:
                logger.warning(f"Attempted to remove non-existent or initial admin {user_id} after initial check.")
                return False, "المسؤول غير موجود أو لا يمكن إزالته."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error removing admin {user_id}: {e}")
            return False, "حدث خطأ أثناء إزالة المسؤول. يرجى المحاولة مرة أخرى لاحقًا."

def get_all_admins():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins")
        admins = [row["user_id"] for row in cursor.fetchall()]
        return admins

# --- Group Management ---
def add_or_update_group(group_id, totp_secret, interval_minutes=10, message_format=1, timezone='GMT', max_attempts=3, is_active=True, job_id=None, time_format='24'):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO groups (group_id, totp_secret, interval_minutes, message_format, timezone, max_attempts, is_active, job_id, time_format)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    totp_secret=excluded.totp_secret,
                    interval_minutes=excluded.interval_minutes,
                    message_format=excluded.message_format,
                    timezone=excluded.timezone,
                    max_attempts=excluded.max_attempts,
                    is_active=excluded.is_active,
                    job_id=excluded.job_id,
                    time_format=excluded.time_format
            """, (group_id, totp_secret, interval_minutes, message_format, timezone, max_attempts, is_active, job_id, time_format))
            conn.commit()
            logger.info(f"Group {group_id} added or updated.")
            return True, "تمت إضافة أو تحديث المجموعة بنجاح."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error adding/updating group {group_id}: {e}")
            return False, "حدث خطأ أثناء إضافة أو تحديث المجموعة. يرجى المحاولة مرة أخرى لاحقًا."

def remove_group(group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM user_attempts WHERE group_id = ?", (group_id,))
            cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Group {group_id} removed along with associated user attempts.")
                return True, "تم حذف المجموعة بنجاح."
            else:
                logger.warning(f"Attempted to remove non-existent group {group_id}")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error removing group {group_id}: {e}")
            return False, "حدث خطأ أثناء حذف المجموعة. يرجى المحاولة مرة أخرى لاحقًا."

def get_all_groups():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups")
        groups = cursor.fetchall()
        return groups

def get_group_settings(group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
        group = cursor.fetchone()
        return group

def update_group_interval(group_id, interval_minutes):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET interval_minutes = ? WHERE group_id = ?", (interval_minutes, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated interval for group {group_id} to {interval_minutes} minutes.")
                return True, "تم تحديث فترة التكرار بنجاح."
            else:
                logger.warning(f"Group {group_id} not found when updating interval.")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating interval for group {group_id}: {e}")
            return False, "حدث خطأ أثناء تحديث فترة التكرار. يرجى المحاولة مرة أخرى لاحقًا."

def update_group_message_format(group_id, message_format, timezone):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET message_format = ?, timezone = ? WHERE group_id = ?", (message_format, timezone, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated message format and timezone for group {group_id} to format {message_format} and timezone {timezone}.")
                return True, "تم تحديث شكل الرسالة والمنطقة الزمنية بنجاح."
            else:
                logger.warning(f"Group {group_id} not found when updating message format.")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating message format for group {group_id}: {e}")
            return False, "حدث خطأ أثناء تحديث شكل الرسالة. يرجى المحاولة مرة أخرى لاحقًا."

def update_group_time_format(group_id, time_format, message_format, timezone):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET time_format = ?, message_format = ?, timezone = ? WHERE group_id = ?", (time_format, message_format, timezone, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated time format for group {group_id} to {time_format}.")
                return True, "تم تحديث تنسيق الوقت بنجاح."
            else:
                logger.warning(f"Group {group_id} not found when updating time format.")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating time format for group {group_id}: {e}")
            return False, "حدث خطأ أثناء تحديث تنسيق الوقت. يرجى المحاولة مرة أخرى لاحقًا."

def update_group_status(group_id, is_active):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET is_active = ? WHERE group_id = ?", (is_active, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                status = "active" if is_active else "inactive"
                logger.info(f"Group {group_id} set to {status}.")
                return True, f"تم {'تفعيل' if is_active else 'إيقاف'} الإرسال الدوري بنجاح."
            else:
                logger.warning(f"Group {group_id} not found when updating status.")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating status for group {group_id}: {e}")
            return False, "حدث خطأ أثناء تحديث حالة المجموعة. يرجى المحاولة مرة أخرى لاحقًا."

def update_group_job_id(group_id, job_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET job_id = ? WHERE group_id = ?", (job_id, group_id))
            conn.commit()
            logger.info(f"Updated job_id for group {group_id} to {job_id}.")
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating job_id for group {group_id}: {e}")

def update_group_max_attempts(group_id, max_attempts):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE groups SET max_attempts = ? WHERE group_id = ?", (max_attempts, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated max attempts for group {group_id} to {max_attempts}.")
                return True, "تم تحديث الحد الأقصى للمحاولات بنجاح."
            else:
                logger.warning(f"Group {group_id} not found when updating max attempts.")
                return False, "المجموعة غير موجودة."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error updating max attempts for group {group_id}: {e}")
            return False, "حدث خطأ أثناء تحديث الحد الأقصى للمحاولات. يرجى المحاولة مرة أخرى لاحقًا."

# --- User Attempt Management ---
def get_user_attempts(user_id, group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Check if the user has an entry in user_attempts
        cursor.execute("SELECT attempts_left, is_banned FROM user_attempts WHERE user_id = ? AND group_id = ?", (user_id, group_id))
        user_data = cursor.fetchone()
        
        if user_data:
            return user_data["attempts_left"], user_data["is_banned"]
        
        # If user doesn't exist, initialize with group's default max_attempts
        cursor.execute("SELECT max_attempts FROM groups WHERE group_id = ?", (group_id,))
        group_data = cursor.fetchone()
        if not group_data:
            logger.warning(f"Group {group_id} not found when initializing attempts for user {user_id}.")
            return 0, False
        
        max_attempts = group_data["max_attempts"]
        try:
            cursor.execute("INSERT INTO user_attempts (user_id, group_id, attempts_left, is_banned) VALUES (?, ?, ?, ?)", (user_id, group_id, max_attempts, False))
            conn.commit()
            logger.info(f"Initialized attempts for user {user_id} in group {group_id} with {max_attempts} attempts.")
            return max_attempts, False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error initializing attempts for user {user_id} in group {group_id}: {e}")
            return 0, False

def get_users_in_group(group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, attempts_left, is_banned FROM user_attempts WHERE group_id = ?", (group_id,))
        users = cursor.fetchall()
        return users

def decrement_user_attempt(user_id, group_id):
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    if is_banned or attempts_left <= 0:
        logger.warning(f"Attempt to decrement failed: User {user_id} in group {group_id} is banned or has {attempts_left} attempts.")
        return False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Begin transaction to prevent race conditions
            cursor.execute("BEGIN TRANSACTION")
            # Lock the row to ensure atomic update
            cursor.execute("SELECT attempts_left FROM user_attempts WHERE user_id = ? AND group_id = ? FOR UPDATE", (user_id, group_id))
            result = cursor.fetchone()
            if result and result["attempts_left"] > 0:
                cursor.execute("UPDATE user_attempts SET attempts_left = attempts_left - 1 WHERE user_id = ? AND group_id = ?", (user_id, group_id))
                conn.commit()
                logger.info(f"Decremented attempt for user {user_id} in group {group_id}.")
                return True
            else:
                conn.rollback()
                logger.warning(f"Failed to decrement attempt for user {user_id} in group {group_id} (maybe already 0).")
                return False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error decrementing attempt for user {user_id} in group {group_id}: {e}")
            return False

def add_user_attempts(user_id, group_id, attempts):
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    new_attempts = attempts_left + attempts

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE user_attempts SET attempts_left = ? WHERE user_id = ? AND group_id = ?", (new_attempts, user_id, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Added {attempts} attempts to user {user_id} in group {group_id}. New total: {new_attempts}.")
                return True, f"تمت إضافة {attempts} محاولات بنجاح. الإجمالي الجديد: {new_attempts}."
            else:
                logger.warning(f"User {user_id} in group {group_id} not found when adding attempts.")
                return False, "المستخدم أو المجموعة غير موجودين."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error adding attempts for user {user_id} in group {group_id}: {e}")
            return False, "حدث خطأ أثناء إضافة المحاولات. يرجى المحاولة مرة أخرى لاحقًا."

def remove_user_attempts(user_id, group_id, attempts):
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    new_attempts = max(0, attempts_left - attempts)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE user_attempts SET attempts_left = ? WHERE user_id = ? AND group_id = ?", (new_attempts, user_id, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Removed {attempts} attempts from user {user_id} in group {group_id}. New total: {new_attempts}.")
                return True, f"تم حذف {attempts} محاولات بنجاح. الإجمالي الجديد: {new_attempts}."
            else:
                logger.warning(f"User {user_id} in group {group_id} not found when removing attempts.")
                return False, "المستخدم أو المجموعة غير موجودين."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error removing attempts for user {user_id} in group {group_id}: {e}")
            return False, "حدث خطأ أثناء حذف المحاولات. يرجى المحاولة مرة أخرى لاحقًا."

def ban_user(user_id, group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE user_attempts SET is_banned = TRUE WHERE user_id = ? AND group_id = ?", (user_id, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"User {user_id} banned in group {group_id}.")
                return True
            else:
                logger.warning(f"User {user_id} in group {group_id} not found when banning.")
                return False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error banning user {user_id} in group {group_id}: {e}")
            return False

def unban_user(user_id, group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE user_attempts SET is_banned = FALSE WHERE user_id = ? AND group_id = ?", (user_id, group_id))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"User {user_id} unbanned in group {group_id}.")
                return True
            else:
                logger.warning(f"User {user_id} in group {group_id} not found when unbanning.")
                return False
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error unbanning user {user_id} in group {group_id}: {e}")
            return False

def reset_all_user_attempts(group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Get the default max_attempts for the group
            cursor.execute("SELECT max_attempts FROM groups WHERE group_id = ?", (group_id,))
            group_data = cursor.fetchone()
            if not group_data:
                logger.warning(f"Group {group_id} not found when resetting attempts.")
                return False, "المجموعة غير موجودة."

            max_attempts = group_data["max_attempts"]
            # Reset attempts for all users in the group
            cursor.execute("UPDATE user_attempts SET attempts_left = ? WHERE group_id = ?", (max_attempts, group_id))
            conn.commit()
            logger.info(f"Reset attempts for all users in group {group_id} to {max_attempts}.")
            return True, f"تم إعادة تعيين المحاولات لجميع المستخدمين في المجموعة {group_id} إلى {max_attempts}."
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Error resetting attempts for group {group_id}: {e}")
            return False, "حدث خطأ أثناء إعادة تعيين المحاولات. يرجى المحاولة مرة أخرى لاحقًا."

# Initialize the database on import
initialize_database()

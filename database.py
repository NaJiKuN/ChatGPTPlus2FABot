# /home/ubuntu/ChatGPTPlus2FABot/database.py
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
    conn = get_db_connection()
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
                job_id TEXT UNIQUE -- To store the scheduler job ID
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
        logger.error(f"Database initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

# --- Admin Management ---
def is_admin(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    is_admin_flag = cursor.fetchone() is not None
    conn.close()
    return is_admin_flag

def add_admin(user_id):
    if is_admin(user_id):
        return False, "المستخدم مسؤول بالفعل."
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        logger.info(f"Admin {user_id} added.")
        return True, "تمت إضافة المسؤول بنجاح."
    except sqlite3.IntegrityError: # Changed from generic Error to IntegrityError for duplicate keys
        conn.rollback()
        logger.warning(f"Attempted to add existing admin {user_id} or other integrity error.")
        return False, "حدث خطأ أثناء إضافة المسؤول (قد يكون المستخدم مسؤولاً بالفعل)."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error adding admin {user_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def remove_admin(user_id):
    if not is_admin(user_id):
        return False, "المستخدم ليس مسؤولاً."
    if user_id == INITIAL_ADMIN_ID:
        return False, "لا يمكن إزالة المسؤول الأولي."
    conn = get_db_connection()
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
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def get_all_admins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins")
    admins = [row["user_id"] for row in cursor.fetchall()]
    conn.close()
    return admins

# --- Group Management ---
def add_or_update_group(group_id, totp_secret, interval_minutes=10, message_format=1, timezone='GMT', max_attempts=3, is_active=True, job_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO groups (group_id, totp_secret, interval_minutes, message_format, timezone, max_attempts, is_active, job_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                totp_secret=excluded.totp_secret,
                interval_minutes=excluded.interval_minutes,
                message_format=excluded.message_format,
                timezone=excluded.timezone,
                max_attempts=excluded.max_attempts,
                is_active=excluded.is_active,
                job_id=excluded.job_id
        """, (group_id, totp_secret, interval_minutes, message_format, timezone, max_attempts, is_active, job_id))
        conn.commit()
        logger.info(f"Group {group_id} added or updated.")
        return True, "تمت إضافة أو تحديث المجموعة بنجاح."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error adding/updating group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def remove_group(group_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Also remove associated user attempts
        cursor.execute("DELETE FROM user_attempts WHERE group_id = ?", (group_id,))
        cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Group {group_id} and associated user attempts removed.")
            return True, "تمت إزالة المجموعة بنجاح."
        else:
            logger.warning(f"Attempted to remove non-existent group {group_id}.")
            return False, "المجموعة غير موجودة."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error removing group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def get_group_settings(group_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
    group = cursor.fetchone()
    conn.close()
    return group

def get_all_groups():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM groups")
    groups = cursor.fetchall()
    conn.close()
    return groups

def update_group_interval(group_id, interval_minutes):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE groups SET interval_minutes = ? WHERE group_id = ?", (interval_minutes, group_id))
        conn.commit()
        if cursor.rowcount > 0:
             logger.info(f"Updated interval for group {group_id} to {interval_minutes} minutes.")
             return True, "تم تحديث فترة التكرار بنجاح."
        else:
             logger.warning(f"Attempted to update interval for non-existent group {group_id}.")
             return False, "المجموعة غير موجودة."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error updating interval for group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def update_group_message_format(group_id, message_format, timezone):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE groups SET message_format = ?, timezone = ? WHERE group_id = ?", (message_format, timezone, group_id))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Updated message format to {message_format} and timezone to {timezone} for group {group_id}.")
            return True, "تم تحديث شكل الرسالة والتوقيت بنجاح."
        else:
            logger.warning(f"Attempted to update format/tz for non-existent group {group_id}.")
            return False, "المجموعة غير موجودة."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error updating message format/timezone for group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def update_group_max_attempts(group_id, max_attempts):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE groups SET max_attempts = ? WHERE group_id = ?", (max_attempts, group_id))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Updated max attempts for group {group_id} to {max_attempts}.")
            return True, "تم تحديث الحد الأقصى للمحاولات للمجموعة بنجاح."
        else:
            logger.warning(f"Attempted to update max attempts for non-existent group {group_id}.")
            return False, "المجموعة غير موجودة."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error updating max attempts for group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def update_group_status(group_id, is_active):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE groups SET is_active = ? WHERE group_id = ?", (is_active, group_id))
        conn.commit()
        if cursor.rowcount > 0:
            status = "activated" if is_active else "deactivated"
            logger.info(f"Group {group_id} {status}.")
            # Corrected f-string for status message
            return True, f"تم {'تفعيل' if is_active else 'إيقاف'} إرسال الرموز للمجموعة بنجاح."
        else:
            logger.warning(f"Attempted to update status for non-existent group {group_id}.")
            return False, "المجموعة غير موجودة."
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error updating status for group {group_id}: {e}")
        return False, f"خطأ في قاعدة البيانات: {e}"
    finally:
        conn.close()

def update_group_job_id(group_id, job_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE groups SET job_id = ? WHERE group_id = ?", (job_id, group_id))
        conn.commit()
        logger.info(f"Updated job_id for group {group_id} to {job_id}.")
        return True
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error updating job_id for group {group_id}: {e}")
        return False
    finally:
        conn.close()

# --- User Attempt Management ---
def get_user_attempts(user_id, group_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attempts_left, is_banned FROM user_attempts WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    result = cursor.fetchone()

    if result:
        conn.close()
        # Corrected dictionary access
        return result['attempts_left'], result['is_banned']
    else:
        conn.close()
        group_settings = get_group_settings(group_id)
        if group_settings:
            # Corrected dictionary access
            default_attempts = group_settings['max_attempts']
            set_user_attempts(user_id, group_id, default_attempts, False)
            return default_attempts, False
        else:
            logger.error(f"Attempted to get attempts for user {user_id} in non-existent group {group_id}")
            return 0, False

def set_user_attempts(user_id, group_id, attempts_left, is_banned):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO user_attempts (user_id, group_id, attempts_left, is_banned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, group_id) DO UPDATE SET
                attempts_left=excluded.attempts_left,
                is_banned=excluded.is_banned
        """, (user_id, group_id, attempts_left, is_banned))
        conn.commit()
        logger.info(f"Set attempts for user {user_id} in group {group_id} to {attempts_left}, banned={is_banned}.")
        return True
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error setting attempts for user {user_id} in group {group_id}: {e}")
        return False
    finally:
        conn.close()

def decrement_user_attempt(user_id, group_id):
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    # Check if get_user_attempts returned valid data (not 0, False from error case)
    # Although the logic inside get_user_attempts handles adding the user, double check here.
    if is_banned or attempts_left <= 0:
        logger.warning(f"Attempt to decrement failed: User {user_id} in group {group_id} is banned or has {attempts_left} attempts.")
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE user_attempts SET attempts_left = attempts_left - 1 WHERE user_id = ? AND group_id = ? AND attempts_left > 0", (user_id, group_id))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"Decremented attempt for user {user_id} in group {group_id}.")
            return True
        else:
            logger.warning(f"Failed to decrement attempt for user {user_id} in group {group_id} (maybe already 0 or race condition).")
            return False
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Error decrementing attempt for user {user_id} in group {group_id}: {e}")
        return False
    finally:
        conn.close()

def ban_user(user_id, group_id):
    attempts_left, _ = get_user_attempts(user_id, group_id)
    # Ensure user exists before banning (get_user_attempts adds user if not found)
    # Check if the return was the error default (0, False)
    # A more robust check might involve checking if the user *was* actually added by get_user_attempts
    # For now, assume get_user_attempts ensures the record exists.
    return set_user_attempts(user_id, group_id, attempts_left, True)

def unban_user(user_id, group_id):
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    # Similar check as ban_user
    return set_user_attempts(user_id, group_id, attempts_left, False)

def add_user_attempts(user_id, group_id, attempts_to_add):
    if not isinstance(attempts_to_add, int) or attempts_to_add <= 0:
        return False, "يجب أن يكون عدد المحاولات المضافة رقماً صحيحاً موجباً."
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    # Assume record exists due to get_user_attempts logic
    new_attempts = attempts_left + attempts_to_add
    success = set_user_attempts(user_id, group_id, new_attempts, is_banned)
    if success:
        return True, f"تمت إضافة {attempts_to_add} محاولة للمستخدم بنجاح. الإجمالي الآن: {new_attempts}"
    else:
        return False, "حدث خطأ أثناء إضافة المحاولات."

def remove_user_attempts(user_id, group_id, attempts_to_remove):
    if not isinstance(attempts_to_remove, int) or attempts_to_remove <= 0:
        return False, "يجب أن يكون عدد المحاولات المحذوفة رقماً صحيحاً موجباً."
    attempts_left, is_banned = get_user_attempts(user_id, group_id)
    # Assume record exists
    new_attempts = max(0, attempts_left - attempts_to_remove)
    success = set_user_attempts(user_id, group_id, new_attempts, is_banned)
    if success:
        actual_removed = attempts_left - new_attempts
        return True, f"تم حذف {actual_removed} محاولة من المستخدم بنجاح. الإجمالي الآن: {new_attempts}"
    else:
        return False, "حدث خطأ أثناء حذف المحاولات."

def get_users_in_group(group_id):
    """Gets all users who have interacted with the bot in a specific group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, attempts_left, is_banned FROM user_attempts WHERE group_id = ? ORDER BY user_id", (group_id,))
    users = cursor.fetchall()
    conn.close()
    return users

if __name__ != "__main__":
    initialize_database()

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
def add_or_update_group(group_id, totp_secret, interval_minutes=10, message_format=1, timezone='GMT', max_attempts=3, is_active=True, job_id=None):
    with get_db_connection() as conn:
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
            return False, "حدث خطأ أثناء إضافة أو تحديث المجموعة. يرجى المحاولة مرة أخرى لاحقًا."

def remove_group(group_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM user_attempts WHERE group_id = ?", (group_id,))
            cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
            conn.commit()
            if cursor.rowcount > 0

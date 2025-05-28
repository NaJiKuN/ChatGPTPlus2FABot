#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام إدارة محاولات المستخدمين
يستخدم هذا السكريبت لإدارة محاولات المستخدمين وإعادة تعيينها يومياً
"""

import logging
import sqlite3
import os
import datetime
import pytz
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filename="user_attempts.log"
)
logger = logging.getLogger(__name__)

# مسار ملف قاعدة البيانات
DB_FILE = "bot_data.db"

def reset_daily_attempts():
    """إعادة تعيين محاولات المستخدمين اليومية بعد منتصف الليل."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # تحديث جميع المستخدمين لإعادة تعيين المحاولات إلى 3 وتسجيل وقت إعادة التعيين
        cursor.execute("""
        UPDATE user_attempts 
        SET remaining_attempts = 3, 
            last_reset = datetime('now')
        """)
        
        conn.commit()
        conn.close()
        logger.info("تم إعادة تعيين محاولات المستخدمين اليومية بنجاح.")
        return True
    except Exception as e:
        logger.error(f"خطأ في إعادة تعيين محاولات المستخدمين: {e}")
        return False

def get_user_attempts(group_id, user_id):
    """الحصول على محاولات المستخدم المتبقية."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
        SELECT remaining_attempts, is_banned, last_reset 
        FROM user_attempts 
        WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))
        
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            return user_data
        else:
            # القيم الافتراضية للمستخدمين الجدد
            return (3, 0, None)  # 3 محاولات، غير محظور، لم يتم إعادة التعيين من قبل
    except Exception as e:
        logger.error(f"خطأ في الحصول على محاولات المستخدم: {e}")
        return (3, 0, None)  # القيم الافتراضية في حالة الخطأ

def update_user_attempts(group_id, user_id, attempts_change=0, is_banned=None, username=None, first_name=None):
    """تحديث محاولات المستخدم المتبقية."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # التحقق مما إذا كان المستخدم موجوداً في هذه المجموعة
        cursor.execute("""
        SELECT remaining_attempts, is_banned 
        FROM user_attempts 
        WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))
        
        user_data = cursor.fetchone()
        
        if user_data:
            current_attempts, current_banned = user_data
            new_attempts = max(0, current_attempts + attempts_change)
            
            # إذا تم توفير is_banned، استخدمه، وإلا احتفظ بالقيمة الحالية
            new_banned = is_banned if is_banned is not None else current_banned
            
            # تحديث معلومات المستخدم إذا تم توفيرها
            if username or first_name:
                update_query = "UPDATE user_attempts SET remaining_attempts = ?, is_banned = ?"
                params = [new_attempts, new_banned]
                
                if username:
                    update_query += ", username = ?"
                    params.append(username)
                
                if first_name:
                    update_query += ", first_name = ?"
                    params.append(first_name)
                
                update_query += " WHERE group_id = ? AND user_id = ?"
                params.extend([group_id, user_id])
                
                cursor.execute(update_query, params)
            else:
                cursor.execute("""
                UPDATE user_attempts 
                SET remaining_attempts = ?, is_banned = ? 
                WHERE group_id = ? AND user_id = ?
                """, (new_attempts, new_banned, group_id, user_id))
        else:
            # مستخدم جديد، تعيين القيم الافتراضية
            new_attempts = max(0, 3 + attempts_change)  # افتراضياً 3 محاولات
            new_banned = is_banned if is_banned is not None else 0
            
            cursor.execute("""
            INSERT INTO user_attempts 
            (group_id, user_id, username, first_name, remaining_attempts, is_banned, last_reset) 
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (group_id, user_id, username, first_name, new_attempts, new_banned))
        
        conn.commit()
        conn.close()
        logger.info(f"تم تحديث محاولات المستخدم {user_id} في المجموعة {group_id} بنجاح.")
        return new_attempts
    except Exception as e:
        logger.error(f"خطأ في تحديث محاولات المستخدم: {e}")
        return 0

def set_user_attempts(group_id, user_id, attempts, is_banned=None, username=None, first_name=None):
    """تعيين عدد محدد من محاولات المستخدم."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # التحقق مما إذا كان المستخدم موجوداً في هذه المجموعة
        cursor.execute("""
        SELECT is_banned 
        FROM user_attempts 
        WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))
        
        user_data = cursor.fetchone()
        
        if user_data:
            current_banned = user_data[0]
            new_banned = is_banned if is_banned is not None else current_banned
            
            # تحديث معلومات المستخدم
            update_query = "UPDATE user_attempts SET remaining_attempts = ?, is_banned = ?"
            params = [attempts, new_banned]
            
            if username:
                update_query += ", username = ?"
                params.append(username)
            
            if first_name:
                update_query += ", first_name = ?"
                params.append(first_name)
            
            update_query += " WHERE group_id = ? AND user_id = ?"
            params.extend([group_id, user_id])
            
            cursor.execute(update_query, params)
        else:
            # مستخدم جديد
            new_banned = is_banned if is_banned is not None else 0
            
            cursor.execute("""
            INSERT INTO user_attempts 
            (group_id, user_id, username, first_name, remaining_attempts, is_banned, last_reset) 
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (group_id, user_id, username, first_name, attempts, new_banned))
        
        conn.commit()
        conn.close()
        logger.info(f"تم تعيين محاولات المستخدم {user_id} في المجموعة {group_id} إلى {attempts} بنجاح.")
        return attempts
    except Exception as e:
        logger.error(f"خطأ في تعيين محاولات المستخدم: {e}")
        return 0

def check_and_reset_attempts_if_needed():
    """التحقق مما إذا كان يجب إعادة تعيين المحاولات اليومية."""
    try:
        # الحصول على التاريخ الحالي
        now = datetime.datetime.now()
        
        # إذا كان الوقت بعد منتصف الليل (00:00)، إعادة تعيين المحاولات
        if now.hour == 0 and now.minute < 5:  # في أول 5 دقائق بعد منتصف الليل
            reset_daily_attempts()
            logger.info("تم إعادة تعيين المحاولات اليومية تلقائياً.")
        
        return True
    except Exception as e:
        logger.error(f"خطأ في التحقق من إعادة تعيين المحاولات: {e}")
        return False

# تنفيذ الوظيفة الرئيسية إذا تم تشغيل السكريبت مباشرة
if __name__ == "__main__":
    check_and_reset_attempts_if_needed()

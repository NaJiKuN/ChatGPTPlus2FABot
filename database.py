#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف إدارة قاعدة البيانات لبوت تليجرام للمصادقة 2FA
"""

import json
import os
from datetime import datetime, time
import pytz
from config import DB_PATH

class Database:
    """فئة إدارة قاعدة البيانات"""
    
    def __init__(self):
        """تهيئة قاعدة البيانات"""
        self.data = self.load_data()
    
    def load_data(self):
        """تحميل البيانات من الملف"""
        if not os.path.exists(DB_PATH):
            return self.create_default_data()
        
        try:
            with open(DB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"خطأ في تحميل البيانات: {e}")
            return self.create_default_data()
    
    def save_data(self):
        """حفظ البيانات في الملف"""
        try:
            with open(DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"خطأ في حفظ البيانات: {e}")
            return False
    
    def create_default_data(self):
        """إنشاء بيانات افتراضية"""
        default_data = {
            "groups": {},
            "users": {},
            "settings": {
                "admin_ids": ["764559466"],
                "default_interval": 10,
                "default_timezone": "Asia/Jerusalem",
                "default_time_format": "12",
                "default_attempts": 3,
            }
        }
        
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with open(DB_PATH, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        
        return default_data
    
    def add_group(self, group_id, totp_secret=None):
        """إضافة مجموعة جديدة"""
        if group_id not in self.data["groups"]:
            self.data["groups"][group_id] = {
                "totp_secret": totp_secret,
                "interval": self.data["settings"]["default_interval"],
                "timezone": self.data["settings"]["default_timezone"],
                "time_format": self.data["settings"]["default_time_format"],
                "active": bool(totp_secret),
                "last_sent": None
            }
            self.save_data()
            return True
        return False
    
    def update_group(self, group_id, **kwargs):
        """تحديث بيانات مجموعة"""
        if group_id in self.data["groups"]:
            for key, value in kwargs.items():
                if key in self.data["groups"][group_id]:
                    self.data["groups"][group_id][key] = value
            self.save_data()
            return True
        return False
    
    def remove_group(self, group_id):
        """حذف مجموعة"""
        if group_id in self.data["groups"]:
            del self.data["groups"][group_id]
            self.save_data()
            return True
        return False
    
    def get_group(self, group_id):
        """الحصول على بيانات مجموعة"""
        return self.data["groups"].get(group_id)
    
    def get_all_groups(self):
        """الحصول على جميع المجموعات"""
        return self.data["groups"]
    
    def add_admin(self, admin_id):
        """إضافة مسؤول جديد"""
        if admin_id not in self.data["settings"]["admin_ids"]:
            self.data["settings"]["admin_ids"].append(admin_id)
            self.save_data()
            return True
        return False
    
    def remove_admin(self, admin_id):
        """حذف مسؤول"""
        if admin_id in self.data["settings"]["admin_ids"]:
            self.data["settings"]["admin_ids"].remove(admin_id)
            self.save_data()
            return True
        return False
    
    def is_admin(self, user_id):
        """التحقق مما إذا كان المستخدم مسؤولاً"""
        return str(user_id) in self.data["settings"]["admin_ids"]
    
    def get_admins(self):
        """الحصول على جميع المسؤولين"""
        return self.data["settings"]["admin_ids"]
    
    def update_user_attempts(self, user_id, group_id=None):
        """تحديث عدد محاولات المستخدم"""
        user_id = str(user_id)
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "attempts": {},
                "total_used": 0
            }
        
        if group_id:
            if group_id not in self.data["users"][user_id]["attempts"]:
                self.data["users"][user_id]["attempts"][group_id] = self.data["settings"]["default_attempts"]
            
            if self.data["users"][user_id]["attempts"][group_id] > 0:
                self.data["users"][user_id]["attempts"][group_id] -= 1
                self.data["users"][user_id]["total_used"] += 1
                self.save_data()
                return self.data["users"][user_id]["attempts"][group_id]
        
        return 0
    
    def get_user_attempts(self, user_id, group_id):
        """الحصول على عدد محاولات المستخدم المتبقية"""
        user_id = str(user_id)
        if user_id in self.data["users"] and group_id in self.data["users"][user_id]["attempts"]:
            return self.data["users"][user_id]["attempts"][group_id]
        return self.data["settings"]["default_attempts"]
    
    def reset_daily_attempts(self):
        """إعادة تعيين محاولات المستخدمين اليومية"""
        for user_id in self.data["users"]:
            for group_id in self.data["users"][user_id]["attempts"]:
                self.data["users"][user_id]["attempts"][group_id] = self.data["settings"]["default_attempts"]
        self.save_data()
        return True
    
    def set_user_attempts(self, user_id, group_id, attempts):
        """تعيين عدد محاولات المستخدم"""
        user_id = str(user_id)
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "attempts": {},
                "total_used": 0
            }
        
        self.data["users"][user_id]["attempts"][group_id] = attempts
        self.save_data()
        return True
    
    def get_user_usage(self, user_id):
        """الحصول على إجمالي استخدام المستخدم"""
        user_id = str(user_id)
        if user_id in self.data["users"]:
            return self.data["users"][user_id]["total_used"]
        return 0
    
    def get_all_users(self):
        """الحصول على جميع المستخدمين"""
        return self.data["users"]
    
    def update_setting(self, key, value):
        """تحديث إعداد عام"""
        if key in self.data["settings"]:
            self.data["settings"][key] = value
            self.save_data()
            return True
        return False
    
    def get_setting(self, key):
        """الحصول على إعداد عام"""
        return self.data["settings"].get(key)
    
    def get_all_settings(self):
        """الحصول على جميع الإعدادات"""
        return self.data["settings"]

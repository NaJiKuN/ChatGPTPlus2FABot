#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف اختبار لبوت تليجرام للمصادقة 2FA
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import pyotp

# إضافة المسار الحالي إلى مسارات البحث
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# استيراد الوحدات المحلية
from utils import (
    generate_totp,
    get_next_update_time,
    is_valid_totp_secret,
    is_valid_group_id
)

class TestTOTPFunctions(unittest.TestCase):
    """اختبار وظائف TOTP"""
    
    def test_generate_totp(self):
        """اختبار توليد رمز TOTP"""
        # إنشاء سر TOTP للاختبار
        secret = pyotp.random_base32()
        
        # توليد رمز TOTP
        totp_code = generate_totp(secret)
        
        # التحقق من أن الرمز تم توليده بنجاح
        self.assertIsNotNone(totp_code)
        self.assertEqual(len(totp_code), 6)  # رمز TOTP يتكون من 6 أرقام
        self.assertTrue(totp_code.isdigit())  # رمز TOTP يتكون من أرقام فقط
    
    def test_get_next_update_time(self):
        """اختبار حساب وقت التحديث القادم"""
        # اختبار مع فترة 10 دقائق
        next_time = get_next_update_time(10, "UTC", "12")
        self.assertIsNotNone(next_time)
        
        # اختبار مع فترة 5 دقائق
        next_time = get_next_update_time(5, "UTC", "12")
        self.assertIsNotNone(next_time)
        
        # اختبار مع صيغة 24 ساعة
        next_time = get_next_update_time(10, "UTC", "24")
        self.assertIsNotNone(next_time)
    
    def test_is_valid_totp_secret(self):
        """اختبار التحقق من صحة سر TOTP"""
        # إنشاء سر TOTP صالح
        valid_secret = pyotp.random_base32()
        
        # إنشاء سر TOTP غير صالح
        invalid_secret = "invalid-secret"
        
        # التحقق من السر الصالح
        self.assertTrue(is_valid_totp_secret(valid_secret))
        
        # التحقق من السر غير الصالح
        self.assertFalse(is_valid_totp_secret(invalid_secret))
    
    def test_is_valid_group_id(self):
        """اختبار التحقق من صحة معرف المجموعة"""
        # معرف مجموعة صالح
        valid_group_id = "-1002329495586"
        
        # معرف مجموعة غير صالح
        invalid_group_id = "invalid-group-id"
        
        # التحقق من المعرف الصالح
        self.assertTrue(is_valid_group_id(valid_group_id))
        
        # التحقق من المعرف غير الصالح
        self.assertFalse(is_valid_group_id(invalid_group_id))

if __name__ == "__main__":
    unittest.main()

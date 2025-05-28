#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف إضافي لتحديث قائمة المسؤول
"""

def update_admin_menu(bot, db):
    """تحديث قائمة المسؤول لإضافة خيار إدارة محاولات جميع المستخدمين في المجموعة"""
    from telebot import types
    import logging
    
    logger = logging.getLogger(__name__)
    
    @bot.message_handler(commands=['admin'])
    def handle_admin(message):
        """معالجة أمر المسؤول"""
        user_id = str(message.from_user.id)
        
        # التحقق من صلاحيات المسؤول
        if not db.is_admin(user_id):
            bot.reply_to(message, "عذراً، هذا الأمر متاح للمسؤولين فقط.")
            return
        
        # إنشاء لوحة تحكم المسؤول
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # إضافة/تعديل مجموعة وإعداد TOTP_SECRET
        btn_add_group = types.InlineKeyboardButton(
            "إضافة/تعديل مجموعة وإعداد TOTP_SECRET",
            callback_data="admin_add_group"
        )
        
        # تعديل فترة إرسال الرموز
        btn_set_interval = types.InlineKeyboardButton(
            "تعديل فترة إرسال الرموز",
            callback_data="admin_set_interval"
        )
        
        # تخصيص شكل رسالة الرمز
        btn_message_format = types.InlineKeyboardButton(
            "تخصيص شكل رسالة الرمز",
            callback_data="admin_message_format"
        )
        
        # إدارة محاولات المستخدمين
        btn_user_attempts = types.InlineKeyboardButton(
            "إدارة محاولات المستخدمين",
            callback_data="admin_user_attempts"
        )
        
        # إدارة محاولات جميع المستخدمين في المجموعة
        btn_group_attempts = types.InlineKeyboardButton(
            "إدارة محاولات جميع المستخدمين في المجموعة",
            callback_data="manage_group_attempts"
        )
        
        # إضافة الأزرار إلى لوحة المفاتيح
        markup.add(btn_add_group, btn_set_interval, btn_message_format, btn_user_attempts, btn_group_attempts)
        
        bot.send_message(
            message.chat.id,
            "مرحباً بك في لوحة تحكم المسؤول",
            reply_markup=markup
        )
        
        logger.info(f"تم عرض قائمة المسؤول للمستخدم {user_id}")

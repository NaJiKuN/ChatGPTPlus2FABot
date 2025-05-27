#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ملف إضافي لإدارة عدد محاولات المستخدمين
"""

def add_manage_attempts_handlers(bot, db):
    """إضافة معالجات إدارة عدد المحاولات"""
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith('manage_attempts_'))
    def handle_manage_attempts(call):
        """معالجة إدارة عدد محاولات المستخدم"""
        parts = call.data.split('_', 2)
        if len(parts) != 3:
            bot.answer_callback_query(call.id, "خطأ في البيانات")
            return
        
        user_id = parts[2]
        user_data = db.get_all_users().get(user_id, {})
        
        if not user_data or not user_data.get("attempts", {}):
            bot.send_message(call.message.chat.id, "لا توجد محاولات لهذا المستخدم")
            return
        
        # عرض قائمة المجموعات لإدارة المحاولات
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for group_id, remaining in user_data.get("attempts", {}).items():
            btn_text = f"المجموعة {group_id}: {remaining} محاولات"
            callback_data = f"select_group_attempts_{user_id}_{group_id}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
        
        bot.send_message(
            call.message.chat.id,
            f"اختر المجموعة لإدارة محاولات المستخدم {user_id}:",
            reply_markup=markup
        )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith('select_group_attempts_'))
    def handle_select_group_attempts(call):
        """معالجة اختيار المجموعة لإدارة المحاولات"""
        parts = call.data.split('_', 4)
        if len(parts) != 5:
            bot.answer_callback_query(call.id, "خطأ في البيانات")
            return
        
        user_id = parts[3]
        group_id = parts[4]
        
        current_attempts = db.get_user_attempts(user_id, group_id)
        
        # إنشاء أزرار لزيادة أو إنقاص عدد المحاولات
        markup = types.InlineKeyboardMarkup(row_width=3)
        
        # أزرار إنقاص المحاولات
        btn_minus_3 = types.InlineKeyboardButton(
            "-3",
            callback_data=f"change_attempts_{user_id}_{group_id}_-3"
        )
        
        btn_minus_1 = types.InlineKeyboardButton(
            "-1",
            callback_data=f"change_attempts_{user_id}_{group_id}_-1"
        )
        
        # أزرار زيادة المحاولات
        btn_plus_1 = types.InlineKeyboardButton(
            "+1",
            callback_data=f"change_attempts_{user_id}_{group_id}_1"
        )
        
        btn_plus_3 = types.InlineKeyboardButton(
            "+3",
            callback_data=f"change_attempts_{user_id}_{group_id}_3"
        )
        
        btn_plus_5 = types.InlineKeyboardButton(
            "+5",
            callback_data=f"change_attempts_{user_id}_{group_id}_5"
        )
        
        # زر إعادة تعيين المحاولات
        btn_reset = types.InlineKeyboardButton(
            "إعادة تعيين",
            callback_data=f"reset_attempts_{user_id}_{group_id}"
        )
        
        # إضافة الأزرار إلى لوحة المفاتيح
        markup.add(btn_minus_3, btn_minus_1, btn_plus_1, btn_plus_3, btn_plus_5, btn_reset)
        
        bot.send_message(
            call.message.chat.id,
            f"إدارة محاولات المستخدم {user_id} للمجموعة {group_id}\n"
            f"عدد المحاولات الحالية: {current_attempts}\n\n"
            "اختر التغيير المطلوب:",
            reply_markup=markup
        )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith('change_attempts_'))
    def handle_change_attempts(call):
        """معالجة تغيير عدد محاولات المستخدم"""
        parts = call.data.split('_', 4)
        if len(parts) != 5:
            bot.answer_callback_query(call.id, "خطأ في البيانات")
            return
        
        user_id = parts[2]
        group_id = parts[3]
        change = int(parts[4])
        
        current_attempts = db.get_user_attempts(user_id, group_id)
        new_attempts = max(0, current_attempts + change)  # لا يمكن أن يكون عدد المحاولات سالباً
        
        db.set_user_attempts(user_id, group_id, new_attempts)
        
        bot.send_message(
            call.message.chat.id,
            f"تم تغيير عدد محاولات المستخدم {user_id} للمجموعة {group_id}\n"
            f"من {current_attempts} إلى {new_attempts}"
        )
        
        bot.answer_callback_query(call.id)

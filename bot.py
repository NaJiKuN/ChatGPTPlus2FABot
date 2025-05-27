#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت تليجرام للمصادقة 2FA
يقوم بإرسال رمز مصادقة 2FA من خلال الـTOTP_SECRET
"""

import os
import sys
import time
import logging
import threading
import schedule
from datetime import datetime, timedelta
import pytz
import telebot
from telebot import types
import pyotp

# استيراد الوحدات المحلية
from config import get_token, MESSAGE_TEMPLATES
from database import Database
from utils import (
    generate_totp, 
    get_next_update_time, 
    is_valid_totp_secret, 
    is_valid_group_id,
    is_midnight
)
from user_attempts import add_manage_attempts_handlers

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# تهيئة البوت وقاعدة البيانات
TOKEN = get_token()
bot = telebot.TeleBot(TOKEN)
db = Database()

# قاموس لتخزين المهام النشطة
active_tasks = {}

def send_2fa_code(group_id):
    """إرسال رمز المصادقة 2FA إلى المجموعة"""
    try:
        group_data = db.get_group(group_id)
        if not group_data or not group_data.get("active") or not group_data.get("totp_secret"):
            logger.warning(f"المجموعة {group_id} غير نشطة أو لا تحتوي على سر TOTP")
            return False
        
        # لا نقوم بتوليد الرمز هنا، سيتم توليده في الوقت الفعلي عند الضغط على الزر
        
        # إنشاء لوحة المفاتيح مع زر النسخ
        markup = types.InlineKeyboardMarkup()
        copy_button = types.InlineKeyboardButton(
            text=MESSAGE_TEMPLATES["copy_button"],
            callback_data=f"copy_{group_id}_realtime"  # استخدام علامة realtime بدلاً من الرمز الثابت
        )
        markup.add(copy_button)
        
        # حساب وقت التحديث القادم بالنسبة للوقت الحالي
        current_time = datetime.now(pytz.timezone(group_data.get("timezone", "UTC")))
        interval_minutes = group_data.get("interval", 10)
        next_update = current_time + timedelta(minutes=interval_minutes)
        
        # تنسيق الوقت حسب الصيغة المطلوبة
        if group_data.get("time_format", "12") == "12":
            current_time_str = current_time.strftime("%I:%M:%S %p")
            next_time_str = next_update.strftime("%I:%M:%S %p")
        else:
            current_time_str = current_time.strftime("%H:%M:%S")
            next_time_str = next_update.strftime("%H:%M:%S")
        
        # تحضير نص الرسالة مع توضيح الوقت الحالي والوقت القادم بشكل واضح
        message_text = f"{MESSAGE_TEMPLATES['header']}\n\n"
        message_text += f"Current time: {current_time_str}\n"
        message_text += f"Next code in: {interval_minutes} minutes\n"
        message_text += f"Next code at: {next_time_str}"
        
        # إرسال الرسالة
        bot.send_message(group_id, message_text, reply_markup=markup)
        
        # تحديث وقت آخر إرسال
        db.update_group(group_id, last_sent=datetime.now().timestamp())
        
        logger.info(f"تم إرسال رمز 2FA إلى المجموعة {group_id}")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في إرسال رمز 2FA إلى المجموعة {group_id}: {e}")
        return False

def schedule_2fa_task(group_id):
    """جدولة مهمة إرسال رمز 2FA بشكل دوري"""
    try:
        # إلغاء المهمة السابقة إذا كانت موجودة
        if group_id in active_tasks:
            schedule.cancel_job(active_tasks[group_id])
        
        group_data = db.get_group(group_id)
        if not group_data or not group_data.get("active"):
            logger.warning(f"المجموعة {group_id} غير نشطة")
            return False
        
        # إرسال رمز فوري
        send_2fa_code(group_id)
        
        # جدولة المهمة الدورية
        interval = group_data.get("interval", 10)  # الفترة الافتراضية 10 دقائق
        
        # إنشاء مهمة جديدة
        job = schedule.every(interval).minutes.do(send_2fa_code, group_id=group_id)
        active_tasks[group_id] = job
        
        logger.info(f"تمت جدولة مهمة إرسال رمز 2FA للمجموعة {group_id} كل {interval} دقائق")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في جدولة مهمة إرسال رمز 2FA للمجموعة {group_id}: {e}")
        return False

def stop_2fa_task(group_id):
    """إيقاف مهمة إرسال رمز 2FA"""
    try:
        if group_id in active_tasks:
            schedule.cancel_job(active_tasks[group_id])
            del active_tasks[group_id]
            logger.info(f"تم إيقاف مهمة إرسال رمز 2FA للمجموعة {group_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"خطأ في إيقاف مهمة إرسال رمز 2FA للمجموعة {group_id}: {e}")
        return False

def reset_daily_attempts():
    """إعادة تعيين محاولات المستخدمين اليومية"""
    db.reset_daily_attempts()
    logger.info("تم إعادة تعيين محاولات المستخدمين اليومية")

def check_midnight():
    """التحقق من منتصف الليل لإعادة تعيين المحاولات"""
    for timezone_str in set(group["timezone"] for group in db.get_all_groups().values()):
        if is_midnight(timezone_str):
            reset_daily_attempts()
            break

def scheduler_thread():
    """دالة تشغيل المجدول في خيط منفصل"""
    while True:
        schedule.run_pending()
        check_midnight()
        time.sleep(1)

# معالجات الأوامر والأزرار

@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالجة أمر البداية"""
    bot.send_message(message.chat.id, MESSAGE_TEMPLATES["welcome"])

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    """معالجة أمر المسؤول"""
    if not db.is_admin(message.from_user.id):
        bot.send_message(message.chat.id, MESSAGE_TEMPLATES["no_permission"])
        return
    
    # إنشاء لوحة المفاتيح للمسؤول
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn_add_group = types.InlineKeyboardButton(
        "إضافة/تعديل مجموعة وإعداد TOTP_SECRET",
        callback_data="admin_add_group"
    )
    
    btn_set_interval = types.InlineKeyboardButton(
        "تعديل فترة إرسال الرموز",
        callback_data="admin_set_interval"
    )
    
    btn_message_format = types.InlineKeyboardButton(
        "تخصيص شكل رسالة الرمز",
        callback_data="admin_message_format"
    )
    
    btn_user_attempts = types.InlineKeyboardButton(
        "إدارة محاولات المستخدمين",
        callback_data="admin_user_attempts"
    )
    
    markup.add(btn_add_group, btn_set_interval, btn_message_format, btn_user_attempts)
    
    bot.send_message(
        message.chat.id,
        MESSAGE_TEMPLATES["admin_welcome"],
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callback(call):
    """معالجة استدعاءات المسؤول"""
    if not db.is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, MESSAGE_TEMPLATES["no_permission"])
        return
    
    if call.data == "admin_add_group":
        # طلب معرف المجموعة
        msg = bot.send_message(
            call.message.chat.id,
            MESSAGE_TEMPLATES["group_id_request"]
        )
        bot.register_next_step_handler(msg, process_group_id)
    
    elif call.data == "admin_set_interval":
        # عرض قائمة المجموعات لاختيار واحدة
        show_group_selection(call.message.chat.id, "interval")
    
    elif call.data == "admin_message_format":
        # عرض قائمة المجموعات لاختيار واحدة
        show_group_selection(call.message.chat.id, "format")
    
    elif call.data == "admin_user_attempts":
        # عرض قائمة المستخدمين
        show_users_list(call.message.chat.id)
    
    # إزالة علامة "جاري التحميل" من الزر
    bot.answer_callback_query(call.id)

def process_group_id(message):
    """معالجة إدخال معرف المجموعة"""
    group_id = message.text.strip()
    
    if not is_valid_group_id(group_id):
        bot.send_message(
            message.chat.id,
            MESSAGE_TEMPLATES["error"].format(error="معرف المجموعة غير صالح")
        )
        return
    
    # تخزين معرف المجموعة مؤقتاً
    user_id = message.from_user.id
    user_data = {"group_id": group_id}
    
    # طلب TOTP_SECRET
    msg = bot.send_message(
        message.chat.id,
        MESSAGE_TEMPLATES["totp_secret_request"]
    )
    
    # تخزين البيانات في الرسالة للاستخدام لاحقاً
    bot.register_next_step_handler_by_chat_id(
        message.chat.id,
        process_totp_secret,
        user_data=user_data
    )

def process_totp_secret(message, user_data):
    """معالجة إدخال TOTP_SECRET"""
    totp_secret = message.text.strip()
    group_id = user_data["group_id"]
    
    # التحقق من صحة TOTP_SECRET
    if not is_valid_totp_secret(totp_secret):
        bot.send_message(
            message.chat.id,
            MESSAGE_TEMPLATES["error"].format(error="TOTP_SECRET غير صالح")
        )
        return
    
    # إضافة أو تحديث المجموعة
    group_exists = db.get_group(group_id) is not None
    
    if group_exists:
        db.update_group(group_id, totp_secret=totp_secret, active=True)
    else:
        db.add_group(group_id, totp_secret=totp_secret)
    
    # إعادة جدولة المهمة
    schedule_2fa_task(group_id)
    
    # إرسال رسالة نجاح
    action = "تحديث" if group_exists else "إضافة"
    bot.send_message(
        message.chat.id,
        f"تم {action} المجموعة بنجاح!\n"
        f"معرف المجموعة: {group_id}\n"
        f"تم تفعيل إرسال رموز 2FA"
    )

def show_group_selection(chat_id, action_type):
    """عرض قائمة المجموعات للاختيار"""
    groups = db.get_all_groups()
    
    if not groups:
        bot.send_message(chat_id, "لا توجد مجموعات مضافة بعد")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for group_id, group_data in groups.items():
        if group_data.get("totp_secret"):  # عرض المجموعات التي لها TOTP_SECRET فقط
            btn_text = f"المجموعة: {group_id}"
            callback_data = f"select_group_{action_type}_{group_id}"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    
    bot.send_message(
        chat_id,
        "اختر المجموعة:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_group_'))
def handle_group_selection(call):
    """معالجة اختيار المجموعة"""
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    action_type = parts[2]
    group_id = parts[3]
    
    if action_type == "interval":
        show_interval_selection(call.message.chat.id, group_id)
    elif action_type == "format":
        show_format_options(call.message.chat.id, group_id)
    
    bot.answer_callback_query(call.id)

def show_interval_selection(chat_id, group_id):
    """عرض خيارات فترة الإرسال"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    intervals = [1, 5, 10, 15, 30, 60]
    buttons = []
    
    for interval in intervals:
        btn_text = f"{interval} دقيقة" if interval == 1 else f"{interval} دقائق"
        callback_data = f"set_interval_{group_id}_{interval}"
        buttons.append(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    
    # إضافة الأزرار في صفوف من 3
    for i in range(0, len(buttons), 3):
        row_buttons = buttons[i:i+3]
        markup.row(*row_buttons)
    
    group_data = db.get_group(group_id)
    current_interval = group_data.get("interval", 10)
    
    bot.send_message(
        chat_id,
        f"اختر فترة إرسال الرموز للمجموعة {group_id}\n"
        f"الفترة الحالية: {current_interval} دقيقة",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_interval_'))
def handle_set_interval(call):
    """معالجة تعيين فترة الإرسال"""
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[2]
    interval = int(parts[3])
    
    # تحديث فترة الإرسال
    db.update_group(group_id, interval=interval)
    
    # إعادة جدولة المهمة
    schedule_2fa_task(group_id)
    
    bot.send_message(
        call.message.chat.id,
        f"تم تعيين فترة إرسال الرموز للمجموعة {group_id} إلى {interval} دقيقة"
    )
    
    bot.answer_callback_query(call.id)

def show_format_options(chat_id, group_id):
    """عرض خيارات تنسيق الرسالة"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn_timezone = types.InlineKeyboardButton(
        "تغيير المنطقة الزمنية",
        callback_data=f"format_timezone_{group_id}"
    )
    
    btn_time_format = types.InlineKeyboardButton(
        "تغيير صيغة الوقت (12/24 ساعة)",
        callback_data=f"format_time_{group_id}"
    )
    
    markup.add(btn_timezone, btn_time_format)
    
    group_data = db.get_group(group_id)
    current_timezone = group_data.get("timezone", "Asia/Jerusalem")
    current_time_format = group_data.get("time_format", "12")
    
    bot.send_message(
        chat_id,
        f"اختر إعدادات تنسيق الرسالة للمجموعة {group_id}\n"
        f"المنطقة الزمنية الحالية: {current_timezone}\n"
        f"صيغة الوقت الحالية: {current_time_format} ساعة",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('format_timezone_'))
def handle_format_timezone(call):
    """معالجة تغيير المنطقة الزمنية"""
    parts = call.data.split('_', 3)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[2]
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    timezones = [
        ("توقيت فلسطين", "Asia/Jerusalem"),
        ("التوقيت العالمي", "UTC")
    ]
    
    for name, tz in timezones:
        markup.add(types.InlineKeyboardButton(
            name,
            callback_data=f"set_timezone_{group_id}_{tz}"
        ))
    
    bot.send_message(
        call.message.chat.id,
        "اختر المنطقة الزمنية:",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_timezone_'))
def handle_set_timezone(call):
    """معالجة تعيين المنطقة الزمنية"""
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[2]
    timezone = parts[3]
    
    # تحديث المنطقة الزمنية
    db.update_group(group_id, timezone=timezone)
    
    # إعادة جدولة المهمة
    schedule_2fa_task(group_id)
    
    bot.send_message(
        call.message.chat.id,
        f"تم تعيين المنطقة الزمنية للمجموعة {group_id} إلى {timezone}"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('format_time_'))
def handle_format_time(call):
    """معالجة تغيير صيغة الوقت"""
    parts = call.data.split('_', 3)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[2]
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_12 = types.InlineKeyboardButton(
        "صيغة 12 ساعة",
        callback_data=f"set_time_format_{group_id}_12"
    )
    
    btn_24 = types.InlineKeyboardButton(
        "صيغة 24 ساعة",
        callback_data=f"set_time_format_{group_id}_24"
    )
    
    markup.add(btn_12, btn_24)
    
    bot.send_message(
        call.message.chat.id,
        "اختر صيغة الوقت:",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_time_format_'))
def handle_set_time_format(call):
    """معالجة تعيين صيغة الوقت"""
    parts = call.data.split('_', 4)
    if len(parts) != 5:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[3]
    time_format = parts[4]
    
    # تحديث صيغة الوقت
    db.update_group(group_id, time_format=time_format)
    
    # إعادة جدولة المهمة
    schedule_2fa_task(group_id)
    
    bot.send_message(
        call.message.chat.id,
        f"تم تعيين صيغة الوقت للمجموعة {group_id} إلى {time_format} ساعة"
    )
    
    bot.answer_callback_query(call.id)

def show_users_list(chat_id):
    """عرض قائمة المستخدمين"""
    users = db.get_all_users()
    
    if not users:
        bot.send_message(chat_id, "لا يوجد مستخدمين بعد")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for user_id, user_data in users.items():
        total_used = user_data.get("total_used", 0)
        btn_text = f"المستخدم: {user_id} - عدد الاستخدامات: {total_used}"
        callback_data = f"user_details_{user_id}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    
    bot.send_message(
        chat_id,
        "اختر مستخدم لعرض التفاصيل:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('user_details_'))
def handle_user_details(call):
    """معالجة عرض تفاصيل المستخدم"""
    parts = call.data.split('_', 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    user_id = parts[2]
    user_data = db.get_all_users().get(user_id, {})
    
    if not user_data:
        bot.send_message(call.message.chat.id, "لا توجد بيانات لهذا المستخدم")
        return
    
    total_used = user_data.get("total_used", 0)
    attempts = user_data.get("attempts", {})
    
    message_text = f"تفاصيل المستخدم {user_id}:\n"
    message_text += f"إجمالي الاستخدامات: {total_used}\n\n"
    message_text += "المحاولات المتبقية حسب المجموعة:\n"
    
    for group_id, remaining in attempts.items():
        message_text += f"المجموعة {group_id}: {remaining} محاولات\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_reset = types.InlineKeyboardButton(
        "إعادة تعيين المحاولات",
        callback_data=f"reset_user_{user_id}"
    )
    
    btn_manage_attempts = types.InlineKeyboardButton(
        "إدارة عدد المحاولات",
        callback_data=f"manage_attempts_{user_id}"
    )
    
    markup.add(btn_reset, btn_manage_attempts)
    
    bot.send_message(
        call.message.chat.id,
        message_text,
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_attempts_'))
def handle_manage_attempts(call):
    """معالجة إدارة عدد المحاولات"""
    parts = call.data.split('_', 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    user_id = parts[2]
    user_data = db.get_all_users().get(user_id, {})
    attempts = user_data.get("attempts", {})
    
    if not attempts:
        bot.send_message(call.message.chat.id, "لا توجد محاولات لهذا المستخدم")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for group_id, remaining in attempts.items():
        btn_text = f"المجموعة {group_id}: {remaining} محاولات"
        callback_data = f"select_group_attempts_{user_id}_{group_id}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
        logger.info(f"تم إنشاء زر للمجموعة {group_id} مع callback_data: {callback_data}")
    
    bot.send_message(
        call.message.chat.id,
        f"اختر المجموعة لإدارة محاولات المستخدم {user_id}:",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_group_attempts_'))
def handle_select_group_attempts(call):
    """معالجة اختيار المجموعة لإدارة المحاولات"""
    logger.info(f"تم استدعاء handle_select_group_attempts مع callback_data: {call.data}")
    
    # تقسيم callback_data مع مراعاة أن group_id قد يحتوي على علامة سالبة
    parts = call.data.split('_')
    if len(parts) < 4:
        logger.error(f"خطأ في تقسيم callback_data: {call.data}")
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    # استخراج user_id و group_id بشكل ديناميكي
    user_id = parts[3]
    # إعادة بناء group_id (قد يحتوي على علامة سالبة)
    group_id = '_'.join(parts[4:])  # نأخذ كل الأجزاء المتبقية كـ group_id
    
    logger.info(f"تم استخراج user_id: {user_id}, group_id: {group_id}")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_increase = types.InlineKeyboardButton(
        "زيادة المحاولات",
        callback_data=f"increase_attempts_{user_id}_{group_id}"
    )
    
    btn_decrease = types.InlineKeyboardButton(
        "نقصان المحاولات",
        callback_data=f"decrease_attempts_{user_id}_{group_id}"
    )
    
    markup.add(btn_increase, btn_decrease)
    
    bot.send_message(
        call.message.chat.id,
        f"اختر الإجراء لإدارة محاولات المستخدم {user_id} في المجموعة {group_id}:",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('increase_attempts_') or call.data.startswith('decrease_attempts_'))
def handle_adjust_attempts(call):
    """معالجة طلب زيادة أو نقصان المحاولات"""
    parts = call.data.split('_')
    if len(parts) < 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    action = parts[0]  # increase_attempts or decrease_attempts
    user_id = parts[2]
    group_id = '_'.join(parts[3:])  # إعادة بناء group_id مع مراعاة العلامة السالبة
    
    # طلب إدخال عدد المحاولات
    msg = bot.send_message(
        call.message.chat.id,
        f"أدخل عدد المحاولات الجديد للمستخدم {user_id} في المجموعة {group_id} (عدد صحيح غير سالب):"
    )
    
    bot.register_next_step_handler(msg, process_attempts_input, user_id=user_id, group_id=group_id, action=action)
    
    bot.answer_callback_query(call.id)

def process_attempts_input(message, user_id, group_id, action):
    """معالجة إدخال عدد المحاولات"""
    try:
        new_attempts = int(message.text.strip())
        if new_attempts < 0:
            bot.send_message(
                message.chat.id,
                MESSAGE_TEMPLATES["error"].format(error="عدد المحاولات يجب أن يكون غير سالب")
            )
            return
        
        # تحديث عدد المحاولات
        db.set_user_attempts(user_id, group_id, new_attempts)
        
        action_text = "زيادة" if action == "increase_attempts" else "نقصان"
        bot.send_message(
            message.chat.id,
            f"تم {action_text} محاولات المستخدم {user_id} في المجموعة {group_id} إلى {new_attempts} بنجاح"
        )
    
    except ValueError:
        bot.send_message(
            message.chat.id,
            MESSAGE_TEMPLATES["error"].format(error="يرجى إدخال عدد صحيح صالح")
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_user_'))
def handle_reset_user(call):
    """معالجة إعادة تعيين محاولات المستخدم"""
    parts = call.data.split('_', 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    user_id = parts[2]
    
    # عرض قائمة المجموعات لإعادة تعيين المحاولات
    user_data = db.get_all_users().get(user_id, {})
    attempts = user_data.get("attempts", {})
    
    if not attempts:
        bot.send_message(call.message.chat.id, "لا توجد محاولات لهذا المستخدم")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for group_id, remaining in attempts.items():
        btn_text = f"المجموعة {group_id}: {remaining} محاولات"
        callback_data = f"reset_attempts_{user_id}_{group_id}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
    
    # إضافة زر لإعادة تعيين جميع المحاولات
    markup.add(types.InlineKeyboardButton(
        "إعادة تعيين جميع المحاولات",
        callback_data=f"reset_all_attempts_{user_id}"
    ))
    
    bot.send_message(
        call.message.chat.id,
        "اختر المجموعة لإعادة تعيين المحاولات:",
        reply_markup=markup
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_attempts_'))
def handle_reset_attempts(call):
    """معالجة إعادة تعيين محاولات المستخدم لمجموعة محددة"""
    parts = call.data.split('_')
    if len(parts) < 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    user_id = parts[2]
    group_id = '_'.join(parts[3:])  # إعادة بناء group_id
    
    # إعادة تعيين المحاولات
    default_attempts = db.get_setting("default_attempts")
    db.set_user_attempts(user_id, group_id, default_attempts)
    
    bot.send_message(
        call.message.chat.id,
        f"تم إعادة تعيين محاولات المستخدم {user_id} للمجموعة {group_id} إلى {default_attempts}"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_all_attempts_'))
def handle_reset_all_attempts(call):
    """معالجة إعادة تعيين جميع محاولات المستخدم"""
    parts = call.data.split('_', 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    user_id = parts[3]
    
    # إعادة تعيين جميع المحاولات
    user_data = db.get_all_users().get(user_id, {})
    attempts = user_data.get("attempts", {})
    default_attempts = db.get_setting("default_attempts")
    
    for group_id in attempts:
        db.set_user_attempts(user_id, group_id, default_attempts)
    
    bot.send_message(
        call.message.chat.id,
        f"تم إعادة تعيين جميع محاولات المستخدم {user_id} إلى {default_attempts}"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_') and not call.data.startswith('copy_code_'))
def handle_copy_code(call):
    """معالجة نسخ رمز المصادقة في الوقت الفعلي"""
    parts = call.data.split('_', 3)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    group_id = parts[1]
    user_id = call.from_user.id
    
    # التحقق من عدد المحاولات المتبقية قبل التحديث
    current_attempts = db.get_user_attempts(user_id, group_id)
    
    if current_attempts <= 0:
        # لا توجد محاولات متبقية
        bot.answer_callback_query(
            call.id,
            text=f"لقد استنفذت جميع محاولاتك اليومية. يرجى الانتظار حتى منتصف الليل لإعادة تعيين المحاولات.",
            show_alert=True
        )
        return
    
    # الحصول على بيانات المجموعة
    group_data = db.get_group(group_id)
    if not group_data or not group_data.get("totp_secret"):
        bot.answer_callback_query(call.id, "خطأ: لا يمكن الوصول إلى بيانات المجموعة")
        return
    
    # توليد رمز TOTP في الوقت الفعلي
    totp_code = generate_totp(group_data["totp_secret"])
    if not totp_code:
        bot.answer_callback_query(call.id, "خطأ في توليد رمز المصادقة")
        return
    
    # تحديث عدد المحاولات
    remaining = db.update_user_attempts(user_id, group_id)
    
    # إرسال إشعار بسيط
    bot.answer_callback_query(
        call.id,
        text="تم توليد رمز المصادقة. سيتم إرساله إليك في رسالة خاصة."
    )
    
    # إرسال الرمز في رسالة خاصة بدون لوحة مفاتيح ليكون قابلًا للنسخ
    try:
        # إرسال الرمز في رسالة خاصة بتنسيق محسن
        bot.send_message(
            user_id,
            f"🔐 رمز المصادقة 2FA\n\n{totp_code}\n\n⚠️ صالح لمدة 30 ثانية فقط!\n\nعدد المحاولات المتبقية: {remaining}",
            parse_mode=None  # استخدام نص عادي لتسهيل النسخ
        )
    except Exception as e:
        # في حالة فشل إرسال الرسالة الخاصة (مثلاً إذا لم يبدأ المستخدم محادثة مع البوت)
        logger.error(f"فشل في إرسال رسالة خاصة للمستخدم {user_id}: {e}")
        bot.answer_callback_query(
            call.id,
            text=f"الرمز: {totp_code}\nيرجى بدء محادثة مع البوت للحصول على رسائل خاصة.",
            show_alert=True
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_code_'))
def handle_copy_code_button(call):
    """معالجة زر نسخ الرمز (لن يُستخدم بعد الآن بسبب إزالة الزر)"""
    parts = call.data.split('_', 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    totp_code = parts[2]
    bot.answer_callback_query(
        call.id,
        text=f"تم نسخ الرمز: {totp_code}",
        show_alert=True
    )

def main():
    """الدالة الرئيسية"""
    try:
        logger.info("بدء تشغيل البوت...")
        
        # إضافة معالجات إدارة عدد المحاولات
        add_manage_attempts_handlers(bot, db)
        
        # بدء خيط المجدول
        scheduler_thread_obj = threading.Thread(target=scheduler_thread)
        scheduler_thread_obj.daemon = True
        scheduler_thread_obj.start()
        
        # جدولة المهام النشطة
        for group_id, group_data in db.get_all_groups().items():
            if group_data.get("active") and group_data.get("totp_secret"):
                schedule_2fa_task(group_id)
        
        # بدء البوت
        bot.infinity_polling()
    
    except KeyboardInterrupt:
        logger.info("تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"حدث خطأ: {e}")
    finally:
        logger.info("إيقاف البوت...")

if __name__ == "__main__":
    main()

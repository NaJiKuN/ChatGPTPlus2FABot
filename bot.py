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
    
    markup.add(btn_add_group, btn_set_interval, btn_message_format)
    
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('copy_'))
def handle_copy_code(call):
    """معالجة نسخ رمز المصادقة في الوقت الفعلي"""
    parts = call.data.split('_', 3)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "خطأ في البيانات")
        return
    
    # التعامل مع نسخ النص من زر النسخ في الرسالة الخاصة
    if parts[1] == "text":
        text_to_copy = parts[2]
        bot.answer_callback_query(
            call.id,
            text=f"تم نسخ الرمز: {text_to_copy}",
            show_alert=False
        )
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
    
    # إرسال الرمز في رسالة خاصة للمستخدم ليكون قابلاً للنسخ
    try:
        # إرسال الرمز في رسالة خاصة بتنسيق محسن مع زر نسخ
        markup = types.InlineKeyboardMarkup()
        copy_button = types.InlineKeyboardButton(
            "نسخ الرمز",
            callback_data=f"copy_text_{totp_code}"
        )
        markup.add(copy_button)
        
        bot.send_message(
            user_id,
            f"🔐 رمز المصادقة 2FA\n\n{totp_code}\n\n⚠️ صالح لمدة 30 ثانية فقط!\n\nعدد المحاولات المتبقية: {remaining}",
            reply_markup=markup
        )
    except Exception as e:
        # في حالة فشل إرسال الرسالة الخاصة (مثلاً إذا لم يبدأ المستخدم محادثة مع البوت)
        logger.error(f"فشل في إرسال رسالة خاصة للمستخدم {user_id}: {e}")
        bot.answer_callback_query(
            call.id,
            text=f"الرمز: {totp_code}\nيرجى بدء محادثة مع البوت للحصول على رسائل خاصة.",
            show_alert=True
        )

def main():
    """الدالة الرئيسية"""
    try:
        logger.info("بدء تشغيل البوت...")
        
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

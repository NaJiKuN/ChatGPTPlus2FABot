#!/usr/bin/env python3 vv1.0
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from pytz import timezone
import pytz
import pyotp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    JobQueue,
)

# Configuration
TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
ADMINS = [764559466]
DB_PATH = '/home/ec2-user/projects/ChatGPTPlus2FABot/bot.db'
PALESTINE_TZ = timezone('Asia/Gaza')

# Initialize database
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS groups
             (group_id TEXT PRIMARY KEY, 
              totp_secret TEXT,
              interval INTEGER DEFAULT 10,
              is_active INTEGER DEFAULT 1,
              time_format TEXT DEFAULT '24h',
              timezone TEXT DEFAULT 'UTC',
              max_clicks INTEGER DEFAULT 3)''')
c.execute('''CREATE TABLE IF NOT EXISTS clicks
             (user_id TEXT, 
              group_id TEXT,
              count INTEGER,
              PRIMARY KEY(user_id, group_id))''')
conn.commit()
conn.close()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_group_data(group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM groups WHERE group_id=?", (group_id,))
    data = c.fetchone()
    conn.close()
    return data

def update_group_data(group_id, field, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE groups SET {field}=? WHERE group_id=?", (value, group_id))
    conn.commit()
    conn.close()

def track_click(user_id, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO clicks VALUES (?, ?, 0)
              ON CONFLICT(user_id, group_id) DO UPDATE SET count=count+1''',
              (user_id, group_id))
    conn.commit()
    conn.close()

def get_remaining_clicks(user_id, group_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT max_clicks FROM groups WHERE group_id=?", (group_id,))
    max_clicks = c.fetchone()[0]
    c.execute("SELECT count FROM clicks WHERE user_id=? AND group_id=?", (user_id, group_id))
    current = c.fetchone()[0] if c.fetchone() else 0
    conn.close()
    return max_clicks - current

def generate_code(secret):
    return pyotp.TOTP(secret).now()

def get_next_update_time(interval, tz):
    now = datetime.now(pytz.timezone(tz))
    next_time = now + timedelta(minutes=interval)
    return next_time

def format_time(dt, time_format, tz):
    local_dt = dt.astimezone(pytz.timezone(tz))
    if time_format == '12h':
        return local_dt.strftime("%I:%M:%S %p")
    return local_dt.strftime("%H:%M:%S")

def send_2fa_message(context):
    job = context.job
    group_id = job.context['group_id']
    data = get_group_data(group_id)
    
    if not data or not data[3]:  # Check if active
        return
    
    secret, interval, _, _, time_format, tz, max_clicks = data
    code = generate_code(secret)
    next_time = get_next_update_time(interval, tz)
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📋 Copy Code",
            callback_data=f"show_code:{group_id}"
        )
    ]])
    
    message = [
        "🔐 2FA Verification Code",
        "",
        f"Next code at: {format_time(next_time, time_format, tz)}"
    ]
    
    context.bot.send_message(
        chat_id=group_id,
        text='\n'.join(message),
        reply_markup=keyboard
    )

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome to 2FA Bot!")

def admin_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if str(user_id) not in ADMINS:
        return
    
    keyboard = [
        [InlineKeyboardButton("Add/Edit Group", callback_data='admin_add_group')],
        [InlineKeyboardButton("Set Interval", callback_data='admin_set_interval')],
        [InlineKeyboardButton("Customize Message", callback_data='admin_customize')]
    ]
    
    update.message.reply_text(
        "Admin Panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_admin_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    
    if data == 'admin_add_group':
        query.message.reply_text("Please enter Group ID:")
        context.user_data['admin_action'] = 'add_group'
    
    elif data.startswith('admin_set_interval:'):
        group_id = data.split(':')[1]
        context.user_data['selected_group'] = group_id
        query.message.reply_text("Enter new interval in minutes:")
        context.user_data['admin_action'] = 'set_interval'
    
    elif data.startswith('show_code:'):
        group_id = data.split(':')[1]
        user_id = query.from_user.id
        remaining = get_remaining_clicks(user_id, group_id)
        
        if remaining <= 0:
            query.answer("No remaining attempts!", show_alert=True)
            return
        
        secret = get_group_data(group_id)[1]
        code = generate_code(secret)
        track_click(user_id, group_id)
        
        query.answer(f"Code: {code} (Remaining: {remaining-1})", show_alert=True)

def handle_admin_input(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if str(user_id) not in ADMINS:
        return
    
    action = context.user_data.get('admin_action')
    text = update.message.text
    
    if action == 'add_group':
        # Verify group exists and bot is admin
        try:
            chat = context.bot.get_chat(text)
            if chat.type != 'supergroup':
                raise Exception()
                
            admins = context.bot.get_chat_administrators(text)
            if not any(admin.user.id == context.bot.id for admin in admins):
                raise Exception()
            
            # Save group
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR IGNORE INTO groups(group_id) VALUES (?)''', (text,))
            conn.commit()
            conn.close()
            
            update.message.reply_text("Group added! Now send TOTP_SECRET:")
            context.user_data['admin_action'] = 'add_secret'
            context.user_data['current_group'] = text
            
        except Exception as e:
            update.message.reply_text("Invalid group or bot not admin!")
            context.user_data.clear()
    
    elif action == 'add_secret':
        group_id = context.user_data['current_group']
        try:
            # Validate secret
            pyotp.TOTP(text).now()
            
            update_group_data(group_id, 'totp_secret', text)
            
            # Schedule job
            current_jobs = context.job_queue.get_jobs_by_name(group_id)
            for job in current_jobs:
                job.schedule_removal()
            
            data = get_group_data(group_id)
            interval = data[2]
            
            context.job_queue.run_repeating(
                send_2fa_message,
                interval=interval*60,
                first=10,
                context={'group_id': group_id},
                name=group_id
            )
            
            update.message.reply_text("Group configured successfully!")
            context.user_data.clear()
            
        except:
            update.message.reply_text("Invalid TOTP_SECRET! Try again:")

def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="Exception while handling update:", exc_info=context.error)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", admin_menu))
    
    # Callbacks
    dp.add_handler(CallbackQueryHandler(handle_admin_callback))
    
    # Messages
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_input))
    
    # Error handling
    dp.add_error_handler(error_handler)
    
    # Restore scheduled jobs
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_id, interval FROM groups WHERE is_active=1")
    active_groups = c.fetchall()
    conn.close()
    
    for group_id, interval in active_groups:
        updater.job_queue.run_repeating(
            send_2fa_message,
            interval=interval*60,
            first=10,
            context={'group_id': group_id},
            name=group_id
        )
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

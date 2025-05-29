# -*- coding: utf-8 -*-
import json
import os
import pyotp
import pytz
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CONFIG_FILE = '/home/ubuntu/ChatGPTPlus2FABot/config.json'
GROUPS_FILE = '/home/ubuntu/ChatGPTPlus2FABot/groups.json'
USERS_FILE = '/home/ubuntu/ChatGPTPlus2FABot/users.json'

# --- JSON Data Handling ---
def load_json(file_path, default_data):
    """Loads data from a JSON file. Creates the file with default data if it doesn't exist."""
    if not os.path.exists(file_path):
        save_json(file_path, default_data)
        return default_data
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Handle empty file case
            content = f.read()
            if not content:
                save_json(file_path, default_data)
                return default_data
            return json.loads(content)
    except (json.JSONDecodeError, FileNotFoundError):
        # If file is corrupted or somehow still not found, recreate it
        save_json(file_path, default_data)
        return default_data

def save_json(file_path, data):
    """Saves data to a JSON file."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving JSON to {file_path}: {e}")

# --- Load Initial Data ---
def load_config():
    return load_json(CONFIG_FILE, {"admins": [764559466], "default_attempts": 5})

def load_groups():
    return load_json(GROUPS_FILE, {})

def load_users():
    return load_json(USERS_FILE, {})

# --- Save Data ---
def save_config(config_data):
    save_json(CONFIG_FILE, config_data)

def save_groups(groups_data):
    save_json(GROUPS_FILE, groups_data)

def save_users(users_data):
    save_json(USERS_FILE, users_data)

# --- Admin Check ---
def is_admin(user_id):
    """Checks if a user ID belongs to an admin."""
    config = load_config()
    return user_id in config.get('admins', [])

# --- TOTP Generation ---
def generate_totp(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        return None
    try:
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        print(f"Error generating TOTP: {e}")
        return None

# --- Time Formatting ---
def get_formatted_time(timezone_str='UTC', include_seconds=True):
    """Gets the current time formatted as HH:MM:SS AM/PM in the specified timezone."""
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc # Default to UTC if timezone is invalid
    now = datetime.now(tz)
    time_format = "%I:%M:%S %p" if include_seconds else "%I:%M %p"
    return now.strftime(time_format)

def get_next_code_time(interval_minutes, timezone_str='UTC'):
    """Calculates the next code generation time."""
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc
    now = datetime.now(tz)
    # Calculate seconds until the next interval boundary
    seconds_in_interval = interval_minutes * 60
    time_since_epoch = now.timestamp()
    seconds_into_current_interval = time_since_epoch % seconds_in_interval
    seconds_to_next = seconds_in_interval - seconds_into_current_interval
    next_time = now + timedelta(seconds=seconds_to_next)
    return next_time.strftime("%I:%M:%S %p")

# --- Message Formatting ---
def format_scheduled_message(group_config):
    """Formats the scheduled message based on group configuration."""
    style = group_config.get('message_style', 1)
    interval = group_config.get('interval_minutes', 10)
    timezone = group_config.get('timezone', 'UTC') # Default to UTC
    if timezone.lower() == 'gaza':
        timezone = 'Asia/Gaza'
    elif timezone.lower() == 'gmt':
         timezone = 'GMT'
    else: # Default or handle other specific cases if needed
        timezone = 'UTC'

    base_text = "🔐 2FA Verification Code\n"
    next_code_at_str = get_next_code_time(interval, timezone)

    if style == 1:
        message = f"{base_text}\n:Next code at: {next_code_at_str}"
    elif style == 2:
        message = f"{base_text}\nNext code in: {interval} minutes\nNext code at: {next_code_at_str}"
    elif style == 3:
        correct_time_str = get_formatted_time(timezone)
        message = f"{base_text}\nNext code in: {interval} minutes\nCorrect Time: {correct_time_str}\nNext Code at: {next_code_at_str}"
    else: # Default to style 1 if invalid style
        message = f"{base_text}\n:Next code at: {next_code_at_str}"

    keyboard = [[InlineKeyboardButton("🔑 Copy Code", callback_data=f"copy_code_{group_config['id']}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    return message, reply_markup

# --- User Attempts Management ---
def get_user_attempts(user_id, group_id):
    """Gets remaining attempts for a user in a group. Returns default if not found or not blocked."""
    users_data = load_users()
    config = load_config()
    group_id_str = str(group_id)
    user_id_str = str(user_id)

    if group_id_str not in users_data:
        return config.get('default_attempts', 5)

    user_info = users_data[group_id_str].get(user_id_str)

    if user_info is None:
        return config.get('default_attempts', 5)

    if user_info.get('blocked', False):
        return 0 # Blocked users have 0 attempts

    return user_info.get('attempts', config.get('default_attempts', 5))

def decrement_user_attempts(user_id, group_id):
    """Decrements user attempts. Returns False if user is blocked or has no attempts left."""
    users_data = load_users()
    config = load_config()
    group_id_str = str(group_id)
    user_id_str = str(user_id)
    default_attempts = config.get('default_attempts', 5)

    if group_id_str not in users_data:
        users_data[group_id_str] = {}

    if user_id_str not in users_data[group_id_str]:
        users_data[group_id_str][user_id_str] = {'attempts': default_attempts, 'blocked': False}

    user_info = users_data[group_id_str][user_id_str]

    if user_info.get('blocked', False):
        return False # Cannot decrement if blocked

    current_attempts = user_info.get('attempts', default_attempts)
    if current_attempts <= 0:
        return False # No attempts left

    user_info['attempts'] = current_attempts - 1
    save_users(users_data)
    return True

def set_user_attempts(user_id, group_id, attempts):
    """Sets a specific number of attempts for a user."""
    users_data = load_users()
    group_id_str = str(group_id)
    user_id_str = str(user_id)

    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    if user_id_str not in users_data[group_id_str]:
        users_data[group_id_str][user_id_str] = {'attempts': attempts, 'blocked': False}
    else:
        users_data[group_id_str][user_id_str]['attempts'] = attempts
        # Ensure user is not blocked when setting attempts explicitly
        # users_data[group_id_str][user_id_str]['blocked'] = False
    save_users(users_data)

def block_user(user_id, group_id, block_status=True):
    """Blocks or unblocks a user for a specific group."""
    users_data = load_users()
    group_id_str = str(group_id)
    user_id_str = str(user_id)

    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    if user_id_str not in users_data[group_id_str]:
         # If user doesn't exist, create with 0 attempts if blocking
        users_data[group_id_str][user_id_str] = {'attempts': 0 if block_status else load_config().get('default_attempts', 5), 'blocked': block_status}
    else:
        users_data[group_id_str][user_id_str]['blocked'] = block_status
        if block_status:
             users_data[group_id_str][user_id_str]['attempts'] = 0 # Set attempts to 0 when blocking

    save_users(users_data)


# --- Group Management Helpers ---
def add_or_update_group(group_id, secret, interval=10, style=1, timezone='UTC', active=True):
    groups_data = load_groups()
    group_id_str = str(group_id)
    groups_data[group_id_str] = {
        'id': group_id,
        'secret': secret,
        'interval_minutes': interval,
        'message_style': style,
        'timezone': timezone,
        'active': active, # To control scheduling
        'job_id': f"job_{group_id}" # Store job ID for easy removal/update
    }
    save_groups(groups_data)
    return groups_data[group_id_str]

def remove_group(group_id):
    groups_data = load_groups()
    group_id_str = str(group_id)
    if group_id_str in groups_data:
        del groups_data[group_id_str]
        save_groups(groups_data)
        return True
    return False

def get_group_config(group_id):
    groups_data = load_groups()
    return groups_data.get(str(group_id))



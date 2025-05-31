import json
import pyotp
import pytz
from datetime import datetime
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
GROUPS_FILE = "groups.json"
USERS_FILE = "users.json"

# --- Data Loading/Saving --- 

def load_json(file_path, default_data=None):
    """Loads data from a JSON file. Returns default_data if file doesn't exist or is invalid."""
    if default_data is None:
        default_data = {}
    try:
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} not found. Creating with default data.")
            save_json(file_path, default_data)
            return default_data
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error loading JSON from {file_path}: {e}. Returning default data.")
        # Optionally, create a backup of the corrupted file here
        return default_data

def save_json(file_path, data):
    """Saves data to a JSON file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        # logger.debug(f"Data successfully saved to {file_path}") # Too verbose for INFO
    except IOError as e:
        logger.error(f"Error saving JSON to {file_path}: {e}")

def load_config():
    """Loads bot configuration."""
    return load_json(CONFIG_FILE, default_data={"admins": [], "default_attempts": 5})

def save_config(config_data):
    """Saves bot configuration."""
    save_json(CONFIG_FILE, config_data)

def load_groups():
    """Loads group data."""
    return load_json(GROUPS_FILE, default_data={})

def save_groups(groups_data):
    """Saves group data."""
    save_json(GROUPS_FILE, groups_data)

def load_users():
    """Loads user data."""
    return load_json(USERS_FILE, default_data={})

def save_users(users_data):
    """Saves user data."""
    save_json(USERS_FILE, users_data)

# --- TOTP Generation --- 

def generate_totp(secret):
    """Generates the current TOTP code for a given secret."""
    if not secret:
        logger.warning("Attempted to generate TOTP with an empty secret.")
        return None
    try:
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        logger.error(f"Error generating TOTP: {e}")
        return None

# --- Time Formatting --- 

SUPPORTED_TIMEZONES = {
    "GMT": "Etc/GMT",
    "غزة": "Asia/Gaza", # Gaza Timezone
    "UTC": "UTC"
}

def get_formatted_time(timezone_key="UTC"):
    """Gets the current time formatted as HH:MM:SS AM/PM in the specified timezone."""
    tz_str = SUPPORTED_TIMEZONES.get(timezone_key, "UTC")
    try:
        tz = pytz.timezone(tz_str)
        now_utc = datetime.now(pytz.utc)
        now_local = now_utc.astimezone(tz)
        return now_local.strftime("%I:%M:%S %p") # 12-hour format with AM/PM and seconds
    except pytz.UnknownTimeZoneError:
        logger.error(f"Unknown timezone key: {timezone_key}. Falling back to UTC.")
        now_utc = datetime.now(pytz.utc)
        return now_utc.strftime("%I:%M:%S %p")

def get_remaining_time_in_interval(interval_seconds=30):
    """Calculates remaining seconds until the next TOTP interval."""
    current_timestamp = datetime.now().timestamp()
    remaining = interval_seconds - (current_timestamp % interval_seconds)
    return int(remaining)

# --- User Attempt Management --- 

def get_user_attempts(user_id, group_id, users_data, config_data):
    """Gets remaining attempts for a user in a group. Returns -1 if blocked, None if error."""
    group_id_str = str(group_id)
    user_id_str = str(user_id)
    default_attempts = config_data.get("default_attempts", 5)

    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    
    user_info = users_data[group_id_str].get(user_id_str)

    if user_info is None:
        # First time user in this group, initialize with default attempts
        users_data[group_id_str][user_id_str] = {"attempts": default_attempts, "blocked": False}
        save_users(users_data) # Save the new user entry
        return default_attempts
    
    if user_info.get("blocked", False):
        return -1 # Blocked
        
    return user_info.get("attempts", default_attempts)

def decrement_user_attempts(user_id, group_id, users_data):
    """Decrements attempts for a user. Returns True if successful, False otherwise."""
    group_id_str = str(group_id)
    user_id_str = str(user_id)

    if group_id_str in users_data and user_id_str in users_data[group_id_str]:
        if not users_data[group_id_str][user_id_str].get("blocked", False):
            current_attempts = users_data[group_id_str][user_id_str].get("attempts", 0)
            if current_attempts > 0:
                users_data[group_id_str][user_id_str]["attempts"] = current_attempts - 1
                save_users(users_data)
                return True
    return False # User not found, blocked, or already at 0 attempts

def set_user_attempts(user_id, group_id, attempts, users_data):
    """Sets a specific number of attempts for a user."""
    group_id_str = str(group_id)
    user_id_str = str(user_id)
    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    if user_id_str not in users_data[group_id_str]:
         users_data[group_id_str][user_id_str] = {"attempts": 0, "blocked": False} # Initialize if not exists
    
    users_data[group_id_str][user_id_str]["attempts"] = max(0, attempts) # Ensure attempts are not negative
    save_users(users_data)

def add_user_attempts(user_id, group_id, attempts_to_add, users_data):
    """Adds attempts for a user."""
    group_id_str = str(group_id)
    user_id_str = str(user_id)
    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    if user_id_str not in users_data[group_id_str]:
         users_data[group_id_str][user_id_str] = {"attempts": 0, "blocked": False}

    current_attempts = users_data[group_id_str][user_id_str].get("attempts", 0)
    users_data[group_id_str][user_id_str]["attempts"] = current_attempts + max(0, attempts_to_add)
    save_users(users_data)

def block_user(user_id, group_id, users_data, block=True):
    """Blocks or unblocks a user in a specific group."""
    group_id_str = str(group_id)
    user_id_str = str(user_id)
    if group_id_str not in users_data:
        users_data[group_id_str] = {}
    if user_id_str not in users_data[group_id_str]:
         users_data[group_id_str][user_id_str] = {"attempts": 0, "blocked": False}
         
    users_data[group_id_str][user_id_str]["blocked"] = block
    save_users(users_data)

# --- Helper for Message Formatting ---
def format_interval(seconds):
    """Formats seconds into a human-readable interval (e.g., 10 minutes, 1 hour)."""
    if seconds < 60:
        return f"{seconds} ثانية" # seconds
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} دقيقة" # minutes
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} ساعة" # hours
    else:
        days = seconds // 86400
        return f"{days} يوم" # days

def escape_markdown_v2(text):
    """Escapes characters for Telegram MarkdownV2."""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in str(text))


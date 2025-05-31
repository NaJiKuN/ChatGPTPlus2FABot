# /home/ec2-user/projects/ChatGPTPlus2FABot/totp_utils.py
import pyotp
import time
import base64

def generate_totp(secret):
    """Generates a TOTP code for the given secret."""
    totp_instance = pyotp.TOTP(secret)
    return totp_instance.now()

def get_remaining_seconds():
    """Gets the remaining seconds until the next TOTP code generation."""
    # pyotp doesn\\'t directly expose remaining time easily without the interval
    # Assuming standard 30-second interval
    return 30 - (int(time.time()) % 30)

def validate_totp_secret(secret):
    """Validates if the provided string is a valid Base32 secret."""
    try:
        # Attempt to decode the base32 string. If it fails, it\\'s not valid base32.
        base64.b32decode(secret, casefold=True)
        # Check if the length is appropriate (multiples of 8 bytes usually, but pyotp might be flexible)
        # A simple check for non-empty string might suffice for basic validation
        return bool(secret)
    except Exception:
        return False

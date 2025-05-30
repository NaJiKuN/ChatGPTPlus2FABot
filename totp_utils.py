# /home/ubuntu/ChatGPTPlus2FABot/totp_utils.py
import pyotp
import base64
import logging

logger = logging.getLogger(__name__)

def is_valid_totp_secret(secret):
    """Checks if the provided string is a potentially valid base32 TOTP secret."""
    if not secret or not isinstance(secret, str):
        return False
    # Basic check: Length should be a multiple of 8, contains valid base32 chars.
    # pyotp handles padding, so we don't need strict length check, but it should not be empty.
    secret = secret.upper().replace(" ", "")
    valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
    if not all(c in valid_chars for c in secret):
        return False
    try:
        # Attempt to decode to ensure it's valid base32
        base64.b32decode(secret)
        return True
    except Exception as e:
        logger.warning(f"Invalid base32 secret provided: {secret}. Error: {e}")
        return False

def generate_totp_code(secret):
    """Generates the current TOTP code for the given secret."""
    if not is_valid_totp_secret(secret):
        logger.error(f"Attempted to generate TOTP with invalid secret: {secret[:5]}..."
        )
        # Return None or raise an error, depending on desired handling
        # Returning a placeholder might be confusing, so None is better.
        return None
    try:
        totp = pyotp.TOTP(secret)
        return totp.now()
    except Exception as e:
        logger.error(f"Error generating TOTP code: {e}")
        return None

def get_time_remaining():
    """Returns the number of seconds remaining in the current TOTP interval (30 seconds)."""
    # pyotp doesn't directly expose this easily, but we can calculate it.
    import time
    interval = 30
    return interval - (int(time.time()) % interval)

# Example usage (for testing)
if __name__ == "__main__":
    # Replace with a valid test secret if needed
    test_secret = "JBSWY3DPEHPK3PXP"
    if is_valid_totp_secret(test_secret):
        print(f"Secret {test_secret} is valid.")
        code = generate_totp_code(test_secret)
        remaining = get_time_remaining()
        print(f"Current TOTP code: {code}")
        print(f"Time remaining in interval: {remaining} seconds")
    else:
        print(f"Secret {test_secret} is invalid.")

    invalid_secret = "INVALIDSECRET1"
    if not is_valid_totp_secret(invalid_secret):
        print(f"Secret {invalid_secret} is correctly identified as invalid.")

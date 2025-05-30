import base64
import hmac
import struct
import time

def validate_totp_secret(secret):
    """Validates if the provided TOTP secret is a valid base32 string."""
    try:
        secret = secret.replace(" ", "").upper()  # Remove spaces and convert to uppercase
        base64.b32decode(secret, casefold=True)  # Try decoding to check if valid base32
        return True
    except Exception:
        return False

def generate_totp(secret, interval=30):
    """Generates a TOTP code based on the provided secret."""
    try:
        # Decode the base32 secret
        secret = secret.replace(" ", "").upper()
        key = base64.b32decode(secret, casefold=True)

        # Get the current timestamp and calculate the time step
        timestamp = int(time.time())
        counter = timestamp // interval

        # Pack the counter into a byte string
        msg = struct.pack(">Q", counter)

        # Generate HMAC-SHA1 hash
        hash_obj = hmac.new(key, msg, "sha1")
        hmac_hash = hash_obj.digest()

        # Dynamic truncation: Get the last 4 bits of the hash to determine the offset
        offset = hmac_hash[-1] & 0x0F

        # Extract 4 bytes starting from the offset
        binary_code = (
            (hmac_hash[offset] & 0x7F) << 24 |
            (hmac_hash[offset + 1] & 0xFF) << 16 |
            (hmac_hash[offset + 2] & 0xFF) << 8 |
            (hmac_hash[offset + 3] & 0xFF)
        )

        # Generate a 6-digit code
        code = binary_code % 1000000
        return f"{code:06d}"  # Ensure the code is 6 digits with leading zeros
    except Exception as e:
        print(f"Error generating TOTP: {e}")
        return None

def get_remaining_seconds(interval=30):
    """Calculates the remaining seconds until the next TOTP code."""
    timestamp = int(time.time())
    elapsed = timestamp % interval
    return interval - elapsed

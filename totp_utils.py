import pyotp
import time
import re

def validate_totp_secret(secret):
    """
    التحقق من صحة المفتاح السري TOTP.
    
    Args:
        secret (str): المفتاح السري المراد التحقق منه.
        
    Returns:
        bool: True إذا كان المفتاح صالحاً، False خلاف ذلك.
    """
    # التحقق من أن المفتاح ليس فارغاً
    if not secret or not isinstance(secret, str):
        return False
    
    # التحقق من أن المفتاح يحتوي على أحرف صالحة فقط (Base32)
    if not re.match(r'^[A-Z2-7]+$', secret.upper()):
        return False
    
    # محاولة إنشاء كائن TOTP
    try:
        totp = pyotp.TOTP(secret.upper())
        # محاولة توليد رمز للتأكد من أن المفتاح صالح
        totp.now()
        return True
    except Exception:
        return False

def generate_totp(secret):
    """
    توليد رمز TOTP باستخدام المفتاح السري.
    
    Args:
        secret (str): المفتاح السري TOTP.
        
    Returns:
        str: رمز TOTP المولد.
    """
    totp = pyotp.TOTP(secret.upper())
    return totp.now()

def get_remaining_seconds():
    """
    حساب عدد الثواني المتبقية حتى توليد الرمز التالي.
    
    Returns:
        int: عدد الثواني المتبقية.
    """
    # TOTP يتغير كل 30 ثانية بشكل افتراضي
    return 30 - int(time.time()) % 30

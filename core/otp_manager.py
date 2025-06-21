# core/services/otp_manager.py

import random
import redis
from django.conf import settings
from core.services import send_sms
from datetime import timedelta
from django.utils import timezone
from core.logging import log_security_event
from urllib.parse import urlparse


REDIS_URL = settings.REDIS_URL  # Ensure this is set in your settings.py
redis_url = urlparse(REDIS_URL)

redis_client = redis.StrictRedis(
    host=redis_url.hostname,
    port=redis_url.port,
    password=redis_url.password,
    db=0,  # or set from redis_url.path if needed
    decode_responses=True,
    ssl=True  # Upstash requires SSL
)
class OTPManager:
    OTP_TTL = 300  # 5 minutes
    MAX_ATTEMPTS = 3
    LOCKOUT_DURATION = 900  # 15 minutes

    @staticmethod
    def _otp_key(user_id):
        return f"otp:{user_id}"

    @staticmethod
    def _attempts_key(user_id):
        return f"otp_attempts:{user_id}"

    @staticmethod
    def _lockout_key(user_id):
        return f"otp_locked:{user_id}"

    @classmethod
    def generate_otp(cls, user):
        if redis_client.exists(cls._lockout_key(user.id)):
            raise PermissionError("Too many failed attempts. Try again later.")

        otp = f"{random.randint(100000, 999999)}"
        redis_client.setex(cls._otp_key(user.id), cls.OTP_TTL, otp)
        redis_client.delete(cls._attempts_key(user.id))  # reset attempts

        send_sms(user.phone_number, f"Your OTP is: {otp}. It expires in 5 minutes.")
        return otp  # For internal use or testing

    @classmethod
    def verify_otp(cls, user, submitted_otp, ip_address=None):
        if redis_client.exists(cls._lockout_key(user.id)):
            return False, "Account temporarily locked due to repeated failures."

        stored_otp = redis_client.get(cls._otp_key(user.id))
        if not stored_otp:
            return False, "OTP expired or not found."

        if stored_otp != submitted_otp:
            attempts = redis_client.incr(cls._attempts_key(user.id))
            redis_client.expire(cls._attempts_key(user.id), cls.OTP_TTL)

            if attempts >= cls.MAX_ATTEMPTS:
                redis_client.setex(cls._lockout_key(user.id), cls.LOCKOUT_DURATION, "locked")
                # Optional: log the lockout event
                log_security_event(user.id, ip_address, reason="OTP brute-force detected")
                return False, "Too many invalid attempts. You are locked out."

            return False, f"Invalid OTP. Attempt {attempts} of {cls.MAX_ATTEMPTS}."

        # Success
        redis_client.delete(cls._otp_key(user.id))
        redis_client.delete(cls._attempts_key(user.id))
        return True, None

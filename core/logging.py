from django.utils import timezone
import logging
logger = logging.getLogger(__name__)

def log_security_event(user_id, ip, reason):
    logger.warning(f"SECURITY: user_id={user_id}, ip={ip}, reason={reason}, time={timezone.now()}")
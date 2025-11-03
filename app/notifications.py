import logging
from .firebase import firebase_admin
from celery import current_app
from . import db
from .models import Notification, User
from firebase_admin import messaging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_notification(user_id, title, message, notif_type, related_secret_id=None, scheduled_for=None):
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=notif_type,
        related_secret_id=related_secret_id,
        scheduled_for=scheduled_for,
        sent_at = datetime.now(),
    )
    db.session.add(notif)
    # ⚠️ Don't commit here — let caller commit once after batch
    return notif


def send_push_notification(fcm_token, title, message):
    """Send Firebase push notification."""
    if not fcm_token:
        return False
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=message),
        token=fcm_token
    )
    try:
        messaging.send(msg)
        return True
    except Exception as e:
        print(f"❌ Push notification failed: {e}")
        return False


def send_and_log_notification(user_id, title, message, notif_type, related_secret_id=None):
    """Send push + log notification."""
    user = db.session.get(User, user_id)
    db.session.expire(user)  # reload from DB
    if not user:
        logger.error(f"User {user_id} not found")
        return False

    logger.info(f"Sending to {user.username} | FCM: {user.fcm_token}")
    sent = send_push_notification(user.fcm_token, title, message)
    logger.info(f"Push sent: {sent}")
    create_notification(user.id, title, message, notif_type, related_secret_id)
    db.session.commit()
    return sent


def _notify_secret(secret, phase):
    user = secret.user or secret.sender
    if not user:
        return

    messages = {
        "month": f"Your shared secret '{secret.title}' will be sent in about a month.\n⚠️ Opening the app will extend the sending date.",
        "5_days": f"Your shared secret '{secret.title}' will be sent in 5 days.\n⚠️ Opening the app will extend the sending date.",
        "hour": f"Your shared secret '{secret.title}' will be sent in 1 hour.\n⚠️ Opening the app will extend the sending date.",
    }

    notif_type = f"secret_reminder_{phase}"
    send_and_log_notification(
        user.id,
        "Shared Secret Reminder",
        messages[phase],
        notif_type,
        related_secret_id=secret.id  # ← CRITICAL
    )


def _notify_subscription(user, phase):
    messages = {
        "5_days": "Your subscription will renew in 5 days.",
        "1_day": "Your subscription will renew tomorrow.",
    }
    send_and_log_notification(
        user.id,
        "Subscription Reminder",
        messages[phase],
        f"subscription_{phase}"
    )


def _notify_end_trial(user, phase):
    messages = {
        "7_days": "Your free trial will end in a week.",
        "1_day": "Your free trial will end tomorrow.",
    }
    send_and_log_notification(
        user.id,
        "Free Trial Ending Soon",
        messages[phase],
        f"free_trial_{phase}"
    )

def _notify_inactivity_reminder(user, phase):
    messages = {
        "60_days": "Your account has been inactive for a long time.",
        "month": "It's been a month since your last login.",
        "2_weeks": "You haven’t logged in for 2 weeks.",
    }

    send_and_log_notification(
        user.id,
        "We miss you!",
        messages[phase],
        f"inactivity_reminder_{phase}"
    )


from . import db
from .models import Notification, User
from firebase_admin import messaging

def create_notification(user_id, title, message, notif_type, related_secret_id=None, scheduled_for=None):
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=notif_type,
        related_secret_id=related_secret_id,
        scheduled_for=scheduled_for,
    )
    db.session.add(notif)
    db.session.commit()
    return notif

def send_push_notification(fcm_token, title, message):
    """Send Firebase push"""
    if not fcm_token:
        return False
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=message),
        token=fcm_token
    )
    messaging.send(msg)
    return True

def send_and_log_notification(user_id, title, message, notif_type, related_secret_id=None):
    """Send and record notification"""
    user = User.query.get(user_id)
    if not user:
        return
    sent = send_push_notification(user.fcm_token, title, message)
    create_notification(user.id, title, message, notif_type, related_secret_id)
    return sent

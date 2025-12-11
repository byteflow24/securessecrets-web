from celery import Celery
from celery.schedules import crontab
from flask import url_for, current_app
from celery import shared_task

from .utils import decrypt_secret, send_whatsapp_message
from .models import SharedSecret, Notification, User, LoginHistory
from .notifications import _notify_secret, _notify_subscription, _notify_end_trial, send_and_log_notification, _notify_inactivity_reminder
from . import db
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
import logging
import os



logging.basicConfig(level=logging.INFO)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


celery = Celery(__name__, broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
# celery = Celery(__name__, broker='redis://localhost:6379/0')


def create_celery_app(app=None):
    if app is None:
        from . import create_app
        app = create_app()
    celery.conf.update(app.config)
    celery.conf.update(
        task_annotations={'*': {'rate_limit': '10/s'}},
        worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] %(message)s",
        worker_task_log_format="[%(asctime)s: %(levelname)s/%(task_name)s] %(message)s",
    )
    celery.conf.worker_prefetch_multiplier = 1
    celery.conf.broker_connection_retry_on_startup = True
    celery.conf.beat_schedule = {
        'check-scheduled-secrets-every-minute': { # check_scheduled_secrets
            'task': 'app.celery_worker.check_scheduled_secrets',
            'schedule': crontab(minute='*'), # ← every minute for testing
        },
        'check_last_login-every-minute': {
            'task': 'app.celery_worker.check_last_login',
            'schedule': crontab(minute='*'),
        },
        'check-scheduled-notifications-every-minute': {
            'task': 'app.celery_worker.check_scheduled_notifications',
            'schedule': crontab(minute='*'),  # ← every minute for testing
        },
    }
    celery.conf.timezone = 'UTC'
    celery.Task = ContextTask
    return celery

class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        if not current_app:
            from . import create_app
            with create_app().app_context():
                return super().__call__(*args, **kwargs)
        else:
            return super().__call__(*args, **kwargs)

celery = create_celery_app()



# Celery task for sending the email asynchronously
@celery.task
def send_email_task(email, token, fname, lname, login_check_del, scheduled_check_del):
    logger.info("Task started")
    from .utils import send_secret_email
    
    with current_app.app_context():
        secret_url = url_for('main.only_for_you', token=token, _external=True)

    # Clean the email by stripping curly braces and any extra spaces
    clean_email = email.strip("{}").strip()  # Strip both curly braces and extra spaces

    # Call the email sending function
    send_secret_email(clean_email, secret_url, fname, lname, login_check_del, scheduled_check_del)


@shared_task
def check_scheduled_secrets():
    now = datetime.now()
    scheduled_secrets = SharedSecret.query.filter(
        SharedSecret.date_to_send == now.date(),
        SharedSecret.time_to_send == now.time().replace(second=0, microsecond=0),
        SharedSecret.received == False
    ).all()

    for secret in scheduled_secrets:

        # --- Send Email ---
        if secret.email:
            emails = []
            if isinstance(secret.email, dict):
                emails = [secret.email.get("value", "")]
            elif isinstance(secret.email, str):
                # Split by comma, strip braces and spaces
                emails = [e.strip("{} ").strip() for e in secret.email.split(",") if e.strip()]
            
            for email_value in emails:
                if email_value:
                    send_email_task.apply_async(args=[
                        email_value,
                        secret.token,
                        secret.first_name,
                        secret.last_name,
                        secret.public_confirm_deletion,
                        secret.scheduled_confirm_deletion
                        ])

        # --- Send WhatsApp ---
        if secret.phone:
            phones = []
            if isinstance(secret.phone, dict):
                phones = [secret.phone.get("value", "")]
            elif isinstance(secret.phone, str):
                phones = [p.strip("{} ").replace(" ", "") for p in secret.phone.split(",") if p.strip()]
            
            file_url = url_for(
                'main.download_file',
                filename=secret.file,
                token=secret.token,
                _external=True,
                twilio="true"
            ) if secret.file else None
            
            for phone_value in phones:
                if phone_value:
                    send_whatsapp_message(
                        to_number=phone_value,
                        sender_name=f"{secret.first_name} {secret.last_name}",
                        secret_text=decrypt_secret(secret.snapshot_secret),
                        timestamp=str(now),
                        file_url=file_url
                    )

        # Mark it as sent
        secret.received = True

    db.session.commit()

@celery.task(name="app.celery_worker.check_last_login")
def check_last_login():

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    last_login_secrets = SharedSecret.query.filter(
        SharedSecret.time_period == now,
        SharedSecret.received == False
    ).all()

    for secret in last_login_secrets:

        # --- Send Email ---
        if secret.email:
            emails = []
            if isinstance(secret.email, dict):
                emails = [secret.email.get("value", "")]
            elif isinstance(secret.email, str):
                # Split by comma, strip braces and spaces
                emails = [e.strip("{} ").strip() for e in secret.email.split(",") if e.strip()]
            
            for email_value in emails:
                if email_value:
                    send_email_task.apply_async(args=[
                        email_value,
                        secret.token,
                        secret.first_name,
                        secret.last_name,
                        secret.public_confirm_deletion,
                        secret.scheduled_confirm_deletion
                        ])

        # --- Send WhatsApp ---
        if secret.phone:
            phones = []
            if isinstance(secret.phone, dict):
                phones = [secret.phone.get("value", "")]
            elif isinstance(secret.phone, str):
                phones = [p.strip("{} ").replace(" ", "") for p in secret.phone.split(",") if p.strip()]
            
            file_url = url_for(
                'main.download_file',
                filename=secret.file,
                token=secret.token,
                _external=True,
                twilio="true"
            ) if secret.file else None
            
            for phone_value in phones:
                if phone_value:
                    send_whatsapp_message(
                        to_number=phone_value,
                        sender_name=f"{secret.first_name} {secret.last_name}",
                        secret_text=decrypt_secret(secret.snapshot_secret),
                        timestamp=str(now),
                        file_url=file_url
                    )

        # Mark it as sent
        secret.received = True

    db.session.commit()


@celery.task(bind=True, base=ContextTask)
def check_scheduled_notifications(self):
    logger.info("🔔 Running check_scheduled_notifications task")
    now = datetime.now(timezone.utc)
    
    # === 1. Shared Secrets Reminders ===
    secrets = SharedSecret.query.filter_by(received=False).all()
    for secret in secrets:
        if not (secret.date_to_send or secret.time_period):
            continue

        target_time = (
            datetime.combine(secret.date_to_send, secret.time_to_send)
            if secret.date_to_send and secret.time_to_send
            else secret.time_period
        )
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)

        delta = target_time - now
        days_left = delta.days
        hours_left = delta.total_seconds() // 3600

        # Define phases
        phases = [
            ("month", 30, "secret_reminder_month"),
            ("5_days", 5, "secret_reminder_5_days"),
            ("hour", 1, "secret_reminder_hour"),
        ]

        for phase_name, threshold, notif_type in phases:
            # Check exact day/hour match
            if (phase_name == "month" and days_left == 30) or \
                (phase_name == "5_days" and 3 <= days_left <= 5) or \
                (phase_name == "hour" and hours_left == 1):

                    already_sent = Notification.query.filter_by(
                        user_id=secret.user_id or secret.sender_id,
                        type=notif_type,
                        related_secret_id=secret.id
                    ).first()

                    if not already_sent:
                        _notify_secret(secret, phase_name)  # ← This now sends BOTH push + email
                        logger.info(f"Sent {phase_name} reminder (push + email) for secret {secret.id}")
                    else:
                        logger.info(f"Skipped {phase_name} — already sent")

    # === 2. Subscription Renewal ===
    # for user in User.query.filter(User.username != "admin", User.next_billing_date.isnot(None)).all():
        # next_date = user.next_billing_date
        # if next_date and next_date.tzinfo is None:
        #     next_date = next_date.replace(tzinfo=timezone.utc)
        # delta = next_date - now
        # days_left = delta.days

        # phases = [
        #     ("5_days", 5, "subscription_5_days"),
        #     ("1_day", 1, "subscription_1_day"),
        # ]

        # for phase, days, notif_type in phases:
        #     if days_left == days:
        #         if not Notification.query.filter_by(user_id=user.id, type=notif_type).first():
        #             _notify_subscription(user, phase)

    # === 3. Trial End ===
    for user in User.query.filter(User.trial_end_date.isnot(None)).all():
        trial_end = user.trial_end_date
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        delta = trial_end - now
        days_left = delta.days

        phases = [
            ("7_days", 7, "free_trial_7_days"),
            ("1_day", 1, "free_trial_1_day"),
        ]

        for phase, days, notif_type in phases:
            if days_left == days:
                if not Notification.query.filter_by(user_id=user.id, type=notif_type).first():
                    _notify_end_trial(user, phase)  # ← Sends BOTH push + email
                    logger.info(f"Sent trial {phase} reminder to {user.username}")

    # === 4. Inactivity Reminder ===
    phases = [
        ("60_days", 60, "inactivity_reminder_60_days"),
        ("month", 30, "inactivity_reminder_month"),
        ("2_weeks", 14, "inactivity_reminder_2_weeks"),
    ]

    users = (
        db.session.query(User, func.max(LoginHistory.login_time).label("last_login"))
        .join(LoginHistory, User.id == LoginHistory.user_id)
        .group_by(User.id)
        .all()
    )

    for user, last_login in users:
        if not last_login:
            continue

        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=timezone.utc)

        delta_days = (now - last_login).days

        for phase, days, notif_type in phases:
            # Check if user matches this inactivity window
            if days <= delta_days < days + 3:
                already_sent = Notification.query.filter_by(
                    user_id=user.id,
                    type=notif_type
                ).first()
                if already_sent:
                    break  # don’t resend the same phase

                _notify_inactivity_reminder(user, phase)

                # === Handle Last Login Shared Secret Warning ===
                shared_secret = SharedSecret.query.filter(
                    SharedSecret.user_id == user.id,
                    SharedSecret.received == False,
                    SharedSecret.time_period.isnot(None),
                    (SharedSecret.date_to_send.is_(None)) &
                    (SharedSecret.time_to_send.is_(None))
                ).first()

                if shared_secret:
                    already_sent_warning = Notification.query.filter(
                        Notification.user_id == user.id,
                        Notification.type == "last_login_warning",
                        Notification.sent_at.isnot(None),
                        Notification.sent_at > now - timedelta(days=30)
                    ).first()

                    if not already_sent_warning:
                        send_and_log_notification(
                            user.id,
                            "Last Login Secret Warning",
                            "You have an active 'Last Login' shared secret. Avoid opening the app unless you intend to reset its timer.",
                            "last_login_warning"
                        )
                break  # stop after sending one reminder phase



# pending_notifs = Notification.query.filter(
#     Notification.scheduled_for <= now,
#     Notification.sent_at.is_(None)
# ).all()

# for notif in pending_notifs:
#     user = notif.user
#     if user and user.fcm_token:
#         from .notifications import send_push_notification
#         send_push_notification(user.fcm_token, notif.title, notif.message)
#         notif.sent_at = datetime.now(timezone.utc)
#         db.session.commit()

# @celery.task
# def test_task():
#     logger.info("Test task executed.")



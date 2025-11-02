from celery import Celery
from celery.schedules import crontab
from flask import url_for, current_app
from celery import shared_task
from .models import SharedSecret, Notification, User, LoginHistory
from .notifications import _notify_secret, _notify_subscription, _notify_end_trial, send_and_log_notification
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
        'check-scheduled-secrets-every-minute': {
            'task': 'app.celery_worker.check_scheduled_secrets',
            'schedule': crontab(minute='*'),
        },
        'check-scheduled-notifications-every-minute': {  # ← renamed
            'task': 'app.celery_worker.check_scheduled_notifications',
            'schedule': crontab(minute='*'),  # ← every minute for testing
        },
        'trial-end-reminder-now': {
            'task': 'app.celery_worker.trial_end_reminder_task',
            'schedule': 60,  # ← every 60 seconds
        },
        'not-paid-reminder-now': {
            'task': 'app.celery_worker.not_paied_reminder_task',
            'schedule': 60,
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
def send_email_task(email, token):
    logger.info("Task started")
    from .utils import send_secret_email
    
    with current_app.app_context():
        secret_url = url_for('main.only_for_you', token=token, _external=True)

    # Clean the email by stripping curly braces and any extra spaces
    clean_email = email.strip("{}").strip()  # Strip both curly braces and extra spaces

    # Call the email sending function
    send_secret_email(clean_email, secret_url)


@shared_task
def check_scheduled_secrets():
    now = datetime.now()
    scheduled_secrets = SharedSecret.query.filter(
        SharedSecret.date_to_send == now.date(),
        SharedSecret.time_to_send == now.time().replace(second=0, microsecond=0),
        SharedSecret.received == False
    ).all()

    for secret in scheduled_secrets:
        # Split emails if multiple, strip curly braces and spaces for each
        email_list = [email.strip("{}").strip() for email in secret.email.split(",")]
        
        for email in email_list:
            # Send each email using the task
            send_email_task.apply_async(args=[email, secret.token])

            secret.received = True  # Mark it as sent
        db.session.commit()


@celery.task
def trial_end_reminder_task():
    logger.info("Running trial end reminder task...")
    from .utils import trial_end_reminder
    trial_end_reminder()
    logger.info("trial_end_reminder_task FINISHED")

@celery.task
def not_paied_reminder_task():
    logger.info("Running not paid reminder task...")
    from .utils import not_paied_reminder
    not_paied_reminder()
    logger.info("not_paied_reminder_task FINISHED")


@celery.task
def check_scheduled_notifications():
    with current_app.app_context():
        logger.info("🔔 Running check_scheduled_notifications task")
        now = datetime.now(timezone.utc)
        logger.info(f"Current UTC time: {now}")

        # TEST: Force a notification
        test_user = User.query.first()
        if test_user:
            logger.info(f"Test user found: {test_user.username}, FCM: {test_user.fcm_token}")
            sent = send_and_log_notification(
                test_user.id,
                "Test Notification",
                "This is a test from Celery!",
                "test"
            )
            logger.info(f"Test notification sent: {sent}")
        else:
            logger.warning("No users in DB!")

        # === 1️⃣ Shared Secrets Reminders ===
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

            if timedelta(days=29) <= delta <= timedelta(days=31):
                _notify_secret(secret, "month")
            elif timedelta(days=1) <= delta <= timedelta(days=2):
                _notify_secret(secret, "5_days")
            elif timedelta(minutes=59) <= delta <= timedelta(minutes=61):
                _notify_secret(secret, "hour")

        # === 2️⃣ Subscription Renewal Reminders ===
        users = User.query.filter(
            User.username != "admin",
            User.next_billing_date.isnot(None)
        ).all()

        for user in users:
            delta = user.next_billing_date - now
            if timedelta(days=4) <= delta <= timedelta(days=5):
                _notify_subscription(user, "5_days")
            elif timedelta(days=0) <= delta <= timedelta(days=1):
                _notify_subscription(user, "1_day")

        # === 3️⃣ Trial End Reminders ===
        for user in users:
            if not user.trial_end_date:
                continue
            delta = user.trial_end_date - now
            if timedelta(days=4) <= delta <= timedelta(days=5):
                _notify_end_trial(user, "5_days")
            elif timedelta(days=0) <= delta <= timedelta(days=1):
                _notify_end_trial(user, "1_day")

        # === 4️⃣ Inactivity Reminder ===
        thirty_days_ago = now - timedelta(days=30)
        inactive_users = (
            db.session.query(User)
            .join(LoginHistory, User.id == LoginHistory.user_id)
            .group_by(User.id)
            .having(func.max(LoginHistory.login_time) < thirty_days_ago)
            .all()
        )

        for user in inactive_users:
            send_and_log_notification(
                user.id,
                "We miss you!",
                "You haven’t logged in for a month. Come back and check your secrets!",
                "inactive_user"
            )

            shared_secret = SharedSecret.query.filter(
                SharedSecret.user_id == user.id,
                SharedSecret.received == False,
                SharedSecret.time_period.isnot(None),
                (SharedSecret.date_to_send.is_(None)) & (SharedSecret.time_to_send.is_(None))
            ).first()

            if shared_secret:
                send_and_log_notification(
                    user.id,
                    "Last Login Secret Warning",
                    "You have an active 'Last Login' shared secret. Avoid opening the app unless you intend to reset its timer.",
                    "last_login_warning"
                )



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



from celery import Celery
from celery.schedules import crontab
from flask import url_for, current_app
from celery import shared_task
from .models import SharedSecret
from . import db
from datetime import datetime
import logging
import os



logging.basicConfig(level=logging.INFO)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# celery = Celery(__name__, broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
celery = Celery(__name__, broker='redis://localhost:6379/0')


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
        
        'initiate-recurring-payment-daily': {
            'task': 'app.celery_worker.initiate_recurring_payment_task',
            'schedule': crontab(hour=0, minute=0),    #crontab(minute=0, hour='*/6') this means every 6 hours
        },
        'trial-end-reminder-daily': {
            'task': 'app.celery_worker.trial_end_reminder_task',
            'schedule': crontab(hour=0, minute=0), #hour=6, minute=0 / only minute='*'
        },
        'not-paid-reminder-daily': {
            'task': 'app.celery_worker.not_paied_reminder_task',
            'schedule': crontab(hour=0, minute=0),
        },
        'check-scheduled-secrets-every-minute': {
            'task': 'app.celery_worker.check_scheduled_secrets',
            'schedule': crontab(minute='*'),  # This runs every minute
        }
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
    logger.info(f"Sending email to: {clean_email}, Secret URL: {secret_url}")

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
def initiate_recurring_payment_task():
    logger.info("Initiating recurring payment task...")
    from .utils import initiate_recurring_payment
    initiate_recurring_payment()

@celery.task
def trial_end_reminder_task():
    logger.info("Running trial end reminder task...")
    from .utils import trial_end_reminder
    trial_end_reminder()

@celery.task
def not_paied_reminder_task():
    logger.info("Running not paid reminder task...")
    from .utils import not_paied_reminder
    not_paied_reminder()

# @celery.task
# def test_task():
#     logger.info("Test task executed.")



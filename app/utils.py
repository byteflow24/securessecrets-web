from io import BytesIO
from flask import abort, request, url_for, session, send_file, flash, redirect, jsonify, send_from_directory, current_app
from flask_login import current_user
from functools import wraps
from urllib.parse import urlparse, urljoin
from . import db, login_manager
from .models import User, Secret, Plan, Payment, PendingSubscription
from sqlalchemy import and_
from datetime import datetime, timezone, timedelta, date
from cryptography.fernet import Fernet
from wtforms.validators import DataRequired, Email, Regexp, ValidationError
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formataddr
from email.header import Header
from google.cloud import recaptchaenterprise_v1, storage
from google.oauth2 import service_account
from google.cloud.recaptchaenterprise_v1 import Assessment
from itsdangerous import URLSafeTimedSerializer
import logging, uuid, json, pytz, jwt, base64, requests, secrets, re, os, smtplib, time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)

def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.id != 1:
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

def current_user_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = kwargs.get('user_id')
        if current_user.id != user_id:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# register required comes from pricing server
def require_pricing_session():
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            # Check if the user has been to the pricing page
            if not session.get('from_pricing'):
                flash("You must select a plan first!", "warning")
                return redirect(url_for('main.pricing'))  # Redirect to pricing page
            return func(*args, **kwargs)
        return decorated_function
    return decorator

# Decorator to restrict access to dashboard and payment pages if the user's subscription or trial has ended
def subscription_ended(api=False):
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            current_date = datetime.now(timezone.utc).date()

            # Check if user is authenticated
            if not current_user.is_authenticated:
                if api:
                    return jsonify({"success": False, "error": "Unauthorized"}), 401
                return redirect(url_for('main.login'))

            # Admin bypasses subscription check
            if current_user.username == 'admin':
                return func(*args, **kwargs)

            trial_valid = current_user.trial_end_date and current_user.trial_end_date.date() >= current_date
            subscription_valid = (
                current_user.subscription_status == "ACTIVE" and
                current_user.next_billing_date and
                current_user.next_billing_date.date() >= current_date
            )

            if trial_valid or subscription_valid:
                return func(*args, **kwargs)

            # Subscription/trial ended
            if api:
                return jsonify({
                    "success": False,
                    "error": "Subscription or trial has ended. Please renew to access your account."
                }), 403

            # For web views, redirect to dashboard unless it's already dashboard or payment
            if func.__name__ not in ('dashboard', 'payment'):
                return redirect(url_for('main.dashboard'))

            return func(*args, **kwargs)
        return decorated_function
    return decorator


# Mention this step at all_secrets server
def decrypt_secrets(user_secrets):
    """Decrypt secrets for a given list of secrets."""
    decrypted_secrets = []
    for secret in user_secrets:
        if not is_encrypted(secret.secret):
            secret.secret = encrypt_secret(secret.secret)
        secret.secret = decrypt_secret(secret.secret)
        decrypted_secrets.append(secret)
    return decrypted_secrets

def get_unique_title(title, user_id):
    # Check if a secret with the exact title already exists
    existing_secret = db.session.execute(db.select(Secret).filter_by(title=title, user_id=user_id)).first()

    if existing_secret:
        # Get all titles that match the pattern "title" with optional numeric suffix
        existing_titles = db.session.execute(db.select(Secret.title).filter(Secret.title.like(f"{title}%"), Secret.user_id == user_id)).scalars().all()

        # Extract numeric suffixes from titles that have them
        suffixes = [int(re.search(r'(\d+)$', s).group(1)) for s in existing_titles if re.search(r'(\d+)$', s)]

        # Determine the next numeric suffix to use
        new_suffix = max(suffixes, default=0) + 1
        title = f"{title}_{new_suffix}"

    return title

# To go throw url 
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

# Loading the encryption Key
key = os.environ.get('KEY')
if not key:
    raise ValueError("No KEY found in environment variables")
cipher_suite = Fernet(key)


# Encryption Function
def encrypt_secret(secret):
    encoded_secret = secret.encode()
    encrypted_secret = cipher_suite.encrypt(encoded_secret)
    return encrypted_secret.decode('utf-8')

# Decryption Function
def decrypt_secret(encrypted_secret):
    encrypted_bytes = encrypted_secret.encode()
    decrypted_secret = cipher_suite.decrypt(encrypted_bytes)
    return decrypted_secret.decode('utf-8')

# Checks if a string is encrypted by attempting decryption
def is_encrypted(data):
    try:
        # Attempt decryption
        cipher_suite.decrypt(data.encode())
        return True
    except Exception:
        return False


# Comprehensive list of common email domains and TLDs
def email_domain_validator(form, field):
    """
    Validates email addresses to ensure they are from allowed domains and have allowed TLDs.
    """
    # Regex for extracting email domain
    domain_pattern = r'^[a-zA-Z0-9_.+-]+@([a-zA-Z0-9-]+)\.([a-zA-Z0-9-.]+)$'
    
    # Split the input into individual emails
    emails = [email.strip().lower() for email in field.data.split(',') if email.strip()]

    # Check the number of emails
    if not (1 <= len(emails) <= 5):
        raise ValidationError("You must provide between 1 and 5 email addresses.")
    
    # Validate each email individually
    for email in emails:
        match = re.match(domain_pattern, email)
        if not match:
            raise ValidationError(f"'{email}' is not a valid email address.")
        

# ensure the field accepts only numbers between 1 and 360
def validate_period(form, field):
    if not field.data.isdigit():
        raise ValidationError("The period must contain only numbers.")
    value = int(field.data)
    if value < 1 or value > 360:
        raise ValidationError("Period must be number/s from 1 to 360 dayes.")

# Ensure the date is today or in future
def is_future_date_or_today(form, field):
    """Validator to check if the selected date is today or in the future."""
    if field.data:
        selected_date = field.data
        today_date = datetime.today().date()
        if selected_date < today_date:
            raise ValidationError("The selected date cannot be in the past.")

# Ensure the time is today and in future
def is_future_time_today(form, field):
    """Validator to check if the selected time is today but in the past."""
    if field.data:
        selected_time = field.data.time()  # Extract time (without date)
        current_time = datetime.now().time().replace(second=0, microsecond=0)  # Get current time
        
        # Get the selected date from the form
        selected_date_field = form.date.data  # Access the DateField from the form

        if selected_date_field:
            selected_date = selected_date_field  # Use the selected date
        else:
            selected_date = date.today()  # Default to today if no date is selected

        # Combine selected date and time
        selected_datetime = datetime.combine(selected_date, selected_time)

        # Get current full datetime
        current_datetime = datetime.now()

        # Validation: If the date is today, ensure the selected time is in the future
        if selected_date == current_datetime.date() and selected_time < current_time:
            raise ValidationError("The selected time cannot be in the past.")

# Converting time to user time
def convert_utc_to_local(utc_time, time_zone):
    if not time_zone:
        time_zone = "UTC"

    try:
        local_tz = pytz.timezone(time_zone)
    except pytz.UnknownTimeZoneError:
        print("Invalid timezone! Falling back to UTC.")
        local_tz = pytz.utc

    if isinstance(utc_time, str):
        # Check if the time is in ISO 8601 format (with 'Z')
        if utc_time.endswith('Z'):
            try:
                # Handle ISO 8601 format (2025-02-13T10:00:00Z)
                utc_time = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                print("Unexpected datetime format:", utc_time)
                return "Invalid Format"
        else:
            try:
                # Handle normal format (2025-02-13 10:00:00)
                utc_time = datetime.strptime(utc_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                print("Unexpected datetime format:", utc_time)
                return "Invalid Format"

    # **Force UTC Time to be correct**
    utc_time = utc_time.replace(tzinfo=pytz.utc)
    local_time = utc_time.astimezone(local_tz)

    return local_time.strftime("%Y-%m-%d %H:%M:%S")


def serve_file(abs_path, filename):
    # Serve PDF or Office inline, otherwise as attachment
    ext = os.path.splitext(filename)[1].lower()

    mime_types = {
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.ms-excel',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }

    return send_from_directory(
        os.path.dirname(abs_path),
        os.path.basename(abs_path),
        as_attachment=ext not in mime_types,
        mimetype=mime_types.get(ext, None)
    )

############################ Storing Users Files ############################
# Set Google credentials (Render: store JSON as env var or mount it as secret file)
# Load credentials
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
GCS_BUCKET = os.environ.get("GCS_BUCKET")

if not SERVICE_ACCOUNT_FILE or not GCS_BUCKET:
    raise ValueError("Missing GOOGLE_APPLICATION_CREDENTIALS or GCS_BUCKET env vars")

credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
storage_client = storage.Client(credentials=credentials)

def upload_to_gcs(file, filename):
    """
    Encrypts the file bytes and uploads them to GCS.
    Returns the blob name (do NOT use public URL directly!)
    """
    from io import BytesIO

    # Read raw bytes
    file_bytes = file.read()
    
    # Encrypt bytes
    encrypted_bytes = cipher_suite.encrypt(file_bytes)
    
    # Upload encrypted bytes to GCS
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    blob.upload_from_file(BytesIO(encrypted_bytes), content_type="application/octet-stream")

    print("Using client:", storage_client._credentials.service_account_email)
    return blob.name  # return filename, NOT public URL

def get_signed_url(filename, expires=300):
    """Return a signed URL valid for `expires` seconds"""
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    url = blob.generate_signed_url(expiration=timedelta(seconds=expires))
    print(f"[Signed URL] filename={filename}, url={url}")
    return url

def gcs_file_exists(filename):
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)
    return blob.exists()

def delete_from_gcs(bucket_name, blob_name):
    """Deletes a blob (file) from the GCS bucket."""
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Get file size from metadata
        blob.reload()  # fetch latest metadata
        file_size = blob.size or 0  

        # Delete file
        blob.delete()
        print(f"Deleted {blob_name} from GCS (size: {file_size} bytes)")
        return True, file_size
    except Exception as e:
        print(f"Error deleting {blob_name} from GCS: {e}")
        return False, 0

def _serve_file(filename):
    """Helper to fetch, decrypt, and stream file from GCS."""
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.blob(filename)

    if not blob.exists():
        return abort(404, description="File not found.")

    encrypted_bytes = blob.download_as_bytes()
    decrypted_bytes = cipher_suite.decrypt(encrypted_bytes)

    # Detect MIME
    ext = filename.split('.')[-1].lower()
    mimetypes = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp',
        'mp4': 'video/mp4', 'mov': 'video/quicktime',
        'pdf': 'application/pdf', 'mp3': 'audio/mpeg'
    }
    mime_type = mimetypes.get(ext, 'application/octet-stream')

    return send_file(
        BytesIO(decrypted_bytes),
        download_name=filename,
        mimetype=mime_type
    )


# def as_dict(self):
#     return {
#         "id": self.id,
#         "title": self.title,
#         "snapshot_secret": self.snapshot_secret,
#         "file": self.file,
#         "share_date": self.share_date.isoformat() if self.share_date else None,
#         "public": self.public,
        
#     }


# Configures PayPal Payment Gateway
####################### LIVE ACTION #######################
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_LIVE_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_LIVE_CLIENT_SECRET")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_LIVE_WEBHOOK_ID")
API_URL = "https://api-m.paypal.com/v1"
####################### RECAPTCHA GOOGLE #######################
SITE_KEY = os.environ.get("SITE_KEY")
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
####################### SENDBOX ACTION #######################
# PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_SENDBOX_CLIENT_ID")
# PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_SENDBOX_CLIENT_SECRET")
# PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID") # Webhook ID
# API_URL = "https://api-m.sandbox.paypal.com/v1"
# Generating request id
request_id = uuid.uuid4()

def is_suspicious_input(text: str) -> bool:
    """
    Check if input contains HTML or suspicious patterns indicative of bot activity.
    """
    if not text:
        return False
    # Check for HTML tags or common bot patterns
    html_pattern = re.compile(r'<[^>]+>')
    suspicious_patterns = [
        r'<!DOCTYPE', r'<html', r'<script', r'<iframe', r'http://', r'https://',
        r'Wildberries', r'free attempts', r'win up to'
    ]
    if html_pattern.search(text):
        logger.warning(f"Suspicious HTML detected in input: {text[:100]}...")
        return True
    for pattern in suspicious_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Suspicious pattern detected in input: {text[:100]}...")
            return True
    return False

# Verify reCAPTCHA token
def create_assessment(
    recaptcha_token: str,
    recaptcha_action: str = 'contact_form',
    flask_request=None,
    ja3: str = None
) -> tuple[bool, str | None]:
    """
    Create an assessment to analyze the risk of a UI action.
    
    Args:
        recaptcha_token (str): The reCAPTCHA token from the client.
        recaptcha_action (str): Action name used in the reCAPTCHA button (e.g., 'contact_form').
        flask_request: Flask request object to extract user_ip_address and user_agent (optional).
        ja3 (str, optional): JA3 fingerprint of the client’s TLS configuration.
        
    Returns:
        tuple: (bool, str or None)
            - bool: True if verification succeeds and score >= 0.5, False otherwise.
            - str or None: Error message if verification fails, None if successful.
    """
    if not PROJECT_ID:
        logger.error("GOOGLE_CLOUD_PROJECT_ID is not set in environment variables")
        return False, "reCAPTCHA configuration error: Project ID missing"

    if not SITE_KEY:
        logger.error("SITE_KEY is not set in environment variables")
        return False, "reCAPTCHA configuration error: Site key missing"

    if not recaptcha_token:
        logger.error("No reCAPTCHA token provided")
        return False, "reCAPTCHA token missing"

    try:
        client = recaptchaenterprise_v1.RecaptchaEnterpriseServiceClient()

        # Set the properties of the event to be tracked
        event = recaptchaenterprise_v1.Event()
        event.site_key = SITE_KEY
        event.token = recaptcha_token
        event.expected_action = recaptcha_action
        if flask_request:
            event.user_ip_address = flask_request.remote_addr
            event.user_agent = flask_request.headers.get('User-Agent')
            # If behind a proxy, try X-Forwarded-For header
            if not event.user_ip_address:
                event.user_ip_address = flask_request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if ja3:
            event.ja3 = ja3

        assessment = recaptchaenterprise_v1.Assessment()
        assessment.event = event

        project_name = f"projects/{PROJECT_ID}"

        # Build the assessment request
        request = recaptchaenterprise_v1.CreateAssessmentRequest()
        request.assessment = assessment
        request.parent = project_name

        response = client.create_assessment(request)

        # Log assessment details
        logger.info(f"reCAPTCHA Enterprise assessment: score={response.risk_analysis.score}, "
                   f"reasons={response.risk_analysis.reasons}, "
                   f"action={response.token_properties.action}, "
                   f"valid={response.token_properties.valid}")

        # Check if the token is valid
        if not response.token_properties.valid:
            error_msg = f"Invalid reCAPTCHA token: {response.token_properties.invalid_reason}"
            logger.error(error_msg)
            return False, error_msg

        # Check if the expected action was executed
        if response.token_properties.action != recaptcha_action:
            error_msg = f"reCAPTCHA action mismatch: expected {recaptcha_action}, got {response.token_properties.action}"
            logger.error(error_msg)
            return False, error_msg

        # Check the risk score
        if response.risk_analysis.score >= 0.5:
            assessment_name = client.parse_assessment_path(response.name).get("assessment")
            logger.info(f"Assessment name: {assessment_name}")
            return True, None
        else:
            error_msg = f"reCAPTCHA score too low: {response.risk_analysis.score}"
            logger.error(error_msg)
            return False, error_msg

    except Exception as e:
        error_msg = f"Error creating reCAPTCHA assessment: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    
# Create Product API
def create_product():

    access_token = get_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'PayPal-Request-Id': f"PRODUCT-{request_id}",
        'Prefer': 'return=representation',
    }
    data = '{ "name": "Secures Secrets Service", "description": "A secure platform for sharing and managing confidential information", "type": "SERVICE", "category": "SOFTWARE"}'
    url = f'{API_URL}/catalogs/products'

    response = requests.post(url, headers=headers, data=data)

    # Check if request was successful
    if response.status_code == 200:
        plan = Plan.query.filter_by(product_id="None").first()
        plan.product_id = response.json()["id"]
        db.session.commit()
        print("Successed fetching product details")
    else:
        print(f"Failed to fetch product id: {response.status_code}")
        print(response.json())
        return None

# Get the access token
def get_access_token():

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en_US",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "client_credentials"
    }
    url = f"{API_URL}/oauth2/token"

    response = requests.post(url, headers=headers, data=data, auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET))

    # Check if request was successful
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"Failed to fetch access token: {response.status_code}")
        print(response.json())
        return None
    
def create_plan():
    access_token = get_access_token()
    plan = Plan.query.filter_by(plan="Basic").first()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'PayPal-Request-Id': f'PLAN-{request_id}',
        'Prefer': 'return=representation',
    }

    ############################################ Basic Plan (Trial + Regular Billing Cycle) ############################################
    basic_plan_data = {
        "product_id": plan.product_id,
        "name": "Basic",
        "description": "Access to basic features with a 14-day trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 14
                },
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {
                    "fixed_price": {
                    "value": "0",
                    "currency_code": "USD"
                    }
                }
            },
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,  # 0 means the subscription is indefinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "0.99",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }
    
    ############################################ Basic Plan (Trial + Regular Billing Cycle + Annual) ############################################

    annual_basic_plan_data = {
        "product_id": plan.product_id,
        "name": "Basic",
        "description": "Access to basic features with a 14-day trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 14
                },
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {
                    "fixed_price": {
                    "value": "0",
                    "currency_code": "USD"
                    }
                }
            },
            {
                "frequency": {
                    "interval_unit": "YEAR",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,  # 0 means the subscription is indefinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "10.69",  # Yearly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }

    ############################################ Basic Plan ( No Trial + Regular Billing Cycle + Annual) ############################################

    Annual_basic_non_trial_plan_data = {
        "product_id": plan.product_id,
        "name": "Annual Basic Plan (No Trial)",
        "description": "Access to basic features without trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "YEAR",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # No trial, regular billing
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "10.99",  # Yearly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }

    ############################################ Premium Plan (Trial + Regular Billing Cycle) ############################################
    premium_plan_data = {
        "product_id": plan.product_id,  # Replace with your actual product ID
        "name": "Premium",
        "description": "Access to premium features with a 14-day trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 14
                },
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {
                    "fixed_price": {
                    "value": "0",
                    "currency_code": "USD"
                    }
                }
            },
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,  # 0 means the subscription is indefinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "1.99",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
    }

    ############################################ Premium Plan (Trial + Regular Billing Cycle + Annual) ############################################

    annual_premium_plan_data = {
        "product_id": plan.product_id,  # Replace with your actual product ID
        "name": "Annual Premium Plan",
        "description": "Access to premium features with a 14-day trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 14
                },
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {
                    "fixed_price": {
                    "value": "0",
                    "currency_code": "USD"
                    }
                }
            },
            {
                "frequency": {
                    "interval_unit": "YEAR",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,  # 0 means the subscription is indefinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "21.49",  # Yearly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
    }

    ############################################ Non-Trial Basic Plan ############################################
    basic_non_trial_plan_data = {
        "product_id": plan.product_id,
        "name": "Basic (No Trial)",
        "description": "Access to basic features without trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # No trial, regular billing
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "0.99",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }

    ############################################ Non-Trial Premium Plan ############################################
    premium_non_trial_plan_data = {
        "product_id": plan.product_id,  # Replace with your actual product ID
        "name": "Premium (No Trial)",
        "description": "Access to premium features without trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # No trial, regular billing
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "1.99",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
    }

    Annual_premium_non_trial_plan_data = {
        "product_id": plan.product_id,
        "name": "Annual Premium plan (No Trial)",
        "description": "Access to premium features without trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "YEAR",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # No trial, regular billing
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "21.99",  # Yearly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
    }

    test_plan = {
        "product_id": plan.product_id,  # Replace with your actual product ID
        "name": "Test Trial Plan",
        "description": "Access to test features with a 1-day trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 1
                },
                "tenure_type": "TRIAL",
                "sequence": 1,
                "total_cycles": 1,
                "pricing_scheme": {
                    "fixed_price": {
                    "value": "0",
                    "currency_code": "USD"
                    }
                }
            },
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 3
                },
                "tenure_type": "REGULAR",
                "sequence": 2,
                "total_cycles": 0,  # 0 means the subscription is indefinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "2.0",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
    }
    
    test_non_trial_plan = {
        "product_id": plan.product_id,
        "name": "Test (No Trial)",
        "description": "Access to test features without trial",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "DAY",
                    "interval_count": 3
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # No trial, regular billing
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "2.0",  # Monthly price
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        }
    }
    

    ############################################ Serialize data to JSON strings ############################################
    # basic_plan_json = json.dumps(basic_plan_data)
    # premium_plan_json = json.dumps(premium_plan_data)
    # basic_non_trial_plan_json = json.dumps(basic_non_trial_plan_data)
    # premium_non_trial_plan_json = json.dumps(premium_non_trial_plan_data)
    # test_plan_json_trial = json.dumps(test_plan)
    # test_plan_json = json.dumps(test_non_trial_plan)
    # annual_basic_plan_json = json.dumps(annual_basic_plan_data)
    # annual_premium_plan_json = json.dumps(annual_premium_plan_data)
    # Annual_basic_non_trial_plan_json = json.dumps(Annual_basic_non_trial_plan_data)
    # Annual_premium_non_trial_plan_json = json.dumps(Annual_premium_non_trial_plan_data)

    url = f"{API_URL}/billing/plans"

    ############################################ Create the Basic and Premium Plans ############################################
    # response_basic = requests.post(url, headers=headers, data=basic_plan_json)
    # response_premium = requests.post(url, headers=headers, data=premium_plan_json)
    # response_basic_non_trial = requests.post(url, headers=headers, data=basic_non_trial_plan_json)
    # response_premium_non_trial = requests.post(url, headers=headers, data=premium_non_trial_plan_json)
    # response_test_plan = requests.post(url, headers=headers, data=test_plan_json)
    # response_test_trial_plan = requests.post(url, headers=headers, data=test_plan_json)
    # response_annual_basic_plan = requests.post(url, headers=headers, data=annual_basic_plan_json)
    # response_annual_premium_plan = requests.post(url, headers=headers, data=annual_premium_plan_json)
    # Annual_basic_non_trial_plan = requests.post(url, headers=headers, data=Annual_basic_non_trial_plan_json)
    # Annual_premium_non_trial_plan = requests.post(url, headers=headers, data=Annual_premium_non_trial_plan_json)

    ###################################################################

    # if Annual_premium_non_trial_plan.status_code == 201:
    #     # Fetch the Basic-Yearly plan
    #     annual_plan_data = Plan.query.filter(
    #         and_(Plan.plan == "Premium", Plan.billing_cycle == "yearly")
    #     ).first()

    #     if not annual_plan_data:
    #         print("Annual Premium plan not found in the database.")
    #         return
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(annual_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(annual_plan_data.paypal_plan_id)
    #     elif isinstance(annual_plan_data.paypal_plan_id, list) or annual_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = annual_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(Annual_premium_non_trial_plan.json()['id'])

    #     # Store back as JSON string
    #     annual_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Annual Premium Plan Created Successfully!")
    #     print(Annual_premium_non_trial_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Annual Premium Plan.")
    #     print(Annual_premium_non_trial_plan.json())

    ###################################################################

    # if Annual_basic_non_trial_plan.status_code == 201:
    #     # Fetch the Basic-Yearly plan
    #     annual_plan_data = Plan.query.filter(
    #         and_(Plan.plan == "Basic", Plan.billing_cycle == "yearly")
    #     ).first()

    #     if not annual_plan_data:
    #         print("Annual Basic plan not found in the database.")
    #         return
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(annual_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(annual_plan_data.paypal_plan_id)
    #     elif isinstance(annual_plan_data.paypal_plan_id, list) or annual_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = annual_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(Annual_basic_non_trial_plan.json()['id'])

    #     # Store back as JSON string
    #     annual_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Annual Basic Plan Created Successfully!")
    #     print(Annual_basic_non_trial_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Annual Basic Plan.")
    #     print(Annual_basic_non_trial_plan.json())

    ###################################################################

    # if response_annual_premium_plan.status_code == 201:
    #     # Fetch the Basic-Yearly plan
    #     annual_plan_data = Plan.query.filter(
    #         and_(Plan.plan == "Premium", Plan.billing_cycle == "yearly")
    #     ).first()

    #     if not annual_plan_data:
    #         print("Annual Premium plan not found in the database.")
    #         return
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(annual_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(annual_plan_data.paypal_plan_id)
    #     elif isinstance(annual_plan_data.paypal_plan_id, list) or annual_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = annual_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_annual_premium_plan.json()['id'])

    #     # Store back as JSON string
    #     annual_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Annual Premium Plan Created Successfully!")
    #     print(response_annual_premium_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Annual Premium Plan.")
    #     print(response_annual_premium_plan.json())

    ###################################################################

    # if response_basic.status_code == 201:
    #     basic_plan = Plan.query.filter_by(plan="Basic").first()
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(basic_plan.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(basic_plan.paypal_plan_id)
    #     elif isinstance(basic_plan.paypal_plan_id, list) or basic_plan.paypal_plan_id is None:
    #         existing_plan_ids = basic_plan.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_basic.json()['id'])

    #     # Store back as JSON string
    #     basic_plan.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Basic Plan Created Successfully!")
    #     print(response_basic.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Basic Plan.")
    #     print(response_basic.json())

    ##############################################################################

    # if response_basic_non_trial.status_code == 201:
    #     basic_plan = Plan.query.filter_by(plan="Basic").first()
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(basic_plan.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(basic_plan.paypal_plan_id)
    #     elif isinstance(basic_plan.paypal_plan_id, list) or basic_plan.paypal_plan_id is None:
    #         existing_plan_ids = basic_plan.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_basic_non_trial.json()['id'])

    #     # Store back as JSON string
    #     basic_plan.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Basic None Trial Plan Created Successfully!")
    #     print(response_basic_non_trial.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Basic None Trial Plan.")
    #     print(response_basic_non_trial.json())

    ##############################################################################

    # if response_premium.status_code == 201:
    #     premium_plan = Plan.query.filter_by(plan="Premium").first()
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(premium_plan.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(premium_plan.paypal_plan_id)
    #     elif isinstance(premium_plan.paypal_plan_id, list) or premium_plan.paypal_plan_id is None:
    #         existing_plan_ids = premium_plan.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_premium.json()['id'])

    #     # Store back as JSON string
    #     premium_plan.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Premium Plan Created Successfully!")
    #     print(response_premium.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Premium Plan.")
    #     print(response_premium.json())

    ##############################################################################

    # if response_premium_non_trial.status_code == 201:
    #     # Fetch the existing plan
    #     premium_plan = Plan.query.filter_by(plan="Premium").first()
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(premium_plan.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(premium_plan.paypal_plan_id)
    #     elif isinstance(premium_plan.paypal_plan_id, list) or premium_plan.paypal_plan_id is None:
    #         existing_plan_ids = premium_plan.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_premium_non_trial.json()['id'])

    #     # Store back as JSON string
    #     premium_plan.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Non-Trial Premium Plan Created Successfully!")
    #     print(response_premium_non_trial.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Non-Trial Premium Plan.")
    #     print(response_premium_non_trial.json())

    ##############################################################################

    # if response_test_trial_plan.status_code == 201:
    #     # Fetch the existing plan
    #     test_plan_data = Plan.query.filter_by(plan="Test").first()
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(test_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(test_plan_data.paypal_plan_id)
    #     elif isinstance(test_plan_data.paypal_plan_id, list) or test_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = test_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_test_trial_plan.json()['id'])

    #     # Store back as JSON string
    #     test_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Test Plan Created Successfully!")
    #     print(response_test_trial_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Test Plan.")
    #     print(response_test_trial_plan.json())

    ##############################################################################

    # if response_test_plan.status_code == 201:
    #     # Fetch the existing plan
    #     test_plan_data = Plan.query.filter_by(plan="Test").first()
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(test_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(test_plan_data.paypal_plan_id)
    #     elif isinstance(test_plan_data.paypal_plan_id, list) or test_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = test_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_test_plan.json()['id'])

    #     # Store back as JSON string
    #     test_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Test Plan Created Successfully!")
    #     print(response_test_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Test Plan.")
    #     print(response_test_plan.json())

    ##############################################################################

    # if response_annual_basic_plan.status_code == 201:
    #     # Fetch the Basic-Yearly plan
    #     annual_plan_data = Plan.query.filter(
    #         and_(Plan.plan == "Basic", Plan.billing_cycle == "yearly")
    #     ).first()

    #     if not annual_plan_data:
    #         print("Annual Basic plan not found in the database.")
    #         return
        
    #     # Check if paypal_plan_id is already a list or a JSON string
    #     if isinstance(annual_plan_data.paypal_plan_id, str):
    #         existing_plan_ids = json.loads(annual_plan_data.paypal_plan_id)
    #     elif isinstance(annual_plan_data.paypal_plan_id, list) or annual_plan_data.paypal_plan_id is None:
    #         existing_plan_ids = annual_plan_data.paypal_plan_id or []
    #     else:
    #         raise TypeError("Unexpected type for paypal_plan_id")

    #     # Append the new PayPal Plan ID
    #     existing_plan_ids.append(response_annual_basic_plan.json()['id'])

    #     # Store back as JSON string
    #     annual_plan_data.paypal_plan_id = json.dumps(existing_plan_ids)
    #     db.session.commit()

    #     print("Test Plan Created Successfully!")
    #     print(response_annual_basic_plan.json())  # Contains the plan_id for Basic
    # else:
    #     print("Failed to create Test Plan.")
    #     print(response_annual_basic_plan.json())

# Create new subscription
def create_new_subscription(user, new_plan_id):
    access_token = get_access_token()
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    # Start in 5 minutes (or adjust as needed)
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    start_time = future_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = {
        "plan_id": new_plan_id,
        "subscriber": {
            "email_address": user.email
        },
        "start_time": start_time,
        "quantity": "1",
        "shipping_amount": {
            "currency_code": "USD",
            "value": "0.0"
        },
        "payment_preferences": {
            "service_type": "PREPAID",
            "auto_bill_outstanding": True
        },
        "application_context": {
            "return_url": url_for('main.dashboard', _external=True),
            "cancel_url": url_for('main.billing', _external=True)
        }
    }

    # Only add payer_id if it exists
    if user.paypal_payer_id:
        data["subscriber"]["payer_id"] = user.paypal_payer_id

    url = f"{API_URL}/billing/subscriptions"
    response = requests.post(url, headers=headers, json=data)  # Use `json=data` instead of `data=json.dumps(data)`

    if response.status_code == 201:
        subscription_data = response.json()
        print("New subscription created successfully.")

        # Extract approval link
        approval_url = next(
            (link["href"] for link in subscription_data["links"] if link["rel"] == "approve"),
            None
        )

        if approval_url:
            print(f"User needs to approve the subscription: {approval_url}")
            return {"subscription": subscription_data, "approval_url": approval_url}

        return {"subscription": subscription_data}

    else:
        print("Failed to create new subscription:", response.json())
        return None

# Cancel subscription
def cancel_subscription(subscription_id, reason):
    access_token = get_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    data = json.dumps({"reason": reason})

    # Check if subscription is already canceled before making a request
    subscription_status = get_subscription_details(subscription_id)
    if subscription_status == "CANCELED":
        print(f"Subscription {subscription_id} is already canceled.")
        return True

    url = f'{API_URL}/billing/subscriptions/{subscription_id}/cancel'
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 204:
        print("Subscription canceled successfully!")
        return True
    else:
        print("Failed to cancel subscription:", response.json())
        return False
    
# Change subscription plan
def change_subscription_plan(user_subscription_id, new_plan_id):
    access_token = get_access_token()
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    data = json.dumps({
        "plan_id": new_plan_id,
    })

    url = f'{API_URL}/billing/subscriptions/{user_subscription_id}/revise'
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        print("Subscription updated successfully!")

        # Fetch the updated subscription details
        updated_subscription = get_subscription_details(user_subscription_id)
        return updated_subscription  # Return latest details
    else:
        print("Failed to update subscription:", response.json())
        return None

# Deactivate plan function
def deactivate_plan(plan_id):
    access_token = get_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    data = '{}'

    url = f'{API_URL}/billing/plans/{plan_id}/deactivate'
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 204:
        print("Deactivated plan Successfully!")

    else:
        print("Failed to deactivate plan.")

# List plans
def call_plans():

    access_token = get_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Prefer': 'return=representation',
    }

    params = (
        ('sort_by', 'create_time'),
        ('sort_order', 'desc'),
    )

    url = f'{API_URL}/billing/plans'
    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        print("Successfully retrieved plans.")
        print(response.json())
    else:
        print("Failed to retrieve Plans!")
        print(response.json())

# Get user subscription details
def get_subscription_details(subscription_id):

    access_token = get_access_token()

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    url = f"{API_URL}/billing/subscriptions/{subscription_id}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        print() #f"Failed to get user subscription details: {response.json()}"

# Webhook veryfication
def verify_paypal_webhook(data, request_headers):

    access_token = get_access_token()

    auth_headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    verify_data = {
        "auth_algo": request_headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": request_headers.get("PAYPAL-CERT-URL"),
        "transmission_id": request_headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": request_headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": request_headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": data,
    }

    url = f"{API_URL}/notifications/verify-webhook-signature"
    response = requests.post(url, headers=auth_headers, json=verify_data)

    if response.status_code == 200 and response.json().get("verification_status") == "SUCCESS":
        return True
    return False

# Get user IP
def get_ip():
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.getlist("X-Forwarded-For")[0]
    else:
        ip = request.remote_addr
    return ip

# Get user agent
def get_user_agent():
    return request.user_agent.string

# Triggered when a user makes a successful payment.
def handle_payment_success(data):
    try:
        # Access the necessary data from the webhook payload
        resource = data.get('resource', {})
        subscription_id = resource.get('billing_agreement_id')
        payment_amount = resource.get('amount', {}).get('total', "0.00")
        currency = resource.get('amount', {}).get('currency', "USD")
        transaction_id = resource.get('id')
        status = resource.get('state')
        payment_time = resource.get('create_time', datetime.now(timezone.utc).isoformat())
        subscriber = resource.get("subscriber", {})

        # Log for debugging
        print(f"Subscription ID: {subscription_id}")
        print(f"Payment Amount: {payment_amount} {currency}")
        print(f"Transaction ID: {transaction_id}")

        # Ensure we have a subscription ID to proceed
        if not subscription_id:
            print("Error: No subscription ID found in webhook data.")
            return

        # Find the user associated with this subscription
        user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
        if not user:
            print(f"No user found for subscription ID {subscription_id}")
            return

        # Convert amount to Decimal (good practice for monetary values)
        payment_amount = float(payment_amount)
        payment_time = convert_utc_to_local(payment_time, user.time_zone)

        user_ip = get_ip()
        user_agent = get_user_agent()
        
        # Create a new payment record in the database
        new_payment = Payment(
            user_id=user.id,
            amount=payment_amount,
            currency=currency,
            transaction_id=transaction_id,
            payment_date=payment_time,  # Convert PayPal time format
            plan_id=user.plan_id,
            ip_address=user_ip,
            user_agent=user_agent,
            payment_status = {
                "completed": "Paid",
                "pending": "Pending",
                "failed": "Failed"
            }.get(status.lower(), None) if status else None
        )
        db.session.add(new_payment)

        # Retrieve and update subscription info
        subscription_data = get_subscription_details(subscription_id)
        billing_info = subscription_data.get("billing_info", {})

        next_billing = convert_utc_to_local(billing_info.get("next_billing_time"), user.time_zone)
        if next_billing and user.next_billing_date != next_billing:
            user.next_billing_date = next_billing

        # Fix: Use .get() to safely access subscriber details
        user.paypal_payer_id = subscriber.get("payer_id", user.paypal_payer_id)  # Keep existing payer_id if missing
        user.updated_at = payment_time

        user.subscription_status = "ACTIVE"

        db.session.commit()
        print(f"Payment recorded successfully for User {user.id}, Amount: {payment_amount} {currency}")

    except KeyError as e:
        db.session.rollback()  # Rollback in case of failure
        print(f"Error processing payment data: Missing key {e}")
    except Exception as e:
        db.session.rollback()
        print(f"Unexpected error: {str(e)}")

# Triggered when subscription created
def handle_subscription_created(data):
    subscription_id = data['resource']['id']
    plan_id = data['resource']['plan_id']
    start_time = data['resource']['start_time']
    status = data['resource']['status']

    # ✅ Handle missing subscriber field
    subscriber_email = data['resource'].get('subscriber', {}).get('email_address', 'unknown')

    print(f"Subscription Created: ID: {subscription_id}, Plan ID: {plan_id}, Email: {subscriber_email}, Status: {status}")

    # Get all plans and find the one that matches new_plan_id
    plans = Plan.query.all()
    matching_plan = next((plan for plan in plans if plan_id in plan.paypal_plan_id), None)

    if not matching_plan:
        print(f"No matching plan found for PayPal plan ID {plan_id}")
        return  # Stop execution if no matching plan is found
    

    # Assuming you have the user record, update their subscription info
    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if user.status == "ACTIVE":
        status = "ACTIVE"

    if user:
        user.paypal_subscription_id = subscription_id
        user.plan_id = matching_plan.id
        user.subscription_start_date = start_time
        user.subscription_status = status
        db.session.commit()
        print(f"User {user.id} subscription updated to {status}")

# Triggered when subscription activated.
def handle_subscription_activated(data):
    subscription_id = data['resource']['id']
    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if not user:
        print(f"No user found for subscription ID {subscription_id} >>handel_sub_activated<<")
        return  # Stop execution if no user is found
        
    user.subscription_status = "ACTIVE"
    db.session.commit()
    print(f"User {subscription_id} activated their subscription.")

# Triggered when a payment is declined.
def handle_payment_failed(data):
    subscription_id = data['resource']['billing_agreement_id']
    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if not user:
        print(f"No user found for subscription ID {subscription_id} >>handel_sub_declined<<")
        return

    user.failed_payments += 1  # Track failed attempts
    if user.failed_payments >= 3:
        user.subscription_status = "SUSPENDED"
    
    db.session.commit()
    print(f"Payment failed for User {subscription_id}")

# Triggered when a user cancels their subscription.
def handle_subscription_canceled(data):
    subscription_id = data['resource']['id']
    reason = data['resource']['status_change_note']
    if reason == "Deleting my account.":
        print(f"Subscription cenceled reason: {reason}")

    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if not user:
        print(f"No user found for subscription ID {subscription_id} >>handel_sub_canceled<<")
        return
    user.subscription_status = "CANCELED"
    db.session.commit()
    print(f"User {subscription_id} canceled their subscription.")

# Triggered when a user suspended their subscription.
def handle_subscription_suspended(data):
    subscription_id = data['resource']['id']
    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if not user:
        print(f"No user found for subscription ID {subscription_id} >>handel_sub_suspended<<")
        return
    user.subscription_status = "SUSPENDED"
    db.session.commit()
    print(f"User {subscription_id} suspended their subscription.")

# Triggered when a user upgrades/downgrades their subscription.
def handle_subscription_updated(data):
    subscription_id = data['resource']['id']
    new_plan_id = data['resource'].get('plan_id')  # Ensure the new plan ID exists

    if not new_plan_id:
        print("No new plan ID found in the updated subscription data.")
        return  

    # Find the user associated with the subscription ID
    user = User.query.filter_by(paypal_subscription_id=subscription_id).first()
    if not user:
        print(f"No user found for subscription ID {subscription_id} >>handle_subscription_updated<<")
        return

    # Get all plans and find the one that matches new_plan_id
    plans = Plan.query.all()
    matching_plan = next((plan for plan in plans if new_plan_id in plan.paypal_plan_id), None)

    if not matching_plan:
        print(f"No matching plan found for PayPal plan ID {new_plan_id}")
        return  # Stop execution if no matching plan is found
    
    # Update the user's plan if it's not already updated
    if user.plan_id != matching_plan.id:
        user.plan_id = matching_plan.id

    # Update billing info only if it's not already set
    subscription_data = data['resource']
    next_billing_time = subscription_data.get('billing_info', {}).get('next_billing_time')
    if next_billing_time and user.next_billing_date != next_billing_time:
        user.next_billing_date = next_billing_time

    # Assuming you have a 'subscription_amount' field to track the subscription amount
    # subscription_amount = subscription_data.get('billing_info', {}).get('last_payment', {}).get('amount', {}).get('value')
    # if subscription_amount:
    #     user.subscription_amount = subscription_amount  # Update the subscription amount

    db.session.commit()  # Commit the changes to the database

    print(f"User {user.id} updated their subscription to Plan: {new_plan_id}")
    print(f"Updated subscription details: {get_subscription_details(subscription_id)}")

# Sends reminder emails to users whose trial periods are nearing their end
def trial_end_reminder():
    logger.info("Sending trial end reminder.")
    
    # Get the current date (ignore time)
    current_date = datetime.now(timezone.utc).date()
    
    users = User.query.filter(User.trial_end_date.isnot(None)).all()
    
    for user in users:

        if user.username == 'admin':
            continue  # Skip processing for admin user

        # Ensuring trial_end_date is timezone-aware (assumed UTC)
        trial_end_date = user.trial_end_date
        if trial_end_date.tzinfo is None:
            trial_end_date = trial_end_date.replace(tzinfo=timezone.utc)
        
        # Get only the date part of trial_end_date (ignore time)
        trial_end_date_only = trial_end_date.date()

        # Calculate the difference in days between current_date and trial_end_date_only
        days_difference = (trial_end_date_only - current_date).days

        # Format the trial end date for email
        formatted_trial_end_date = trial_end_date.strftime('%d-%m-%Y')

        # Debug print statement
        print(f"User: {user.username}, Trial End Date: {trial_end_date_only}, Days Difference: {days_difference}")

        # Check if the trial end date is exactly 7 days or 1 day away
        if days_difference == 7:
            email_reminder(user.email, user.username, formatted_trial_end_date, reminder_type="trial_week")
        elif days_difference == 1:
            email_reminder(user.email, user.username, formatted_trial_end_date, reminder_type="trial_day")
        elif days_difference <= 0:
            # When the trial ends, reset the trial_end_date to None
            user.trial_end_date = current_date
            db.session.commit()


# Check if user subscription end date
def not_paied_reminder():
    logger.info("Sending not paid reminder.")
    current_date = datetime.now(timezone.utc).date()
    users = User.query.filter(User.next_billing_date <= current_date).all()

    for user in users:

        if user.username == 'admin':
            continue  # Skip processing for admin user

        plan = Plan.query.filter_by(id=user.plan_id).first()
        if user.next_billing_date:
            if user.next_billing_date.tzinfo is None:
                next_billing_date = user.next_billing_date.replace(tzinfo=timezone.utc)
            else:
                next_billing_date = user.next_billing_date
            
            # Get only the date part of next_billing_date (ignore time)
            next_billing_date = next_billing_date.date()

            # will make the user inactive if the subscription ended
            if next_billing_date > current_date:
                user.subscription_status = "INACTIVE"
                db.session.commit()

            # Calculate the difference in days
            days_left = (next_billing_date - current_date).days

            if days_left in [-5, -3, -7]:
                days_left = abs(days_left)

            logger.info(days_left)

            if days_left in [5, 3, 1]:  # Send reminders at 5, 3, and 1 day left
                reminder_to_pay_email(user.username, user.email, plan.plan, days_left)
                
                # If it's the last reminder (1 day), delete the user
                if days_left == 1:
                    db.session.delete(user)
                    db.session.commit()


# Generating a token
def generate_token():
    return secrets.token_urlsafe(32)


# Generate access token
def generate_access_token(user_id, secret_key, expires_in=3600):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(seconds=expires_in),
        'iat': datetime.utcnow()
    }
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token

# ======  CONFIGURATION  ====== APPLE API ======
APPLE_ISSUER_ID = os.environ.get("APPLE_ISSUER_ID")
APPLE_KEY_ID = os.environ.get("APPLE_KEY_ID")
APPLE_PRIVATE_KEY_PATH = os.environ.get("APPLE_PRIVATE_KEY_PATH")
APPLE_API_BASE = "https://api.storekit.itunes.apple.com"  # For production
APPLE_SANDBOX_BASE = "https://api.storekit-sandbox.itunes.apple.com"# For sandbox

# ======  HELPER: GENERATE APPLE JWT  ======
def generate_apple_jwt():
    try:
        with open(APPLE_PRIVATE_KEY_PATH, "r") as f:
            private_key = f.read()
    except Exception as e:
        print(f"Error reading private key: {e}")
        raise

    now = int(time.time())
    claims = {
        "iss": APPLE_ISSUER_ID,
        "iat": now,
        "exp": now + 1800,
        "aud": "appstoreconnect-v1",
        "bid": "com.byteflowdigital.securessecrets",
    }

    try:
        token = jwt.encode(
            claims,
            private_key,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": APPLE_KEY_ID, "typ": "JWT"}
        )
        return token
    except Exception as e:
        print(f"Error generating JWT: {e}")
        raise

def verify_transaction(transaction_id, token, use_sandbox=True):  # Default to sandbox
    base_url = APPLE_SANDBOX_BASE if use_sandbox else APPLE_API_BASE
    url = f"{base_url}/inApps/v1/transactions/{transaction_id}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        return {"error": "Request failed", "details": str(e)}, 500, str(e)

    try:
        apple_data = resp.json()
    except ValueError as e:
        apple_data = {"error": "Invalid JSON", "details": str(e), "raw": resp.text}

    # Retry with sandbox if 404 in production
    if resp.status_code == 404 and not use_sandbox:
        return verify_transaction(transaction_id, token, use_sandbox=True)

    # Handle 401 specifically
    if resp.status_code == 401:
        return apple_data, resp.status_code, "Authentication error"

    return apple_data, resp.status_code, None


def parse_apple_transaction(apple_data):
    """
    Decodes signedTransactionInfo and returns parsed dict.
    """
    signed_tx = apple_data.get("signedTransactionInfo")
    if not signed_tx:
        return None

    try:
        parsed_tx = jwt.decode(signed_tx, options={"verify_signature": False})
        # Convert expiresDate from ms to datetime
        if "expiresDate" in parsed_tx:
            parsed_tx["expiresDate"] = datetime.fromtimestamp(
                int(parsed_tx["expiresDate"]) / 1000, tz=timezone.utc
            )
        if "purchaseDate" in parsed_tx:
            parsed_tx["purchaseDate"] = datetime.fromtimestamp(
                int(parsed_tx["purchaseDate"]) / 1000, tz=timezone.utc
            )
        return parsed_tx
    except Exception as e:
        print("Error decoding signedTransactionInfo:", e)
        return None

def decode_apple_signed_payload(signed_payload):
    # JWS format: header.payload.signature
    parts = signed_payload.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid JWS structure")

    # The payload is the 2nd part (base64url encoded)
    payload_b64 = parts[1]
    # Pad base64 string if necessary
    payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
    payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
    return json.loads(payload_json)

def decode_jwt(jwt_token):
    parts = jwt_token.split('.')
    payload_b64 = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
    return json.loads(payload_json)


def update_user_subscription(original_transaction_id, product_id, status, expires_date=None, tx_info=None):
    """
    Update the User subscription fields when Apple sends a notification.
    Includes handling free trials and trial → paid conversion.
    """
    try:
        user = User.query.filter_by(transaction_id=original_transaction_id).first()

        if user:
            # ✅ Existing user → update subscription
            plan = Plan.query.filter_by(app_product_id=product_id).first()
            if plan:
                user.plan_id = plan.id

            user.subscription_status = status
            user.updated_at = datetime.now(timezone.utc)

            # convert expiry
            expiry_dt = None
            if expires_date:
                if isinstance(expires_date, (int, float)):
                    expiry_dt = datetime.fromtimestamp(expires_date / 1000, tz=timezone.utc)
                elif isinstance(expires_date, str) and expires_date.isdigit():
                    expiry_dt = datetime.fromtimestamp(int(expires_date) / 1000, tz=timezone.utc)

                user.next_billing_date = expiry_dt

            # ✅ Handle trial logic
            if tx_info:
                offer_type = tx_info.get("offerType")  # e.g. FREE_TRIAL, INTRODUCTORY
                transaction_reason = tx_info.get("transactionReason")
                price = tx_info.get("price", 0)

                # --- Case 1: Free Trial purchase ---
                if offer_type and "TRIAL" in offer_type.upper():
                    if not user.trial_start_date:  # only set once
                        user.trial_start_date = datetime.now(timezone.utc)
                        user.trial_end_date = expiry_dt
                        print(f"🎁 Free Trial started: {user.trial_start_date} → {user.trial_end_date}")

                elif transaction_reason == "PURCHASE" and (not price or price == 0):
                    if not user.trial_start_date:
                        user.trial_start_date = datetime.now(timezone.utc)
                        user.trial_end_date = expiry_dt
                        print(f"🎁 Free Trial (price=0) started: {user.trial_start_date} → {user.trial_end_date}")

                # --- Case 2: Trial converts to Paid (Renewal with price > 0) ---
                elif transaction_reason == "RENEWAL" and price and price > 0:
                    # Keep trial_end_date as history, just mark as active paid
                    user.subscription_status = "active"
                    print(f"💳 Trial converted to paid subscription for {user.email}")

                # --- Case 3: Expired trial or subscription ---
                if status == "EXPIRED":
                    if user.trial_end_date and user.trial_end_date <= datetime.now(timezone.utc):
                        print(f"⏰ Trial expired for {user.email}")
                    user.trial_end_date = datetime.now(timezone.utc)

            db.session.commit()
            print(f"✅ Updated user {user.email} → plan={plan.plan if plan else 'N/A'}, "
              f"status={status}, next billing={user.next_billing_date}, "
              f"trial=({user.trial_start_date} → {user.trial_end_date})")
            return True
        else:
            # ⚠️ No user yet → update PendingSubscription instead
            pending = PendingSubscription.query.filter_by(transaction_id=original_transaction_id).first()
            if pending:
                pending.status = status
                if expires_date:
                    expiry_dt = datetime.fromtimestamp(int(expires_date) / 1000, tz=timezone.utc)
                    pending.expires_date = expiry_dt

                # Handle trial even before user exists
                if tx_info:
                    offer_type = tx_info.get("offerType")
                    price = tx_info.get("price", 0)

                    if offer_type and "TRIAL" in offer_type.upper():
                        if not pending.trial_start_date:
                            pending.trial_start_date = datetime.now(timezone.utc)
                            pending.trial_end_date = expiry_dt
                            print(f"📌 Pending Free Trial started {pending.trial_start_date} → {pending.trial_end_date}")
                    elif not price or price == 0:
                        if not pending.trial_start_date:
                            pending.trial_start_date = datetime.now(timezone.utc)
                            pending.trial_end_date = expiry_dt
                            print(f"📌 Pending Free Trial (price=0) {pending.trial_start_date} → {pending.trial_end_date}")

                pending.updated_at = datetime.now(timezone.utc)
                db.session.commit()
                print(f"📌 Updated PendingSubscription {original_transaction_id} → status={status}")
                return True

            print(f"⚠️ No User or PendingSubscription found for transaction_id={original_transaction_id}")
            return False

    except Exception as e:
        db.session.rollback()
        print("❌ Error updating subscription:", e)
        return False
    

def update_google_subscription(subscription_id, transaction_id, purchase_token, status, expiry_dt=None):
    try:
        base_tx_id = transaction_id[:24] if transaction_id else None

        # --- Try user lookup by transaction_id first ---
        user = None
        if base_tx_id:
            user = User.query.filter_by(transaction_id=base_tx_id).first()

        # --- Fallback: try by purchase_token if no user found ---
        if not user and purchase_token:
            user = User.query.filter_by(purchase_token=purchase_token).first()

        current_plan = Plan.query.filter_by(app_product_id=subscription_id).first()

        if user:
            user_plan = Plan.query.get(user.plan_id) if user.plan_id else None

            if current_plan and user_plan:
                # --- Upgrade: price higher than current → apply immediately ---
                if current_plan.price > user_plan.price:
                    user.plan_id = current_plan.id
                    user.next_plan_id = None
                    print(f"⚡ Immediate UPGRADE → {current_plan.plan}")

                # --- Downgrade: defer until next billing ---
                elif current_plan.price < user_plan.price:
                    user.next_plan_id = current_plan.id
                    print(f"⏳ Deferred DOWNGRADE scheduled → {current_plan.plan}")

                # --- Renewal or same plan ---
                else:
                    user.plan_id = current_plan.id

            # --- Apply deferred downgrade if billing ended ---
            if user.next_plan_id and status == "ACTIVE" and expiry_dt and expiry_dt <= datetime.now(timezone.utc):
                next_plan = Plan.query.get(user.next_plan_id)
                if next_plan:
                    user.plan_id = next_plan.id
                    user.next_plan_id = None
                    print(f"✅ Applied deferred downgrade → {next_plan.plan}")

            # --- Always update subscription info ---
            user.subscription_status = status
            if expiry_dt:
                user.next_billing_date = expiry_dt
            user.updated_at = datetime.now(timezone.utc)
            if base_tx_id:
                user.transaction_id = base_tx_id
            if purchase_token:
                user.purchase_token = purchase_token
            db.session.commit()

            print(f"✅ User {user.email} updated → plan={user.plan_id}, status={status}, next billing={expiry_dt}")
            return True

        # --- PendingSubscription fallback ---
        pending = None
        if base_tx_id:
            pending = PendingSubscription.query.filter_by(transaction_id=base_tx_id).first()
        if not pending and purchase_token:
            pending = PendingSubscription.query.filter_by(purchase_token=purchase_token).first()

        if pending:
            pending.status = status
            pending.expires_date = expiry_dt
            pending.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            print(f"📌 Updated PendingSubscription {pending.transaction_id} → status={status}, expiry={expiry_dt}")
            return True

        print(f"⚠️ No User or PendingSubscription found for transaction_id={transaction_id}, purchase_token={purchase_token}")
        return False

    except Exception as e:
        db.session.rollback()
        print("❌ Error updating subscription:", e)
        return False


############## GENERETE TOKEN & CONFIRMATION DELETE ACCOUNT ##############
    
def generate_delete_token(user_id):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(user_id, salt='delete-account-salt')

def confirm_delete_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        user_id = serializer.loads(
            token,
            salt='delete-account-salt',
            max_age=expiration
        )
    except Exception:
        return None
    return user_id

# Sender details which SS email, and pswd
EMAIL = "support@securessecrets.com"
PSWD = os.environ.get("EMAIL_PSWD")
SERVER = 'smtp.titan.email'
PORT = 587

# def send_report()

def reset_password_email(email, username, token):

    reset_url = url_for('main.reset_password', token=token, _external=True)

    msg = MIMEMultipart()
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email
    
    msg['Subject'] = Header('Reset Your Password for SecuresSecrets', 'utf-8')
    body = (
        f"Hi {username},\n\n"
        f"You requested to reset your password. Click the link below to reset it:\n"
        f"{reset_url}.\n\n"
        f"If you didn’t request this, you can safely ignore this email.\n\n"
        f"Best regards,\n"
        f"SecuresSecrets Support Team."
    )

    msg.attach(MIMEText(body, 'plain'))

    try:
        # Send the email via SMTP
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")


def email_reminder(email, username, trial_end_date, reminder_type):
    # Construct the email message
    msg = MIMEMultipart("related")  # Use "related" for images
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email

    if reminder_type == "trial_week":
        msg['Subject'] = Header('Your SecuresSecrets Trial Ends in 1 Week – Don’t Miss Out!', 'utf-8')
        body = (
            f"<html>"
            f"<body>"
            f"<h2>Hi {username},</h2>"
            f"<p>We hope you're enjoying your experience with SecuresSecrets!<p><br>"
            f"<p>This is a friendly reminder that your free trial will end in 1 week, on {trial_end_date}.</p><br>"
            f"<p>Best regards,</p>"
            f"<p>SecuresSecrets Support Team.</p>"
            f"<div style='padding-left: 30px;'>"
            f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
            f"</div>"
            f"</body>"
            f"</html>"
        )
        
    elif reminder_type == "trial_day":
        msg['Subject'] = Header('Your SecuresSecrets Trial Ends Tomorrow – Don’t Miss Out!', 'utf-8')
        body = (
            f"<html>"
            f"<body>"
            f"<h2>Hi {username},</h2>"
            f"<p>We wanted to remind you that your free trial with SecuresSecrets will end tomorrow, on {trial_end_date}.</p>"
            f"<p>Please pay your plan so you can continue using all the features seamlessly.</p><br>"
            f"<p>Best regards,</p>"
            f"<p>SecuresSecrets Support Team.</p>"
            f"<div style='padding-left: 30px;'>"
            f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
            f"</div>"
            f"</body>"
            f"</html>"
        )

    msg.attach(MIMEText(body, 'html'))

    # Add the logo image to the email
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')  # Use this Content-ID in the HTML
        image.add_header('Content-Disposition', 'inline', filename=os.path.basename(logo_path))
        msg.attach(image)
    except FileNotFoundError as e:
        print(f"Logo image not found at path: {logo_path}")

    try:
        # Send the email via SMTP
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")


# Reminder email to pay the subscription 
def reminder_to_pay_email(username, email, plan_name, days_left):

    msg = MIMEMultipart("related")  # Use "related" for images
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email  # Adjust accordingly

    if days_left == 5:
        msg['Subject'] = Header('Important: 5 Days Left to Renew Your Subscription!', 'utf-8')
        body = (
            f"<html>"
            f"<body>"
            f"<h2>Hi {username},</h2>"
            f"<p>This is a reminder that you have <strong>5 days</strong> left to renew your subscription for the {plan_name} plan.</p>"
            f"<p>If you do not renew, your account will be deleted after this period.</p><br>"
            f"<p>Best regards,</p>"
            f"<p>SecuresSecrets Support Team.</p>"
            f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
            f"</body>"
            f"</html>"
        )

    elif days_left == 3:
        msg['Subject'] = Header('Important: 3 Days Left to Renew Your Subscription!', 'utf-8')
        body = (
            f"<html>"
            f"<body>"
            f"<h2>Hi {username},</h2>"
            f"<p>This is a reminder that you have <strong>3 days</strong> left to renew your subscription for the {plan_name} plan.</p>"
            f"<p>If you do not renew, your account will be deleted after this period.</p><br>"
            f"<p>Best regards,</p>"
            f"<p>SecuresSecrets Support Team.</p>"
            f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
            f"</body>"
            f"</html>"
        )

    elif days_left == 1:
        msg['Subject'] = Header('Your Account Will Be Deleted Soon!', 'utf-8')
        body = (
            f"<html>"
            f"<body>"
            f"<h2>Hi {username},</h2>"
            f"<p>This is your final reminder that you have <strong>1 day</strong> left to renew your subscription for the {plan_name} plan.</p>"
            f"<p>Unfortunately, if you do not renew today, your account will be deleted.</p><br>"
            f"<p>We hope to see you back soon!</p>"
            f"<p>Best regards,</p>"
            f"<p>SecuresSecrets Support Team.</p>"
            f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
            f"</body>"
            f"</html>"
        )

    msg.attach(MIMEText(body, 'html'))

    # Add the logo image to the email
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')  # Use this Content-ID in the HTML
        msg.attach(image)
    except FileNotFoundError as e:
        print(f"Logo image not found at path: {logo_path}")

    try:
        # Send the email via SMTP
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")

# User payment email
def send_payment_email(email, username, plan_name, payment_amount, payment_date, subscription_type, card_type, last_4_digit):
    # Set up message
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email

    # Select subject and unique content per subscription type
    if subscription_type == "new":
        msg['Subject'] = Header(f'{plan_name} Plan SecuresSecrets!', 'utf-8')
        unique_content = (
            f"<p>Welcome to SecuresSecrets! We're happy to have you with us.</p>"
            f"<p>Your new subscription has been successfully activated, and you're all set to enjoy your plan's features.</p>"
        )
    elif subscription_type == "upgrade":
        msg['Subject'] = Header('Your Plan Has Been Changed!', 'utf-8')
        unique_content = (
            f"<p>Your plan has been successfully changed, and you now have access to additional features.</p>"
        )
    elif subscription_type == "renewal":
        msg['Subject'] = Header('Your Subscription Has Been Renewed!', 'utf-8')
        unique_content = (
            f"<p>Thank you for renewing your subscription with SecuresSecrets.</p>"
            f"<p>Your subscription is now active, and you have full access to all the features included in your plan.</p>"
        )
    
    # Construct body
    body = (
        f"<html>"
        f"<body style='font-family: Arial, sans-serif; color: #333;'>"
        f"<p>Dear {username},</p>"
        f"{unique_content}"
        f"<h3>Plan Details</h3>"
        f"<ul>"
        f"<li><strong>Plan Name:</strong> {plan_name}</li>"
        f"<li><strong>Amount Paid:</strong> ${payment_amount:.2f} USD</li>"
        f"<li><strong>Date of Payment:</strong> {payment_date.strftime('%B %d, %Y')}</li>"
        f"</ul>"
        f"<p><strong>Payment Method:</strong> {card_type} ending in {last_4_digit}</p>"
        f"<p><strong>Total Charged:</strong> -${payment_amount:.2f} USD</p>"
        f"<p><strong>Total Due:</strong> $0.00 USD</p>"
        f"<h3>Activation Timeline</h3>"
        f"<p>{payment_date.strftime('%B %d, %Y')} - {subscription_type.capitalize()} successful</p>"
        f"<p>If you have any questions or need assistance, please reach out to our support team. We're here to help!</p>"
        f"<p>Best regards,<br>SecuresSecrets Support Team.</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto; margin-top:10px;' alt='SecuresSecrets Logo'>"
        f"</body>"
        f"</html>"
    )

    msg.attach(MIMEText(body, 'html'))

    # Add inline logo image
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')
        msg.attach(image)
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")

    # Send email
    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")



# If payment failed
def send_payment_failed_email(email, username, failure_status, plan_name, card_type, last_4_digit):
    # Construct the email message
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email
    msg['Subject'] = Header('Payment Failure Notice', 'utf-8')

    body = (
        f"<html>"
        f"<body>"
        f"<p>Dear {username},</p>"
        f"<p>Unfortunately, your recent attempt to renew your subscription for the {plan_name} plan failed due to the following reason:</p>"
        f"<p><strong>Status: {failure_status}</strong></p>"
        f"<p>Payment Method: {card_type} ending in {last_4_digit}</p>"
        f"<p>Please update your payment details or try again to avoid any interruptions in your service.</p>"
        f"<p>If you have any questions or need further assistance, feel free to contact our support team.</p>"
        f"<p>Best regards,<br>SecuresSecrets Support Team.</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
        f"</body>"
        f"</html>"
    )

    msg.attach(MIMEText(body, 'html'))

    # Add the logo image to the email
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')
        msg.attach(image)
    except FileNotFoundError as e:
        print(f"Logo image not found at path: {logo_path}")

    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")

# Verification email
def send_verification_email(user_email, username, token):
    
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = user_email
    msg['Subject'] = Header('Welcome to SecuresSecrets!', 'utf-8')

    # Use external=True to generate an absolute URL
    verification_url = url_for('main.confirm_email', token=token, _external=True)
    
    body = (
        f"<html>"
        f"<body>"
        f"<h2>Hi {username},</h2>"
        f"<p>Thank you for signing up to SecuresSecrets. Before we can continue, we need to validate your email address.</p>"
        f"<p>Please click the link below to verify your email:</p>"
        f"<p><a href='{verification_url}'>{verification_url}</a></p>"
        f"<p>Best regards,<br>SecuresSecrets Support Team.</p>"
        f"<div style='padding-left: 30px;'>"
        f"<img src='cid:logo_image' style='width:150px; height:auto;' alt='Logo'>"
        f"</div>"
        f"</body>"
        f"</html>"
    )

    msg.attach(MIMEText(body, 'html'))

    # Add the logo image to the email
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')  # Use this Content-ID in the HTML
        image.add_header('Content-Disposition', 'inline', filename=os.path.basename(logo_path))
        msg.attach(image)
    except FileNotFoundError as e:
        print(f"Logo image not found at path: {logo_path}")

    try:
        # Send the email via SMTP
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {user_email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {user_email}: {str(e)}")

# Sending the eamil
def send_secret_email(email, secret_url):
    # Construct the email message
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email
    msg['Subject'] = Header('Important: Access Your Secret', 'utf-8')
    # Email body
    body = (
        f"<html>"
        f"<body>"
        f"<p>Hi there,</p>"
        f"<p>This secret has been shared with you securely and privately. Only you have access to this information. "
        f"Feel at ease knowing your privacy is protected.</p>"
        f"<p><a href='{secret_url}'>Click here to view the secret</a></p>"
        f"<p><small>Note: the link will be deleted 1 hour after you open this link.</small></p>"
        f"<p>Best regards,</p>"
        f"<p>SecuresSecrets Support Team.</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto; margin-top:10px;' alt='SecuresSecrets Logo'>"
        f"</body>"
        f"</html>"
    )
    msg.attach(MIMEText(body, 'html'))

    # Add inline logo image
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')
        msg.attach(image)
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")

    # Send the email via SMTP
    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {email}. SMTP error: {str(e)}")
        raise  # Re-raise the exception to be handled by Celery
    except Exception as e:
        print(f"An unexpected error occurred while sending email to {email}: {str(e)}")
        raise  # Re-raise the exception to be handled by Celery

# contact us email
def contact_email(name, email, subject, message):
    # User email setup
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email
    msg['Subject'] = Header('Thank You for Reaching Out!', 'utf-8')

    # Construct user email body
    body = (
        f"<html>"
        f"<body style='font-family: Arial, sans-serif; color: #333;'>"
        f"<p>Dear {name},</p>"
        f"<p>Thank you for contacting SecuresSecrets! We have received your message and appreciate you reaching out to us.</p>"
        f"<h3>Your Contact Details</h3>"
        f"<ul>"
        f"<li><strong>Name:</strong> {name}</li>"
        f"<li><strong>Email:</strong> {email}</li>"
        f"<li><strong>Subject:</strong> {subject}</li>"
        f"</ul>"
        f"<h3>Your Message</h3>"
        f"<p>{message}</p>"
        f"<p>We will review your message and get back to you as soon as possible. If you have any additional questions or need immediate assistance, please reply to this email or reach out to our support team.</p>"
        f"<p>Best regards,<br>SecuresSecrets Support Team.</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto; margin-top:10px;' alt='SecuresSecrets Logo'>"
        f"</body>"
        f"</html>"
    )
    msg.attach(MIMEText(body, 'html'))

    # Add inline logo image
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            img_data = img.read()
        image = MIMEImage(img_data, name=os.path.basename(logo_path))
        image.add_header('Content-ID', '<logo_image>')
        msg.attach(image)
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")

    # Admin notification setup
    admin_msg = MIMEMultipart("alternative")
    admin_msg['From'] = formataddr(('SecuresSecrets Notifications', EMAIL))
    admin_msg['To'] = EMAIL
    admin_msg['Subject'] = Header('New Contact Us Submission', 'utf-8')

    admin_body = (
        f"<html>"
        f"<body style='font-family: Arial, sans-serif; color: #333;'>"
        f"<h3>New Contact Us Submission</h3>"
        f"<ul>"
        f"<li><strong>Name:</strong> {name}</li>"
        f"<li><strong>Email:</strong> {email}</li>"
        f"<li><strong>Subject:</strong> {subject}</li>"
        f"<li><strong>Message:</strong><br>{message}</li>"
        f"</ul>"
        f"<p>Sent from the contact form on your site.</p>"
        f"</body>"
        f"</html>"
    )
    admin_msg.attach(MIMEText(admin_body, 'html'))

    # Send emails
    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            # Send email to user
            connection.send_message(msg)
            # Send email to admin
            connection.send_message(admin_msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An unexpected error occurred while sending emails: {str(e)}")

def send_report_email(secret_id, secret, secret_file, report_details):
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = EMAIL
    msg['Subject'] = Header('New Secret Report Submitted', 'utf-8')

    # Build HTML content in parts
    body = (
        f"<html>"
        f"<body>"
        f"<p>Hi Team,</p>"
        f"<p>A public secret has been reported by a user.</p>"
        f"<p><strong>Secret ID:</strong> {secret_id}</p>"
        f"<p><strong>Reason:</strong></p>"
        f"<blockquote style='background:#f8f9fa;padding:10px;border-left:3px solid #dc3545;'>"
        f"{report_details}</blockquote>"
        f"<p><strong>Secret:</strong> {secret}</p>"
    )

    # Include file only if it exists
    if secret_file:
        file_url = f"{url_for('main.download_file', filename=secret_file, _external=True)}"  # Replace with your file route
        if secret_file.endswith(('.png', '.jpg', '.jpeg', '.gif')):
            print(file_url)
            body += f'<img src="{file_url}" alt="File Preview" style="max-width: 50%; height: auto;">'
        elif secret_file.endswith('.pdf'):
            body += f'<iframe src="{file_url}" style="width: 50%; height: auto; border: none;"></iframe>'
        elif secret_file.endswith(('.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
            body += f'<iframe src="https://docs.google.com/viewer?url={file_url}&embedded=true" style="width: 50%; height: auto; border: none;"></iframe>'
        else:
            body += f'<p><strong>Download Attachment:</strong>\
                <a href="{file_url}" class="link-primary" download><i class="bi bi-file-earmark-arrow-down">\
                    </i> {secret_file}</a></p>'
    # Finish HTML
    body += (
        f"<p>Best regards,<br>SecuresSecrets Report System</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto; margin-top:10px;' alt='SecuresSecrets Logo'>"
        f"</body>"
        f"</html>"
    )

    msg.attach(MIMEText(body, 'html'))

    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            image = MIMEImage(img.read(), name=os.path.basename(logo_path))
            image.add_header('Content-ID', '<logo_image>')
            msg.attach(image)
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")

    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"SMTP error: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error sending report email: {str(e)}")
        raise


def send_delete_account_email(user, verification_link, instructions=""):
    """
    Send account deletion confirmation email with optional platform-specific instructions.
    :param user: User object
    :param verification_link: URL for verifying deletion
    :param instructions: Optional text to instruct user about subscription cancellation
    """
    msg = MIMEMultipart("related")
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = user.email
    msg['Subject'] = Header('Verify Account Deletion', 'utf-8')

    # Default message if no instructions provided
    subscription_note = f"<p>{instructions}</p>" if instructions else ""

    # Email HTML body
    body = f"""
    <html>
    <body>
        <p>Hi {user.username},</p>
        <p>You requested to <strong>delete your account</strong>. 
        Once you confirm, <span style="color:#dc3545; font-weight:bold;">your account and all associated data will be permanently deleted immediately</span>.</p>

        <span style="color:#dc3545; font-weight:bold;"></span><p style="color:#dc3545; font-size:0.75rem;">{subscription_note}</p>

        <p style="text-align:center; margin:20px;">
            <a href="{verification_link}" 
            style="background-color:#dc3545;color:white;
                    padding:12px 24px;text-decoration:none;
                    border-radius:6px;font-weight:bold;">
            Verify Deletion
            </a>
        </p>

        <p>If you did not request this, please ignore this email. 
        Your account will not be deleted.</p>
        <br>
        <p>Best regards,<br>SecuresSecrets Team</p>
        <img src="cid:logo_image" style="width:150px; height:auto; margin-top:10px;" alt="SecuresSecrets Logo">
    </body>
    </html>
    """

    msg.attach(MIMEText(body, 'html'))

    # Attach logo
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.webp')
    try:
        with open(logo_path, "rb") as img:
            image = MIMEImage(img.read(), name=os.path.basename(logo_path))
            image.add_header('Content-ID', '<logo_image>')
            msg.attach(image)
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")

    # Send email
    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"SMTP error: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error sending deletion email: {str(e)}")
        raise

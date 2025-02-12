from flask import abort, request, url_for, session, flash, redirect
from flask_login import current_user
from functools import wraps
from urllib.parse import urlparse, urljoin
from . import db, login_manager
from .models import User, Secret, Plan, Payment, HistoryPayment
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from wtforms.validators import DataRequired, Email, Regexp, ValidationError
import base64
import requests
import secrets
import re
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formataddr
from email.header import Header
import logging
import uuid
import json
import pytz


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
def subscription_ended():
    def decorator(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            current_date = datetime.now(timezone.utc).date()
            
            # Check if the user is logged in
            if not current_user.is_authenticated:
                return redirect(url_for('main.login'))  # Redirect to login if not logged in
            
            # Bypass subscription check for admin
            if current_user.username == 'admin':
                return func(*args, **kwargs)  # Allow full access for admin
            
            # Check if the subscription is valid
            if (
                ((current_user.trial_end_date and current_user.trial_end_date.date() >= current_date) or
                (current_user.subscription_status == "ACTIVE" and
                (current_user.next_billing_date and current_user.next_billing_date.date() >= current_date)))
            ):
                # If the subscription is active, allow full access
                return func(*args, **kwargs)
            
            # If the subscription has ended, restrict access to certain routes
            if func.__name__ not in ('main.dashboard', 'main.payment'):
                return redirect(url_for('main.dashboard'))  # Redirect to dashboard for restricted users
            
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


# Helper function to the billing page and upgrading plan
def populate_plan_choices(form, user):
    plans = Plan.query.order_by(Plan.price).all()

    # Populate the choices of the SelectField based on available plans
    available_plans = [(0, "---Select a Plan---")] + [
        (plan.id, f"{plan.plan} - {plan.price} {plan.currency} ({plan.storage_limit / (1024 * 1024):.0f} MB)")
        for plan in plans if plan.id > user.plan_id
    ] + [
        (plan.id, f"{plan.plan} - {plan.price} {plan.currency} ({plan.storage_limit / (1024 * 1024):.0f} MB)")
        for plan in plans if plan.id < user.plan_id
    ]
    
    if available_plans:
        form.plan_id.choices = available_plans


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
        raise ValidationError("Period must be number/s from 1 to 360.")

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
    """Validator to check if the selected time is today but not in the future."""
    if field.data:
        selected_time = field.data.time().replace(second=0, microsecond=0)  # Remove seconds and microseconds
        current_time = datetime.now().time().replace(second=0, microsecond=0)  # Remove seconds and microseconds # Get only the time part (ignore the date)
        
        # Check if the selected time is in the future compared to the current time
        if selected_time < current_time:
            raise ValidationError("The selected time cannot be in the future.")

# Converting time to user time
def convert_utc_to_local(utc_time, user_time_zone):
    print(f"Converting time: {utc_time} to {user_time_zone}")  # Debug print

    if not user_time_zone:  # Ensure time zone exists
        user_time_zone = "UTC"

    try:
        local_tz = pytz.timezone(user_time_zone)  # Get the timezone object
    except pytz.UnknownTimeZoneError:
        print("Invalid timezone detected! Falling back to UTC.")  # Debug print
        local_tz = pytz.utc  # If time zone is invalid, fallback to UTC

    if isinstance(utc_time, str):  # Convert string to datetime if needed
        print("utc_time is a string, converting to datetime object.")  # Debug print
        utc_time = datetime.strptime(utc_time, "%Y-%m-%d %H:%M:%S")  

    utc_time = utc_time.replace(tzinfo=pytz.utc)  # Ensure it's UTC
    local_time = utc_time.astimezone(local_tz)  # Convert to local timezone

    print(f"Final local time: {local_time}")  # Debug print
    return local_time.strftime("%Y-%m-%d %H:%M:%S")  # Return as string

# Configures PayPal Payment Gateway
# TAP_PROD_SECRET_KEY = os.environ.get("TAP_PROD_SECRET_KEY")
####################### LIVE ACTION #######################
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_LIVE_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_LIVE_CLIENT_SECRET")
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_LIVE_WEBHOOK_ID")
API_URL = "https://api-m.paypal.com/v1"
####################### SENDBOX ACTION #######################
# PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_SENDBOX_CLIENT_ID")
# PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_SENDBOX_CLIENT_SECRET")
# PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_SENDBOX_WEBHOOK_ID") # Webhook ID
# API_URL = "https://api-m.sandbox.paypal.com/v1"
# Generating request id
request_id = uuid.uuid4()
API_KEY = "sk_test_XKokBfNWv6FIYuTMg5sLPjhJ"

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
    test_plan_json = json.dumps(test_non_trial_plan)

    url = f"{API_URL}/billing/plans"

    ############################################ Create the Basic and Premium Plans ############################################
    # response_basic = requests.post(url, headers=headers, data=basic_plan_json)
    # response_premium = requests.post(url, headers=headers, data=premium_plan_json)
    # response_basic_non_trial = requests.post(url, headers=headers, data=basic_non_trial_plan_json)
    # response_premium_non_trial = requests.post(url, headers=headers, data=premium_non_trial_plan_json)
    response_test_plan = requests.post(url, headers=headers, data=test_plan_json)
    # response_test_trial_plan = requests.post(url, headers=headers, data=test_plan_json)

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
        print("Failed to get user subscription details:")
        print(response.json())

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

# Creating a charge and redirecting to Tap's hosted payment page, handling 3D Secure if needed
def create_charge(amount, currency, description, email, phone_country_code, phone_number, first_name, plan_id, source_id):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }

    data = {
        'amount': float(amount),
        'currency': currency,
        "save_card": True,
        'description': description,
        'customer': {
            'email': email,
            'phone': {
                'country_code': phone_country_code,
                'number': phone_number
            },
            'first_name': first_name
        },
        'source': {
            'id': source_id, 
        },
        'redirect': {
            'url': url_for('main.payment_complete', _external=True, plan_id=plan_id)
        }
    }

    response = requests.post(f"{API_URL}/charges", headers=headers, json=data)
    
    if response.status_code == 200:
        charge_response = response.json()

        # Handle 3D Secure if required
        if charge_response.get('status') == 'INITIATED':
            if charge_response.get('threeDSecure', False):
                # If 3D Secure is required, redirect to the 3D Secure authentication page
                payment_url = charge_response.get('transaction', {}).get('url')
                if payment_url:
                    return payment_url  # Return URL for redirection to 3D Secure
                else:
                    raise Exception("Failed to retrieve 3D Secure redirection URL.")
            else:
                return charge_response  # If no 3D Secure is needed, return the charge response

        raise Exception(f"Payment initiation failed: {charge_response.get('response', {}).get('message', 'Unknown error')}")

    else:
        error_details = response.json()
        print(error_details)
        description = error_details.get('response', {}).get('message', 'Unknown error occurred')
        raise Exception(f"Charge creation failed: {description}")

# Getting Charge Details by charge_id
def get_charge_details(charge_id):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }

    url = f"{API_URL}/charges/{charge_id}"
    response = requests.get(url, headers=headers)
    print(response.json())

    if response.status_code == 200:
        return response.json()
    else:
        error_details = response.json()
        raise Exception(f"Failed to fetch charge details {error_details}")
    

#  Retrieving card details
def retrieve_cards_details(customer_id, card_id):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }
    url = f"{API_URL}/card/{customer_id}/{card_id}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("Failed to fetch card details")

# Savig card token before the end of the trial
def tokenize_card(card, ex_month, ex_year, cvc, name):
    headers = {
        "Authorization": f'Bearer {API_KEY}',
        "Content-Type": "application/json"
    }
    print(card, ex_month, ex_year, cvc, name)
    payload = {
        "card": {
            "number": card,
            "exp_month": ex_month,
            "exp_year": ex_year,
            "cvc": cvc,
            "name": name
        }
    }
    url = f"{API_URL}/tokens"
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
            return response.json()
    else:
        error_details = response.json()  # Get detailed error message from the response
        print("Error Status Code:", response.status_code)
        print("Error Response:", error_details)
        error_message = error_details.get('response', {}).get('message', 'Unknown error occurred')
        raise Exception(f"Failed to fetch card token: {error_message}")
    

# Creating a token (saved card)
def generate_card_token(customer_id, card_id, client_ip):

    payload = {
        "saved_card": {
            "card_id": card_id,
            "customer_id": customer_id
        },
        "client_ip": client_ip
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f'Bearer {API_KEY}'
    }

    url = f"{API_URL}/tokens"
    response = requests.post(url, json=payload, headers=headers)
    print(response.json())
    if response.status_code == 200:
            return response.json()
    else:
        raise Exception("Failed to fetch saved card token")
    

# Initiating recurring payment 'SUBSCRIPTION PAYMENT'
def recurring_payment(customer_id, card_id, client_ip, payment_agreement_id, amount, currency, description):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json',
    }

    # Use the generated token from the saved card
    token = generate_card_token(customer_id, card_id, client_ip)

    data = {
        'amount': float(amount),
        'currency': currency,
        'customer': {
            'id': customer_id
        },
        'source': {
            'id': token['id']  # Use the token generated from the saved card
        },
        'save_card': False,  # Since the card is already saved, no need to save again
        'description': description,
        'payment_agreement': {
            'id': payment_agreement_id
        },
        'customer_initiated': False  # Mark as merchant-initiated transaction
    }

    response = requests.post(f"{API_URL}/charges", headers=headers, json=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        error_details = response.json()
        print(error_details)
        raise Exception(f"Recurring payment initiation failed: {error_details.get('response', {}).get('message', 'Unknown error')}")
        

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

        user_ip = get_ip()
        user_agent = get_user_agent()
        
        # Create a new payment record in the database
        new_payment = Payment(
            user_id=user.id,
            amount=payment_amount,
            currency=currency,
            transaction_id=transaction_id,
            payment_date=datetime.fromisoformat(payment_time.replace("Z", "+00:00")),  # Convert PayPal time format
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

        next_billing = billing_info.get("next_billing_time")
        if next_billing and user.next_billing_date != next_billing:
            user.next_billing_date = datetime.fromisoformat(next_billing.replace("Z", "+00:00"))

        # Fix: Use .get() to safely access subscriber details
        user.paypal_payer_id = subscriber.get("payer_id", user.paypal_payer_id)  # Keep existing payer_id if missing

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

# Recurring payment process
def initiate_recurring_payment():
    logger.info("Executing recurring payment logic.")
    current_date = datetime.now(timezone.utc).date()
    users = User.query.filter(User.subscription_end_date <= current_date).all()
    for user in users:

        payment_method = Payment.query.filter_by(user_id=user.id).first()
        # Ensure subscription_end_date is timezone-aware (assumed UTC)
        if user.subscription_end_date:
            if user.subscription_end_date.tzinfo is None:
                subscription_end_date = user.subscription_end_date.replace(tzinfo=timezone.utc)
            else:
                subscription_end_date = user.subscription_end_date

            # Get only the date part of subscription_end_date (ignore time)
            subscription_end_date = subscription_end_date.date()

            if current_date > subscription_end_date:
                user_plan = db.get_or_404(Plan, user.plan_id)
                print(user_plan)
                customer_id = user.customer_id
                card_id = user.card_id
                user_ip = payment_method.ip_address
                payment_agreement_id = user.payment_agreement_id
                amount = user_plan.price
                currency = user_plan.currency
                description = f"Recurring Payment {user_plan.plan}"

                try:
                    payment_response = recurring_payment(customer_id, card_id, user_ip, payment_agreement_id, amount, currency, description)

                    if payment_response['status'] == 'CAPTURED':

                        history = HistoryPayment(
                            user_id=user.id,
                            plan_id=user.plan_id,
                            amount=payment_response['amount'],
                            currency=payment_response['currency'],
                            payment_method=payment_response['source']['payment_type'],
                            payment_status=payment_response['status'],
                            transaction_id=payment_response['id'],
                            card_brand=payment_response['card']['brand'],
                            card_last_four=payment_response['card']['last_four'],
                            authorization_id=payment_response['transaction']['authorization_id']
                        )

                        # Update the subscription end date (monthly/yearly)
                        if user_plan.billing_cycle == 'monthly':
                            user.subscription_start_date = current_date
                            user.subscription_end_date = current_date + timedelta(days=29)
                            user.subscription_status = "active"

                        send_payment_email(user.email, user.username, user_plan.plan, amount, current_date, "renewal", payment_method.card_brand, payment_method.card_last_four)
                        
                        db.session.add(history)
                        db.session.commit()

                        print("Recurring payment successful!")
                    elif payment_response['status'] in ['FAILED', 'DECLINED']:
                        # Send failure email
                        send_payment_failed_email(user.email, user.username, payment_response['status'], user_plan.plan, payment_method.card_brand, payment_method.card_last_four)

                        print("Recurring payment failed due to card issue.")
                except Exception as e:
                    print(str(e))


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
    users = User.query.filter(User.subscription_end_date <= current_date).all()

    for user in users:

        if user.username == 'admin':
            continue  # Skip processing for admin user

        plan = Plan.query.filter_by(id=user.plan_id).first()
        if user.subscription_end_date:
            if user.subscription_end_date.tzinfo is None:
                subscription_end_date = user.subscription_end_date.replace(tzinfo=timezone.utc)
            else:
                subscription_end_date = user.subscription_end_date
            
            # Get only the date part of subscription_end_date (ignore time)
            subscription_end_date = subscription_end_date.date()

            # will make the user inactive if the subscription ended
            if subscription_end_date > current_date:
                user.subscription_status = "inactive"
                db.session.commit()

            # Calculate the difference in days
            days_left = (subscription_end_date - current_date).days

            if days_left in [-5, -3, -7]:
                days_left = abs(days_left)

            logger.info(days_left)

            if days_left in [5, 3, 1]:  # Send reminders at 5, 3, and 1 day left
                reminder_to_pay_email(user.username, user.email, plan.plan, days_left)
                
                # If it's the last reminder (1 day), delete the user
                if days_left == 1:
                    db.session.delete(user)
                    db.session.commit()


# When user pay his own plan manualy
def pay_plan_now():
    current_date = datetime.now(timezone.utc)
    if current_user:
        user_plan = db.get_or_404(Plan, current_user.plan_id)
        customer_id = current_user.customer_id
        card_id = current_user.card_id
        user_ip = get_ip()
        payment_agreement_id = current_user.payment_agreement_id
        amount = user_plan.price
        currency = user_plan.currency
        description = f"Paying for {user_plan.plan}"

        try:
            payment_response = recurring_payment(customer_id, card_id, user_ip, payment_agreement_id, amount, currency, description)

            if payment_response['status'] == 'CAPTURED':
                print("Recurring payment successful!")
                flash("Payment was successful!", "success")

                if user_plan.billing_cycle == 'monthly':
                    current_user.subscription_end_date = current_date + timedelta(days=30)
                    current_user.subscription_status = "active"
                send_payment_email(current_user, current_user.username, user_plan.plan, amount, current_date, "renewal", payment_response['card']['brand'], payment_response['card']['last_four'])
                db.session.commit()
            else:
                print("Recurring payment failed.")
        except Exception as e:
            print(str(e))


# Generating a token
def generate_token():
    return secrets.token_urlsafe(32)


# Sender details which SS email, and pswd
EMAIL = "support@securessecrets.com"
PSWD = os.environ.get("EMAIL_PSWD")
SERVER = 'smtp.titan.email'
PORT = 587

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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
def contact_email(name, email, phone, message):
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
        f"<li><strong>Phone:</strong> {phone}</li>"
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
    logo_path = os.path.join(os.path.dirname(__file__), 'static/assets/images/logoss.png')
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
        f"<li><strong>Phone:</strong> {phone}</li>"
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


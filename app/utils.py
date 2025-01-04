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
                (current_user.subscription_status == "active" and
                (current_user.subscription_end_date and current_user.subscription_end_date.date() >= current_date)))
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
ALLOWED_DOMAINS = {
    "gmail", "hotmail", "outlook", "yahoo", "icloud", "aol",
    "live", "msn", "comcast", "yandex", "mail", "protonmail",
    "zoho", "gmx", "fastmail"
}

ALLOWED_TLDS = {".com", ".net", ".org", ".edu", ".gov", ".mil", ".qa", ".fr", ".de", ".uk", ".ca", ".us"}


def email_domain_validator(form, field):
    """
    Validates email addresses to ensure they are from allowed domains and have allowed TLDs.
    """
    # Regex for extracting email domain
    domain_pattern = r'^[a-zA-Z0-9_.+-]+@([a-zA-Z0-9-]+)\.([a-zA-Z]+)$'
    
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
        
        domain_name = match.group(1)  # Extract the domain name (e.g., 'gmail')
        tld = f".{match.group(2)}"   # Extract the TLD (e.g., '.com')
        
        # Check if domain and TLD are allowed
        if domain_name not in ALLOWED_DOMAINS or tld not in ALLOWED_TLDS:
            raise ValidationError(
                f"'{email}' must be from an allowed domain like Gmail, Yahoo, Outlook, etc., "
                f"and end with a common TLD such as .com, .net, or .org."
            )

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

# Configures Tap payment
# API_KEY = os.environ.get("TAP_PROD_SECRET_KEY")
# API_KEY = os.environ.get("TAP_TEST_API_SECRET")
API_KEY = "sk_test_XKokBfNWv6FIYuTMg5sLPjhJ"
API_URL = "https://api.tap.company/v2"

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
        f"The SecuresSecrets Team"
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
            f"<p>The SecuresSecrets Team</p>"
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
            f"<p>The SecuresSecrets Team</p>"
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
            f"<p>The SecuresSecrets Team</p>"
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
            f"<p>The SecuresSecrets Team</p>"
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
            f"<p>The SecuresSecrets Team</p>"
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
        f"<p>Best regards,<br>The SecuresSecrets Team</p>"
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
        f"<p>Best regards,<br>The SecuresSecrets Team</p>"
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
    
    msg = MIMEMultipart()
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
        f"<p>Best regards,<br>The SecuresSecrets Team</p>"
        f"<img src='cid:logo_image' style='width:150px; height:auto; margin-top:10px;' alt='SecuresSecrets Logo'>"
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
    except FileNotFoundError:
        print(f"Logo image not found at path: {logo_path}")
    
    try:
        with smtplib.SMTP(SERVER, PORT) as connection:
            connection.starttls()
            connection.login(EMAIL, PSWD)
            connection.send_message(msg)
    except smtplib.SMTPException as e:
        print(f"Failed to send email to {user_email}. SMTP error: {str(e)}")
    except Exception as e:
        print(f"An error occurred while sending email to {user_email}: {str(e)}")


# Sending the eamil
def send_secret_email(email, secret_url):
    # Construct the email message
    msg = MIMEMultipart()
    msg['From'] = formataddr(('SecuresSecrets Team', EMAIL))
    msg['To'] = email
    msg['Subject'] = Header('Important: Access Your Secret', 'utf-8')
    print(email, secret_url)
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
        f"<p>The SecuresSecrets Team</p>"
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
        f"<p>Best regards,<br>The SecuresSecrets Team</p>"
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


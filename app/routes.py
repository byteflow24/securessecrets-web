from flask import Blueprint, render_template, redirect, url_for, send_from_directory, flash, request, session, jsonify, current_app, abort, send_file
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from . import db, csrf
from .forms import SecretForm, RegisterForm, LoginForm, SearchForm, ShareForm, ProfileForm, ChangePasswordForm, PlanUpgradeForm, ForgetPaswdForm, ContactUsForm
from .models import User, LoginHistory, Secret, Payment, Plan, SharedSecret
from .utils import get_unique_title, storage_client, GCS_BUCKET, send_whatsapp_message, subscription_ended_flag, storage_exceeded_flag, require_pricing_session, subscription_ended, convert_utc_to_local, generate_token, send_verification_email, is_safe_url, decrypt_secrets, get_subscription_details, create_assessment, is_suspicious_input, get_access_token, create_product, deactivate_plan, create_plan, call_plans, create_new_subscription, cancel_subscription, verify_paypal_webhook, change_subscription_plan, handle_payment_success, handle_subscription_created, handle_subscription_activated, handle_subscription_canceled, handle_subscription_suspended, handle_subscription_updated, handle_payment_failed, is_encrypted, encrypt_secret, decrypt_secret, send_payment_email, reset_password_email, send_report_email, contact_email, serve_file, generate_delete_token, send_delete_account_email, confirm_delete_token, upload_to_gcs, get_signed_url, gcs_file_exists, _serve_file, delete_from_gcs, get_gcs_file_size, convert_local_to_utc
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, desc, func, or_
from datetime import date, datetime, timedelta, timezone 
from google.cloud import storage
from google.oauth2 import service_account
from dateutil.relativedelta import relativedelta
from io import BytesIO
import pytz, paypalrestsdk, uuid, time, json, os, traceback, requests, logging, jwt, mimetypes, psutil

# Handle Google Application Credentials
if "GOOGLE_APPLICATION_CREDENTIALS_JSON" in os.environ:
    creds_path = "/tmp/google-credentials.json"
    with open(creds_path, "w") as f:
        f.write(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
else:
    raise EnvironmentError("Missing GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable.")

main = Blueprint('main', __name__)

# logging.basicConfig(level=logging.DEBUG)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(get_remote_address)

@main.errorhandler(CSRFError)
def handle_csrf_error(e):
    return redirect(url_for('main.login'))

# allows users to change the language
@main.route('/set_language/<lang>')
def set_language(lang):
    # Set the selected language in the session
    session['lang'] = lang
    # print(f"Language set to: {session['lang']}")
    return redirect(request.referrer or url_for('main.dashboard'))

# flask middleware to ensure flashes are cleared
@main.after_request
def clear_flashes(response):
    # Only clear flashes for text/html responses after rendering
    if '_flashes' in session and 'text/html' in response.content_type:
        if 'flash-messages' in response.get_data(as_text=True):
            session.pop('_flashes', None)
    return response

# Add the before_request function
@main.before_request
def make_session_permanent():
    # Skip session handling for specific routes (e.g., login, static files)
    if request.endpoint in ['main.login', 'static']:
        return

    # Ensure the session is marked as permanent
    session.permanent = True
    session.modified = True

    # Check if 'last_activity' exists in session
    if 'last_activity' in session:
        now = datetime.now()
        last_activity = session['last_activity']

        # Ensure last_activity is naive datetime (remove timezone if exists)
        if hasattr(last_activity, 'tzinfo') and last_activity.tzinfo is not None:
            last_activity = last_activity.replace(tzinfo=None)

        # Check for inactivity (15 minutes = 900 seconds)
        if (now - last_activity).total_seconds() > 900:
            session.clear()  # Clear session to log the user out
            flash('Your session has ended due to inactivity. Please log in again.', 'danger')
            
            # Signal the frontend about the session end
            response = redirect(url_for('main.login'))
            response.set_cookie("sessionEnded", "true")
            return response  # Redirect to login page

    # Update last activity timestamp to current time
    session['last_activity'] = datetime.now()


@main.route('/', methods=['GET', 'POST'])
def home():
    form = ContactUsForm()
    # Fetch the public shared secrets, eager-load user and secret relationships
    shared_secret = db.session.execute(
        db.select(SharedSecret)
        .where(SharedSecret == True, 
            (SharedSecret.time_period != None) | (SharedSecret.time_to_send != None))
        .options(joinedload(SharedSecret.user), joinedload(SharedSecret.secret))
    ).scalars().all()

    current_date = datetime.now().date()
    current_time = datetime.now().time()
    # send_whatsapp_message(
    #     to_number="+97455676464",
    #     sender_name="Secures Secrets Team",
    #     secret_text="Hi dear, this is a secret message.",
    #     timestamp=datetime.now(),
    #     # file_url=file_url
    # )

    # send_whatsapp_message("+97433629868", "Hi dear,\nThis is me Taha, it's my last thing I can tell you.\n Be carful and fully powered, be a great and manage all things by your hands.\n I know you, you can do it, what ever it will take.\n\n\n This secret has been privded by Secures Secrets from someone you know.")
    # Check if the user logged in recently and update the time period or scheduled date
    for secret in shared_secret:
        # Get the most recent login date for the user
        latest_login = db.session.execute(
            db.select(LoginHistory.login_time)
            .where(LoginHistory.user_id == secret.user_id)
            .order_by(desc(LoginHistory.login_time))
            .limit(1)
        ).scalar_one_or_none()

        # Initialize date_time with None for cases when no scheduled date is set
        date_time = None

        # If a recent login exists and it's more recent than the current last_login
        if latest_login and (secret.last_login is None or latest_login > secret.last_login):
            # Update the last_login to the latest login date
            secret.last_login = latest_login

            # Handle `period` and calculate `time_period` if `period` is present
            if secret.period:
                try:
                    # Only extend if current time_period is still in the future
                    if not secret.time_period or secret.time_period > datetime.now():
                        # Calculate the new time period based on the period (e.g., days)
                        time_period = latest_login + timedelta(days=int(secret.period))
                        secret.time_period = time_period
                except ValueError:
                    # Skip this secret if `period` is invalid but do not raise an error
                    continue

        # Handle the scenario when `date_to_send` and `time_to_send` are used
        if secret.date_to_send == current_date and secret.time_to_send == current_time:
            # Combine date_to_send and time_to_send if they exist and match the current time
            date_time = datetime.combine(secret.date_to_send, secret.time_to_send)

        # Update the associated SharedSecret share_date if available
        public_secret = SharedSecret.query.filter_by(id=secret.id).first()

        if public_secret:
            # Update share_date based on valid `time_period` or `date_time`
            if secret.time_period:
                public_secret.share_date = secret.time_period
            elif date_time:
                public_secret.share_date = date_time

    # Commit changes to the database
    db.session.commit()

    # Fetch all public shared secrets with eligible share_date, sorted by share_date (newest first)
    public_secrets = SharedSecret.query.filter(
        SharedSecret.public == True,
        SharedSecret.share_date <= datetime.now()
    ).order_by(SharedSecret.share_date.desc()).all()

    # Check if files exist; delete secrets with missing files
    for public_secret in public_secrets[:]:
        if public_secret.file:
            if not gcs_file_exists(public_secret.file):  # <- custom helper to check in GCS
                db.session.delete(public_secret)
                public_secrets.remove(public_secret)

    # Decrypt and prepare public secrets for display
    decrypted_secrets = []
    for public_secret in public_secrets:
        
        # Dynamically attach display_time as a string
        display_time = public_secret.share_date.strftime('%H:%M') if public_secret.share_date else ''
        public_secret.display_time = display_time

        # Decrypt the secret if it's encrypted
        if public_secret.snapshot_secret and is_encrypted(public_secret.snapshot_secret):
            public_secret.snapshot_secret = decrypt_secret(public_secret.snapshot_secret)

        if public_secret.file:
                public_secret.signed_url = url_for('main.download_file', filename=public_secret.file)

        # Append the public secret to the list
        decrypted_secrets.append(public_secret)

    # Report submission
    if request.method == "POST":
        try:
            secret_id_raw = request.form.get('secret_id')
            secret_id = int(secret_id_raw)
        except (ValueError, TypeError):
            flash('Invalid secret ID.', 'danger')
            return redirect(request.path)

        report_details = request.form.get('details', '').strip()
        secret = request.form.get('secret')
        secret_file = request.form.get('secret_file')

        if not report_details:
            flash('You must provide a reason for the report.', 'danger')
            return redirect(request.path)

        public_secret = SharedSecret.query.filter_by(id=secret_id).first()
        if not public_secret:
            flash('The secret you are reporting does not exist.', 'danger')
            return redirect(request.path)

        send_report_email(secret_id, secret, secret_file, report_details)
        flash('Report submitted successfully.', 'success')
    
    # No need for the Session timeout in this page
    session.permanent = False

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/home_content.html',
                                    public_secrets=decrypted_secrets,
                                    form=form),
            'title': 'Home - Secures Secrets'
        })
    return render_template('home.html', show_header=True, show_footer=True, public_secrets=decrypted_secrets, form=form)

@main.route('/how-it-works', methods=['GET'])
def how_works():
    # No need for the Session timeout in this page
    session.permanent = True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
                'html': render_template('partials/how_content.html'),
                'title': 'Home - Secures Secrets'
            })
    return render_template('how.html', show_header=True, show_footer=True)

    
# Registeration server @sign-up
@main.route('/register', methods=['GET', 'POST'])
@require_pricing_session()
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = RegisterForm()
    plan_id = request.args.get('plan_id')
    if not plan_id:
        flash('Please choose plan agian.', 'warning')
        return redirect(url_for('main.pricing'))
    
    if form.validate_on_submit():
        if form.confirm_password.data != form.password.data:
            session['form_data'] = {
                'username': form.username.data.lower(),
                'email': form.email.data.lower().strip(),
                'code': form.code.data,
                'phone': form.phone.data
            }
            flash("The password confirmation does not match!", "danger")
            return redirect(url_for('main.register', plan_id=plan_id))

        # Check if the user already exists
        existing_user = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
        existing_user_name = db.session.execute(db.select(User).where(User.username == form.username.data)).scalar()
        if existing_user:
            flash("You've already signed up with that email, log in instead.", "warning")
            return redirect(url_for('main.login'))
        if existing_user_name:
            session['form_data'] = {
                'email': form.email.data,
            }
            flash("This username is already in use, please choose another!", "danger")
            return redirect(url_for('main.register', plan_id=plan_id))
        
        # Store registration data in session
        new_user = User(
            email=form.email.data,
            username=form.username.data,
            password=generate_password_hash(form.password.data, method='pbkdf2:sha256', salt_length=16),
            country_code=form.code.data,
            phone=form.phone.data,
            plan_id=plan_id,
            email_token=generate_token(),
            payment_source="site"
        )
        db.session.add(new_user)
        try:
            db.session.commit()
            # Send verification email
            send_verification_email(new_user.email, new_user.username, new_user.email_token)
            # Redirect to confirmation pending page
            return redirect(url_for('main.confirmation_pending', user=new_user.id))

        except Exception as e:
            # Rollback in case of an error
            db.session.rollback()
            print(f"Error saving user: {e}")
            # Optionally, flash an error message or handle the error as needed
            flash('An error occurred during registration. Please try again.', 'danger')
            return redirect(url_for('main.register'))

    if 'form_data' in session:
        form.username.data = session['form_data'].get('username', '')
        form.email.data = session['form_data'].get('email', '')
        form.code.data = session['form_data'].get('code')
        form.phone.data = session['form_data'].get('phone')

    # No need for the Session timeout in this page
    session.permanent = True

    return render_template('register.html', form=form, current_user=current_user, show_header=False, show_footer=True)


# create_product()
    # print(get_subscription_details("I-YM3K8PW3Y4HL"))
    # subscription_details = get_subscription_details("I-YM3K8PW3Y4HL")
    # # Use `.get()` to avoid KeyError
    # billing_info = subscription_details.get('billing_info', {})

    # next_billing_time = billing_info.get('next_billing_time', 'Not Available')

    # print(f"Next Billing Time: {convert_utc_to_local(next_billing_time, 'Asia/Qatar')}")
    # get_access_token()
    # call_plans()
    # create_plan()
    # deactivate_plan('P-52H4034244582515FM6UHT7Y')
    # cancel_subscription("I-M10UXVBHYH55", "Cancel")

    
# Log in server
@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    # Get next from both GET and POST
    next_page = request.args.get('next') or request.form.get('next')

    # Prepopulate form data from session if it exists
    if 'form_data' in session:
        form.user.data = session['form_data'].get('user', '')
        session.pop('form_data')  # Remove after use
    
    if form.validate_on_submit():
        password = form.password.data
        # print(form.user.data)
        user = db.session.execute(db.select(User).where((func.lower(User.email) == form.user.data.lower().strip()) | (func.lower(User.username) == form.user.data.lower()))).scalar()
        
        if not user:
            flash("Email/ username does not exist.", "danger")
            return redirect(url_for('main.login'))
        
        elif not check_password_hash(user.password, password):
            session['form_data'] = {'user': form.user.data}  # Store entered user
            flash('Password incorrect.', "danger")
            return redirect(url_for('main.login'))
        
        else:
            if not user.is_confirmed:
                flash('Please confirm your email address before logging in.', 'warning')
                return redirect(url_for('main.confirmation_pending', user=user.id))
            login_user(user)
            
            # Update last login time
            ip_address = request.remote_addr  # This retrieves the client's IP address
    
            # Add a new entry in the LoginHistory table
            login_history = LoginHistory(user_id=user.id, login_time=convert_utc_to_local(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user.time_zone), ip_address=ip_address)
            db.session.add(login_history)
            db.session.commit()
            # No need for the Session timeout in this page
            session.permanent = False
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            
            return redirect(url_for('main.dashboard'))
    
    
    return render_template('login.html', form=form, current_user=current_user, show_header=False, show_footer=True)

# Log out server
@main.route('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.login'))

# Updating timezone for each user
@main.route('/update-timezone', methods=['POST'])
def update_timezone():
    data = request.get_json()
    
    user_id = request.args.get("user")  # Get user ID from URL parameters
    user = User.query.get(user_id)  # Retrieve user from the database

    if not user:
        return {"error": "User not found"}, 404

    time_zone = data.get("time_zone")
    if not time_zone:
        return {"error": "Time zone not provided"}, 400

    user.time_zone = time_zone
    db.session.commit()

    return {"message": "Time zone updated successfully"}

# confirmation email to change user password when he press forgot password
@main.route('/confirm-email-for-password', methods=['POST'])
def forget_password_email():
    if request.method == "POST":
        email = request.form.get("email")
        user = User.query.filter_by(email=email).first()

        if user:
            if user.reset_pswd_token:
                user.reset_pswd_token = None
                db.session.commit()
            token = generate_token()
            user.reset_pswd_token = token
            db.session.commit()
            reset_password_email(user.email, user.username, token)
            flash('An email with a password reset link has been sent to your email.', 'info')
        else:
            flash('This email is not registered.', 'danger')
        return redirect(url_for('main.login'))


# User forgot password
@main.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    form = ForgetPaswdForm()
    token = request.args.get("token")
    user = User.query.filter_by(reset_pswd_token=token).first()

    # Ensure token is valid and matches a user
    if not user:
        flash('Invalid or expired token.', 'danger')
        return redirect(url_for('main.login'))

    if form.validate_on_submit():
        new_password = form.new_password.data
        confirm_password = form.confirm_password.data
        
        # Check if passwords match
        if confirm_password != new_password:
            flash("The password confirmation does not match!", 'danger')
            return redirect(url_for('main.reset_password', token=token))

        # Update password and clear token
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=16)
        user.reset_pswd_token = None
        try:
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.session.rollback()
            print(f"Error committing changes: {e}")
            flash('Something went wrong while updating your password.', 'danger')
            return redirect(url_for('main.reset_password', token=token))

    return render_template('reset_password.html', form=form)

# Profile
@main.route('/profile', methods=['GET', 'POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def update_profile():
    secret_form = SecretForm()
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized", "message": "Your session has expired. Please log in again."}), 401  # Explicitly return 401 status for AJAX
    
    pr_form = ProfileForm(obj=current_user)
    login = LoginHistory.query.filter_by(user_id=current_user.id).all()
    last_login = LoginHistory.query.filter_by(user_id=current_user.id).order_by(LoginHistory.login_time.desc()).first()
    if pr_form.validate_on_submit():
        # Handle profile update (only phone details)
        current_user.username = pr_form.username.data
        current_user.phone = pr_form.phone.data
        current_user.country_code = pr_form.code.data
        db.session.commit()
        flash('Mobile number updated successfully!', 'success')
        return redirect(url_for('main.update_profile'))
    pr_form.code.data = current_user.country_code

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/profile_content.html',
                                    current_user=current_user,
                                    pr_form=pr_form,
                                    ps_form=ChangePasswordForm(),
                                    login_history=login,
                                    last_login=last_login,
                                    secret_form=secret_form),
            'title': 'Profile - Secures Secrets'
        })
    return render_template('profile.html', current_user=current_user, pr_form=pr_form, ps_form=ChangePasswordForm(), login_history=login, last_login=last_login, secret_form=secret_form, show_header=True, show_footer=True)

# Pagination for the login history
@main.route('/api/login-history', methods=['GET'])
@login_required
def api_login_history():
    # Get the page number from the request, default to 1
    page = request.args.get('page', 1, type=int)
    per_page = 5  # Number of records per page

    # Query the login history from the database, paginated
    login_history = LoginHistory.query.filter_by(user_id=current_user.id) \
        .order_by(LoginHistory.login_time.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    # Create a list of pages to display (max 5 pages)
    max_display_pages = 5
    total_pages = login_history.pages
    start_page = max(1, page - 2)  # show the previous 2 pages if possible
    end_page = min(total_pages, page + 2)  # show the next 2 pages if possible
    page_range = list(range(start_page, end_page + 1))

    # Serialize the login history data
    history_data = [{
        'login_time': login.login_time,
        'ip_address': login.ip_address
    } for login in login_history.items]

    return jsonify({
        'data': history_data,
        'total': login_history.total,
        'page': page,
        'pages': total_pages,
        'page_range': page_range  # Include the page range in the response
    })


# Update password
@main.route('/change-password', methods=['POST'])
@login_required
@subscription_ended()
def change_password():

    pr_form = ProfileForm(obj=current_user)
    ps_form = ChangePasswordForm(request.form)
    secret_form = SecretForm()
    login = LoginHistory.query.filter_by(user_id=current_user.id).all()
    last_login = LoginHistory.query.filter_by(user_id=current_user.id).order_by(LoginHistory.login_time.desc()).first()
    if ps_form.validate_on_submit():
        current_password = ps_form.current_password.data
        new_password = ps_form.new_password.data
        confirm_password = ps_form.confirm_password.data

        # Check if current password is correct
        if check_password_hash(current_user.password, current_password):
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            else:
                # Update password only
                current_user.password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=16)
                db.session.commit()
                flash('Password changed successfully!', 'success')
                return redirect(url_for('main.update_profile'))
        else:
            flash('Current password is incorrect.', 'danger')

    pr_form.code.data = current_user.country_code

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/profile_content.html', current_user=current_user, pr_form=pr_form, ps_form=ps_form, login_history=login, last_login=last_login, secret_form=secret_form)
    return render_template('profile.html', current_user=current_user, pr_form=pr_form, ps_form=ps_form, login_history=login, last_login=last_login, secret_form=secret_form, show_header=True, show_footer=True)

# dashboard server
@main.route('/dashboard', methods=['GET', 'POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def dashboard():
    secret_form = SecretForm()
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized", "message": "Your session has expired. Please log in again."}), 401  # Explicitly return 401 status for AJAX
    
    # cancel_subscription('I-JWXGEDPYF9XT', 'I was testing only')
    # redirect the new users to the payment page to continue using the account
    if current_user.status == "new" and current_user.payment_source == "site":
        return redirect(url_for("main.payment"))
        
    # counting secrets for each user
    secrets = Secret.query.filter_by(user_id=current_user.id).count()
    # last_login = current_user.login_history[-1] if current_user.login_history else None
    last_login = LoginHistory.query.filter_by(user_id=current_user.id).order_by(LoginHistory.login_time.desc()).first()

    # Fetch the public shared secrets and eager-load user and secret relationships
    shared_secret = db.session.execute(
        db.select(SharedSecret)
        .where(SharedSecret.public == True, 
            (SharedSecret.time_period != None) | (SharedSecret.time_to_send != None))
        .options(joinedload(SharedSecret.user), joinedload(SharedSecret.secret))
    ).scalars().all()

    current_date = datetime.now().date()
    current_time = datetime.now().time()

    # Check if the user logged in recently and update the time period or scheduled date
    for secret in shared_secret:
        # Get the most recent login date for the user
        latest_login = db.session.execute(
            db.select(LoginHistory.login_time)
            .where(LoginHistory.user_id == secret.user_id)
            .order_by(desc(LoginHistory.login_time))
            .limit(1)
        ).scalar_one_or_none()

        # Initialize date_time with None for cases when no scheduled date is set
        date_time = None

        # If a recent login exists and it's more recent than the current last_login
        if latest_login and (secret.last_login is None or latest_login > secret.last_login):
            # Update the last_login to the latest login date
            secret.last_login = latest_login

            # Handle `period` and calculate `time_period` if `period` is present
            if secret.period:
                try:
                    # Only extend if current time_period is still in the future
                    if not secret.time_period or secret.time_period > datetime.now():
                        # Calculate the new time period based on the period (e.g., days)
                        time_period = latest_login + timedelta(days=int(secret.period))
                        secret.time_period = time_period
                except ValueError:
                    # Skip this secret if `period` is invalid but do not raise an error
                    continue

        # Handle the scenario when `date_to_send` and `time_to_send` are used
        if secret.date_to_send == current_date and secret.time_to_send == current_time:
            # Combine date_to_send and time_to_send if they exist and match the current time
            date_time = datetime.combine(secret.date_to_send, secret.time_to_send)

        # Update the associated SharedSecret > when public true > share_date if available
        public_secret = SharedSecret.query.filter_by(id=secret.id).first()
        if public_secret:
            # Update share_date based on valid `time_period` or `date_time`
            if secret.time_period:
                public_secret.share_date = secret.time_period
            elif date_time:
                public_secret.share_date = date_time

    # Commit changes to the database
    db.session.commit()

    # Fetch all public shared secrets with eligible share_date, sorted by share_date (newest first)
    public_secrets = SharedSecret.query.filter(
        SharedSecret.public == True,
        SharedSecret.share_date <= datetime.now()
    ).order_by(SharedSecret.share_date.desc()).all()

    # Check if files exist; delete secrets with missing files
    for public_secret in public_secrets[:]:
        if public_secret.file:
            if not gcs_file_exists(public_secret.file):  # <- custom helper to check in GCS
                db.session.delete(public_secret)
                public_secrets.remove(public_secret)

    # Commit changes after deletion
    db.session.commit()

    # Decrypt and prepare public secrets for display
    decrypted_secrets = []
    for public_secret in public_secrets:

        # Dynamically attach display_time as a string
        display_time = public_secret.share_date.strftime('%H:%M') if public_secret.share_date else ''
        public_secret.display_time = display_time

        # Decrypt the secret if it's encrypted
        if public_secret.snapshot_secret and is_encrypted(public_secret.snapshot_secret):
            public_secret.snapshot_secret = decrypt_secret(public_secret.snapshot_secret)

        if public_secret.file:
            # Use the internal download route so Flask will decrypt the file before sending
            public_secret.signed_url = url_for('main.download_file', filename=public_secret.file)

        
        # Append the public secret to the list
        decrypted_secrets.append(public_secret)
            
    
    subscription_approval = get_subscription_details(current_user.paypal_subscription_id)
    if current_user.username != "SecuresSecrets" or current_user.payment_source == "Apple Pay" or current_user.payment_source == "Google Play":
        approval_link = "pass"
    elif subscription_approval.get("status") == "APPROVAL_PENDING":
        approval_link = next((link["href"] for link in subscription_approval.get("links", []) if link["rel"] == "resend"), None)
    else:
        approval_link = "pass"

    
    # Report submission
    if request.method == "POST":
        try:
            secret_id = int(request.form.get('secret_id'))
        except (ValueError, TypeError):
            flash(f'Invalid secret ID. {secret_id}', 'danger')
            return redirect(request.path)

        report_details = request.form.get('details', '').strip()
        secret = request.form.get('secret')
        secret_file = request.form.get('secret_file')

        if not report_details:
            flash('You must provide a reason for the report.', 'danger')
            return redirect(request.path)

        public_secret = SharedSecret.query.filter_by(id=secret_id).first()
        if not public_secret:
            flash('The secret you are reporting does not exist.', 'danger')
            return redirect(request.path)
        
        if public_secret.user and public_secret.user.username == "SecuresSecrets":
            flash("You cannot report admin's secrets.", "warning")
            return redirect(request.path)

        send_report_email(secret_id, secret, secret_file, report_details)
        flash('Report submitted successfully.', 'success')


    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/dashboard_content.html', 
                                    current_user=current_user, 
                                    public_secrets=decrypted_secrets, 
                                    secrets=secrets, 
                                    last_login=last_login.login_time, 
                                    secret_form=secret_form, 
                                    link=approval_link, 
                                    show_secrets_list=False),
            'title': 'Dashboard - Secures Secrets'
        })
    return render_template('dashboard.html', current_user=current_user, show_header=True, show_footer=True, show_secrets_list=False, public_secrets=decrypted_secrets, secrets=secrets, last_login=last_login.login_time, secret_form=secret_form, link=approval_link)

# List of all secerts for the user 
@main.route('/all-secrets', methods=['GET', 'POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def all_secrets():

    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        flash('Your session has expired. Please log in again.', 'danger')
        return redirect(url_for('main.login')), 401  # Explicitly return 401 status for AJAX

    form = SearchForm()
    share_form = ShareForm()
    secret_form = SecretForm()

    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))

    # Fetch all secrets for the user
    query = db.select(Secret).where(Secret.user_id == current_user.id)
    user_secrets = db.session.execute(query.order_by(Secret.date.desc())).scalars().all()

    if not user_secrets:
        current_user.storage_used = 0
    db.session.commit()

    # Decrypt secrets
    decrypted_secrets = decrypt_secrets(user_secrets)

    # Attach signed URLs for files
    for secret in decrypted_secrets:
        if secret.file:
            # Use internal download route
            secret.signed_url = url_for('main.download_file', filename=secret.file)
        # if secret.title:
        #     secret.title = get_unique_title(secret.title, current_user.id)

    # Fetch shared secrets for the current user
    shared_secrets = db.session.execute(
        db.select(SharedSecret)
        .where(SharedSecret.user_id == current_user.id)  # assuming shared via email
        .order_by(SharedSecret.date_to_send.desc())  # or any date field you prefer
    ).scalars().all()

    # Decrypt shared and public secrets after fetching them
    for shared in shared_secrets:
        # Check if public_secret is encrypted and decrypt it if necessary
        if shared.snapshot_secret and is_encrypted(shared.snapshot_secret):
            shared.snapshot_secret = decrypt_secret(shared.snapshot_secret)
        # Attach signed URL for the file in the SharedSecret record itself
        if shared.file:
            shared.signed_url = url_for('main.download_file', filename=shared.file)
        # Optional: also attach signed URL for the original secret's file (if needed)
        elif shared.secret and shared.secret.file:
            shared.secret.signed_url = url_for('main.download_file', filename=shared.secret.file)

    for shared in shared_secrets:
        if shared.date_to_send and shared.time_to_send:
            combined = datetime.combine(shared.date_to_send, shared.time_to_send)
            shared.status = 'shared' if combined <= datetime.now() else 'pending'
        else:
            shared.status = 'shared' if shared.received else 'pending'
        
    for shared in shared_secrets:
        if shared.share_date:
            shared.share_date_local = convert_utc_to_local(shared.share_date, current_user.time_zone)
        elif shared.date_to_send and shared.time_to_send:
            combined = datetime.combine(shared.date_to_send, shared.time_to_send)
            shared.share_date_local = convert_utc_to_local(combined, current_user.time_zone)
        elif shared.time_period:
            shared.share_date_local = convert_utc_to_local(shared.time_period, current_user.time_zone)
        else:
            shared.share_date_local = None
    

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/all_secrets_content.html',
                                    user_secrets=decrypted_secrets,
                                    shared_secrets=shared_secrets,
                                    current_user=current_user,
                                    share_form=share_form,
                                    form=form,
                                    secret_form=secret_form),
            'title': 'All Secrets - Secures Secrets'
        })
    return render_template('all_secrets.html', user_secrets=decrypted_secrets, shared_secrets=shared_secrets, current_user=current_user, form=form, share_form=share_form, secret_form=secret_form, show_header=True, show_footer=True, show_secrets_list=True)

# Search and Filter
@main.route('/search-secrets', methods=['POST'])
@login_required
def search_secrets():
    form = SearchForm()

    if form.validate_on_submit():
        search_term = f"%{form.search.data}%" if form.search.data else None
        query = db.select(Secret).where(Secret.user_id == current_user.id)

        if search_term:
            query = query.where(Secret.title.ilike(search_term))

        if form.date_filter.data:
            query = query.order_by(Secret.date.desc() if form.date_filter.data == "latest" else Secret.date.asc())
        if form.alpha_filter.data:
            query = query.order_by(Secret.title.asc() if form.alpha_filter.data == "A-Z" else Secret.title.desc())

        user_secrets = db.session.execute(query).scalars().all()
        decrypted_secrets = decrypt_secrets(user_secrets)

        # Render only the secrets list as HTML
        rendered_secrets = render_template(
            'partials/secrets_list.html',  # A partial for the secrets list only
            user_secrets=decrypted_secrets
        )
        return jsonify({"html": rendered_secrets}), 200

    # Handle invalid form submission
    return jsonify({"error": "Invalid form submission"}), 400

# New secret popup
@main.route('/add-secret', methods=['POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def add_secret():
    form = SecretForm()

    if not form.validate_on_submit():
        return jsonify(success=False, error="Form validation failed."), 400

    try:
        # Secret limit
        secret_limit = 10
        user_secrets = db.session.execute(
            db.select(Secret).where(Secret.user_id == current_user.id)
        ).scalars().all()
        if current_user.plan.plan == 'Basic' and len(user_secrets) >= secret_limit:
            return jsonify(success=False, error=f"You reached the max limit of {secret_limit} secrets for Basic plan."), 403

        # Secret text or file must exist
        uploaded_filename = request.form.get("uploadedFileName")
        if not form.secret.data.strip() and not uploaded_filename:
            return jsonify(success=False, error="Provide a secret or upload a file."), 400

        # Encrypt secret text and calculate size
        encrypted_secret = encrypt_secret(form.secret.data)
        secret_size = len(encrypted_secret.encode('utf-8'))

        # Calculate metadata size
        unique_title = get_unique_title(form.title.data.strip(), current_user.id)
        metadata = {
            "title": unique_title,
            "date": date.today().strftime("%Y-%m-%d"),
            "file": uploaded_filename or "",
            "user_id": str(current_user.id)
        }
        metadata_size = len(json.dumps(metadata).encode('utf-8')) + 100  # Add DB overhead estimate

        # Verify file size server-side
        file_size = get_gcs_file_size(uploaded_filename) if uploaded_filename else 0

        # Check storage limit
        total_size = secret_size + metadata_size + file_size
        if current_user.storage_used + total_size > current_user.plan.storage_limit:
            return jsonify(success=False, error="Adding this secret exceeds your plan's storage."), 403

        # Update storage usage
        current_user.storage_used += total_size
        new_secret = Secret(
            title=unique_title,
            secret=encrypted_secret,
            file=uploaded_filename,
            date=date.today().strftime("%Y-%m-%d"),
            user_id=current_user.id,
            secret_size=total_size
        )
        db.session.add(new_secret)
        db.session.commit()

        return jsonify(
            success=True,
            title=new_secret.title,
            date=new_secret.date,
            totalSecrets=Secret.query.filter_by(user_id=current_user.id).count(),
            plan={'plan': current_user.plan.plan},
            storageInfo={
                "used": current_user.storage_used,
                "total": current_user.plan.storage_limit
            },
            flash_message="New secret added successfully."
        ), 200

    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="Error saving your secret. Please try again."), 500


@main.route('/upload', methods=['POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def upload_file():
    if 'file' not in request.files:
        return jsonify(error='No file part in the request'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(error='No selected file'), 400

    if not current_user.is_authenticated:
        return jsonify(error='User not authenticated'), 401

    try:
        # ✅ Get file size safely
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size == 0:
            return jsonify(error="Empty file uploaded"), 400

        if current_user.storage_used + file_size > current_user.plan.storage_limit:
            return jsonify(error='Exceeds storage limit'), 403

        original_filename = secure_filename(file.filename)
        unique_prefix = uuid.uuid4().hex
        filename = f"{unique_prefix}_{original_filename}"

        # Log memory usage before upload
        print(f"Pre-upload memory: {psutil.virtual_memory().percent}%")

        # ✅ Upload directly from stream (no full buffering)
        print(f"Uploading {filename}, size: {file_size} bytes")
        upload_to_gcs(file.stream, filename)

        # Log memory usage after upload
        print(f"Post-upload memory: {psutil.virtual_memory().percent}%")

        # Update storage usage
        # current_user.storage_used += file_size
        db.session.commit()

        return jsonify(message='File successfully uploaded', filename=filename), 200

    except Exception as e:
        print(f"[❌ Upload Error] {str(e)}")
        return jsonify(error=str(e)), 500
    
# Example endpoint to show usage
@main.route('/storage-usage', methods=['GET'])
def storage_usage():
    secrets = db.session.execute(
        db.select(Secret).where(Secret.user_id == current_user.id)
    ).scalars().all()

    text_size = sum(len(s.secret.encode('utf-8')) for s in secrets if s.secret)
    file_size = sum(get_gcs_file_size(s.file) for s in secrets if s.file)

    metadata_size = sum(len(json.dumps({
        "title": s.title,
        "date": s.date.strftime("%Y-%m-%d") if s.date else None,  # ✅ convert date to string
        "file": s.file or ""
    }).encode('utf-8')) for s in secrets)

    return jsonify({
        "text_size_bytes": text_size,
        "file_size_bytes": file_size,
        "metadata_size_bytes": metadata_size,
        "total_size_bytes": text_size + file_size + metadata_size
    })


# Route to fetch the user's current storage usage and limit, requiring login.
@main.route('/get-storage-info', methods=['GET'])
@login_required
def get_storage_info():
    try:
        secrets = db.session.execute(
            db.select(Secret).where(Secret.user_id == current_user.id)
        ).scalars().all()
        text_size = sum(len(s.secret.encode('utf-8')) for s in secrets if s.secret)
        file_size = sum(get_gcs_file_size(s.file) for s in secrets if s.file)
        metadata_size = sum(len(json.dumps({
            "title": s.title,
            "date": s.date.strftime("%Y-%m-%d") if s.date else None,  # ✅ convert date to string,
            "file": s.file or ""
        }).encode('utf-8')) + 100 for s in secrets)
        return jsonify({
            'used': current_user.storage_used,
            'total': current_user.plan.storage_limit,
            'breakdown': {
                'text': text_size,
                'files': file_size,
                'metadata': metadata_size
            }
        })
    except Exception as e:
        print(f"Error fetching storage info: {e}")
        return jsonify({'error': str(e)}), 500

# Sharing secret server
@main.route('/share', methods=['POST'])
@subscription_ended_flag
@storage_exceeded_flag()
def share():
    form = ShareForm()

    # Default variable initialization
    sharing_type = None
    email, public, phone, token, time_period, date, time, last_login, date_time_combined, first_name, last_name = None, False, None, None, None, None, None, None, None, None, None

    if form.validate_on_submit():
        # print("Form submission data:", form.data)
        # Determine sharing type
        login_emails = [email.strip() for email in form.email_login.data.split(',') if email.strip()]
        scheduled_emails = [email.strip() for email in form.email_scheduled.data.split(',') if email.strip()]
        login_phones = [p.strip() for p in form.phone_login.data.split(',') if p.strip()]
        scheduled_phones = [p.strip() for p in form.phone_scheduled.data.split(',') if p.strip()]

        first_name = form.first_name.data if form.first_name.data else None
        last_name = form.last_name.data if form.last_name.data else None

        if form.date_period.data:
            sharing_type = "last_login"
            if not login_emails and not login_phones and not form.public_login.data:
                return jsonify({"success": False, "message": "Email or Public must be selected for Last Login Check"}), 400

            email = login_emails
            phone = login_phones
            public = form.public_login.data
            date_period = form.date_period.data

            # Get the last login time
            user_last_login = (
                LoginHistory.query
                .filter_by(user_id=current_user.id)
                .order_by(LoginHistory.login_time.desc())
                .first()
            )
            last_login = user_last_login.login_time if user_last_login else None

            if not last_login:
                return jsonify({"success": False, "message": "Last login time not found"}), 400

            # Calculate the time period
            if date_period:
                time_period = (last_login + timedelta(days=int(date_period))).replace(second=0, microsecond=0)
                message = f"Your secret will be shared after {date_period} day/s from the last login"
        elif form.date.data and form.time.data:
            sharing_type = "scheduled"
            if not scheduled_emails and not scheduled_phones and not form.public_scheduled.data:
                return jsonify({"success": False, "message": "Email or Public must be selected for Scheduled Sharing"}), 400

            date = form.date.data
            time = form.time.data
            if isinstance(time, str):  # Convert string time to time object
                time = datetime.strptime(time, "%H:%M").time()

            email = scheduled_emails
            phone = scheduled_phones
            public = form.public_scheduled.data
            
            # Ensure 'time' is a datetime.time object before combining
            if isinstance(time, datetime):
                time = time.time()

            # Convert the date/ time to user current UTC and split them to save them in DB
            date_time_combined = convert_local_to_utc(datetime.combine(date, time), current_user.time_zone)
            date_str, time_str = str(date_time_combined).split()
            share_datetime_local = convert_utc_to_local(date_time_combined, current_user.time_zone)
            message = f"Your secret is scheduled at {share_datetime_local}"
        else:
            return jsonify({"success": False, "message": "Invalid sharing type or missing fields!"}), 400

        # Create and save the shared secret
        try:
            if email or phone:
                token = generate_token()

            secret = Secret.query.filter_by(id=request.args.get("secret_id")).first()

            if not secret:
                return jsonify(success=False, error="Secret not found"), 404

            # Store a snapshot of the secret in SharedSecret
            new_shared_secret = SharedSecret(
                user_id=current_user.id,
                secret_id=secret.id,
                email=email,
                phone=phone,
                username=current_user.username,
                public=public,
                title=secret.title,
                snapshot_secret=secret.secret,
                file=secret.file,
                share_date=(
                        time_period if sharing_type == "last_login"
                        else date_time_combined if sharing_type == "scheduled"
                        else None
                    ),
                last_login=last_login if sharing_type == "last_login" else None,
                period=date_period if sharing_type == "last_login" else None,
                time_period=time_period if sharing_type == "last_login" else None,
                public_delete_confirm=form.public_confirm_deletion.data if sharing_type == "last_login" else False,
                token=token,
                date_to_send=date_str if sharing_type == "scheduled" else None,
                time_to_send=time_str if sharing_type == "scheduled" else None,
                received=False,
                schedule_delete_confirm=form.scheduled_confirm_deletion.data if sharing_type == "scheduled" else False,
                first_name=first_name,
                last_name=last_name,
            )
            db.session.add(new_shared_secret)
            db.session.commit()

            flash(message, "success")
            return jsonify(success=True, message=message), 200

        except Exception as e:
            db.session.rollback()
            error_message = str(e)
            print(f"Error occurred: {error_message}")
            flash(f"Error occurred: {error_message}")
            return jsonify(
                success=False,
                message="An error occurred while sharing the secret",
                error=error_message
            ), 500


    # Log validation errors
    print("Validation errors:", form.errors)
    flash("Please fix the errors in the form", "danger")
    errors = {field: error for field, error in form.errors.items()}
    return jsonify(success=False, errors=errors), 400


# The link where that person will read the >>SHARED_SECRET<<
@main.route('/only-for-you/<token>', methods=['GET'])
def only_for_you(token):
    now = datetime.now()
    shared_secret = SharedSecret.query.filter_by(token=token).first()
    if shared_secret:
        # Mark the secret as received and set the deletion time
        if not shared_secret.received:
            shared_secret.received = True
            shared_secret.received_time = now
            if shared_secret.schedule_delete_confirm:
                shared_secret.delete_at = now + timedelta(hours=1)
            db.session.commit()
        
        # Check if delete_at is not None and if the current time is past the delete time
        if shared_secret.delete_at and now > shared_secret.delete_at:
            # Delete the secret after 1 hour of opening
            db.session.delete(shared_secret)
            db.session.commit()
            return "The link has expired.", 404
        
        # Calculate remaining time in seconds
        remaining_time = (shared_secret.delete_at - now).total_seconds() if shared_secret.delete_at else 0
        if remaining_time < 0:
            remaining_time = 0

        # Decrypting the secret
        decrypted_secret_content = decrypt_secret(shared_secret.snapshot_secret)
        print(decrypt_secret)

         # ✅ Handle attached encrypted file (same logic as in published secrets)
        file_url = None
        if shared_secret.file:
            # Use the same download route that handles decryption
            file_url = {
                'download': url_for('main.download_file', filename=shared_secret.file, token=shared_secret.token),
                'preview': url_for('main.download_file', filename=shared_secret.file, token=shared_secret.token, preview='true'),
                'filename': shared_secret.file  # Pass the filename for extension checking
            }

        return render_template(
            'display_secret.html',
            decrypted_secret=decrypted_secret_content,
            secret=shared_secret,
            remaining_time=int(remaining_time),
            file_url=file_url,
        )
    else:
        return "Invalid or expired link", 404

# # Toggle pinned
# @main.route('/toggle_pin/<int:secret_id>', methods=['POST'])
# def toggle_pin(secret_id):
#     secret = db.get_or_404(Secret, secret_id)
#     secret.pinned = not secret.pinned
#     db.session.commit()
#     return jsonify(success=True)

# # Toggle starred
# @main.route('/toggle_star/<int:secret_id>', methods=['POST'])
# def toggle_star(secret_id):
#     secret = db.get_or_404(Secret, secret_id)
#     secret.starred = not secret.starred
#     db.session.commit()
#     return jsonify(success=True)    

# Deleting a secret
@main.route('/delete/<int:sec_id>', methods=['GET', 'DELETE'])
@login_required
def delete_secret(sec_id):
    
    try:
        secret = db.get_or_404(Secret, sec_id)

        # ✅ Check if this secret is linked to any shared secrets
        shared_links = SharedSecret.query.filter_by(secret_id=secret.id).all()
        if shared_links:
            print(f"Secret {secret.id} is shared — will not delete shared records.")

        # Calculate the size of the secret's text (in bytes)
        text_size = len(secret.secret.encode('utf-8'))  # Convert the string to bytes and measure its length

        # Calculate metadata size (same logic as add_secret)
        metadata = {
            "title": secret.title,
            "date": secret.date.isoformat() if secret.date else "",
            "file": secret.file or "",
            "user_id": str(secret.user_id)
        }
        metadata_size = len(json.dumps(metadata).encode('utf-8')) + 100  # overhead


        # Get the file size if the secret has a file
        file_size = 0
        if secret.file:
            # Check if the file is still referenced in SharedSecret
            is_shared_publicly = SharedSecret.query.filter_by(file=secret.file).first()
            if not is_shared_publicly:
                # ✅ Delete from GCS
                success, file_size = delete_from_gcs(secret.file)
                if not success:
                    file_size = 0

        # Update the user's storage used
        total_size = text_size + metadata_size + file_size
        current_user.storage_used = max(0, current_user.storage_used - total_size)  # Prevent negative storage

        # Commit the changes to update storage
        db.session.commit()

        # Delete the secret from the database
        db.session.delete(secret)
        db.session.commit()
        flash('Secret has been deleted successfully.', 'success')
        return redirect(url_for('main.all_secrets'))

    except IntegrityError as e:
        db.session.rollback()
        print(e)
        # Handle error (e.g., notify the user, log the error, etc.)
        return "An error occurred while deleting the secret.", 500

# deleting shared secret by user
@main.route('/delete-shared-secret/<int:secret_id>', methods=['GET', 'DELETE'])
@login_required
def delete_shared_secret(secret_id):

    if not current_user.username:
        flash('You are not authorized to delete the secret', 'danger')
        return redirect(url_for('main.dashboard'))
    else:
        secret = SharedSecret.query.get(secret_id)
        db.session.delete(secret)
        db.session.commit()
        flash('Secret has been deleted successfully.', 'success')
        return redirect(url_for('main.all_secrets'))
    

# Delete account
@main.route('/delete-account/<int:user_id>', methods=['GET', 'POST'])
@login_required
def delete_account(user_id):
    user = User.query.get(user_id)
    if user is None or user.id != current_user.id:
        flash("User not found or unauthorized action.", "danger")
        return redirect(url_for('main.update_profile'))

    # Generate secure token
    token = generate_delete_token(user.id)
    verification_link = url_for('main.verify_delete_account', token=token, _external=True)

    # Send verification email
    try:
        send_delete_account_email(current_user, verification_link)
        flash("A verification email has been sent. Please check your inbox to confirm deletion.", "info")
    except Exception as e:
        print(f"Error sending email: {e}")
        flash("Could not send verification email. Please try again later.", "danger")

    return redirect(url_for('main.update_profile'))

@main.route('/verify-delete-account/<token>', methods=['GET'])
# @login_required
def verify_delete_account(token):
    user_id = confirm_delete_token(token)
    if not user_id:
        flash("Invalid or expired deletion link.", "danger")
        return redirect(url_for('main.login'))

    user = User.query.get(user_id)
    if user is None:
        flash("User not found or unauthorized action.", "danger")
        return redirect(url_for('main.login'))

    try:
        # Cancel subscription if exists
        if user.paypal_subscription_id:
            cancel_subscription(user.paypal_subscription_id, "Deleting my account.")
            time.sleep(5)  # wait until subscription is canceled
        
        # Loop through user's secrets
        for secret in user.secrets:
            if secret.file:
                # Check if still shared
                is_shared_publicly = SharedSecret.query.filter_by(file=secret.file).first()
                if not is_shared_publicly:
                    # Delete file from GCS
                    delete_from_gcs(secret.file)

        # Delete account
        db.session.delete(user)
        db.session.commit()

        # Log out after deletion
        logout_user()
        flash("Your account has been permanently deleted. We're sad to see you go.", "success")
        return redirect(url_for('main.login'))

    except SQLAlchemyError as e:
        db.session.rollback()
        flash("An error occurred while deleting your account. Please try again.", "danger")
        print(e)
        return redirect(url_for('main.login'))
    
# Admin can delete published secrets
@main.route('/delete-pubsecret/<int:pb_secret_id>', methods=['GET', 'DELETE'])
@login_required
def delete_published_secret(pb_secret_id):

    if current_user.username != "SecuresSecrets":
        flash('You are not authorized to delete the secret', 'danger')
        return redirect(url_for('main.dashboard'))
    else:
        secret = SharedSecret.query.get(pb_secret_id)
        db.session.delete(secret)
        db.session.commit()
        flash('Secret has been deleted successfully.', 'success')
        return redirect(url_for('main.dashboard'))


# Editing secret
@main.route('/update-secret/<int:secret_id>', methods=['POST'])
@login_required
@subscription_ended_flag
@storage_exceeded_flag()
def update_secret(secret_id):
    form = SecretForm()
    secret = db.get_or_404(Secret, secret_id)

    if not form.validate_on_submit():
        return jsonify(success=False, error="Form validation failed."), 400

    try:
        # Encrypt new secret text
        encrypted_secret = encrypt_secret(form.secret.data.strip())

        # --- Calculate OLD sizes ---
        old_text_size = len(secret.secret.encode('utf-8'))
        old_metadata = {
            "title": secret.title,
            "date": secret.date.isoformat() if secret.date else "",
            "file": secret.file or "",
            "user_id": str(secret.user_id)
        }
        old_metadata_size = len(json.dumps(old_metadata).encode('utf-8')) + 100
        old_file_size = get_gcs_file_size(secret.file) if secret.file else 0
        old_total_size = old_text_size + old_metadata_size + old_file_size

        # --- Handle file update ---
        new_file_size = 0
        old_file_size_to_subtract = 0
        filename = secret.file

        if form.file.data:
            file = form.file.data
            original_filename = secure_filename(file.filename)

            # Generate new unique filename (keep extension)
            unique_prefix = uuid.uuid4().hex
            new_filename = f"{unique_prefix}_{original_filename}"

            # Calculate new file size
            file.seek(0, os.SEEK_END)
            new_file_size = file.tell()
            file.seek(0)

            # Upload new file to GCS
            upload_to_gcs(file, new_filename)

            # Delete old file from GCS (if exists and not used elsewhere)
            if secret.file and gcs_file_exists(secret.file):
                old_blob = storage_client.bucket(GCS_BUCKET).blob(secret.file)
                old_file_size_to_subtract = old_blob.size or 0
                old_blob.delete()

            # Replace filename with the new one
            filename = new_filename

        # --- Calculate NEW sizes ---
        new_text_size = len(encrypted_secret.encode('utf-8'))
        new_metadata = {
            "title": form.title.data.strip(),
            "date": secret.date.isoformat() if secret.date else "",
            "file": filename or "",
            "user_id": str(current_user.id)
        }
        new_metadata_size = len(json.dumps(new_metadata).encode('utf-8')) + 100
        new_file_size = get_gcs_file_size(filename) if filename else new_file_size
        new_total_size = new_text_size + new_metadata_size + new_file_size

        # --- Calculate difference and check storage ---
        storage_diff = new_total_size - old_total_size
        if current_user.storage_used + storage_diff > current_user.plan.storage_limit:
            return jsonify(success=False, error="Exceeds storage limit."), 403

        # Update user storage usage
        current_user.storage_used += storage_diff

        # --- Update secret fields ---
        secret.title = form.title.data.strip()
        secret.secret = encrypted_secret
        secret.file = filename
        secret.date = date.today().strftime("%Y-%m-%d")
        # ✅ Update secret size
        secret.secret_size = new_total_size

        # --- Update any shared entries ---
        shared_entries = SharedSecret.query.filter_by(secret_id=secret.id).all()
        for shared in shared_entries:
            shared.title = secret.title
            shared.snapshot_secret = secret.secret
            shared.file = secret.file

        # Commit all changes
        db.session.commit()

        decrypted_secret = decrypt_secret(secret.secret)

        return jsonify(
            success=True,
            flash_message="Secret updated successfully!",
            secret={
                "id": secret.id,
                "secret": decrypted_secret,
                "file": secret.file,
                "date": secret.date.strftime("%Y-%m-%d %H:%M:%S"),
                "file_preview": secret.file.lower().endswith(
                    ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mov')
                )
            },
        ), 200

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=str(e)), 500


# Pricing page
@main.route('/pricing')
def pricing():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    session['from_pricing'] = True

    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))
    
    plans = db.session.execute(db.select(Plan).order_by(Plan.id)).scalars().all()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/pricing_content.html',
                                    plans=plans),
            'title': 'Pricing - Secures Secrets'
        })
    
    return render_template('pricing.html', current_user=current_user, plans=plans, show_header=True, show_footer=True)


@main.route('/charge')
def payment():
    if current_user.is_authenticated:
        user = current_user
    else:
        token = request.args.get("token")
        if not token:
            return jsonify({"error": "Unauthorized"}), 401

        try:
            decoded = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user = User.query.get(decoded['user_id'])

            if not user:
                return jsonify({"error": "User not found"}), 404

        except Exception as e:
            return jsonify({"error": "Invalid or expired token"}), 401
        
    
    currency = user.plan.currency
    amount = user.plan.price
    client_id = os.environ.get("PAYPAL_LIVE_CLIENT_ID")
    paypal_plan_id = json.loads(user.plan.paypal_plan_id)[0]

    return render_template("card_details.html", show_header=False, show_footer=False,
                           client_id=client_id, paypal_plan_id=paypal_plan_id, currency=currency, amount=amount)


@main.route('/create-paypal-order', methods=['POST'])
def create_paypal_order():
    try:
        data = request.get_json()
        plan_id = data.get('plan_id')
        amount = data.get('amount')
        currency = data.get('currency')

        # Configure PayPal SDK
        paypalrestsdk.configure({
            'mode': 'sandbox',  # Change to 'live' for production
            'client_id': os.environ.get('PAYPAL_LIVE_CLIENT_ID'),
            'client_secret': os.environ.get('PAYPAL_LIVE_CLIENT_SECRET')
        })

        # Create PayPal order
        order = paypalrestsdk.Order({
            'intent': 'CAPTURE',
            'purchase_units': [{
                'amount': {
                    'currency_code': currency,
                    'value': amount
                },
                'description': 'Subscription payment'
            }],
            'application_context': {
                'brand_name': 'Your App Name',  # Replace with your app name
                'landing_page': 'NO_PREFERENCE',
                'user_action': 'PAY_NOW'
            }
        })

        if order.create():
            print(f"Created PayPal order: {order.id}")  # Debug
            return jsonify({'orderId': order.id})
        else:
            print(f"Order creation failed: {order.error}")  # Debug
            return jsonify({'error': 'Failed to create PayPal order', 'details': order.error}), 500
    except Exception as e:
        print(f"Error creating PayPal order: {str(e)}")  # Debug
        return jsonify({'error': 'Server error creating PayPal order', 'details': str(e)}), 500


@main.route('/process-subscription', methods=['POST'])
def process_subscription():
    # Parse the incoming JSON data
    data = request.get_json()

    subscription_id = data.get('subscription_id')
    user_id = data.get('user_id')

    if not subscription_id or not user_id:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    try:
        subscription_data = get_subscription_details(subscription_id)
        print("Full Subscription Data:", subscription_data)  # Log response for debugging

        # Extract relevant details
        status = subscription_data.get("status", "UNKNOWN")
        # When the subscription started
        start_time = convert_utc_to_local(subscription_data.get("start_time"), user.time_zone)  # Convert the date to user current date
        billing_info = subscription_data.get("billing_info", {})
        subscriber = subscription_data.get("subscriber", {})

        # Get Trial End Date
        trial_end = None
        next_billing_date = None
        failed_payments = billing_info.get("failed_payments_count", 0)

        if "cycle_executions" in billing_info:
            for cycle in billing_info["cycle_executions"]:
                if cycle["sequence"] == 1 and cycle["tenure_type"] == "TRIAL":
                    trial_end = billing_info.get("next_billing_time")
                elif (cycle["sequence"] == 1 or cycle["sequence"] == 2) and cycle["tenure_type"] == "REGULAR":
                    next_billing_date = billing_info.get("next_billing_time")

        # Update User Subscription in DB
        user.paypal_subscription_id = subscription_id
        user.paypal_payer_id = subscriber.get("payer_id")
        user.subscription_status = status
        user.trial_start_date = start_time  # Subscription start = trial start
        user.trial_end_date = convert_utc_to_local(trial_end, user.time_zone)
        user.subscription_start_date = start_time
        user.next_billing_date = convert_utc_to_local(next_billing_date, user.time_zone)  # Next billing date
        user.fialed_payments = failed_payments
        user.updated_at = convert_utc_to_local(datetime.now(), user.time_zone)
        user.payment_source="PayPal"
        user.status = None

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Subscription processed",
            "subscription_status": status,
            "trial_end_date": convert_utc_to_local(trial_end, user.time_zone),
            "next_billing_date": next_billing_date
        }), 200

    except requests.exceptions.RequestException as e:
        print("Error fetching subscription details:", e)
        return jsonify({"status": "error", "message": "Failed to retrieve PayPal subscription details"}), 500

# Confirm email
@main.route('/confirm/<token>')
def confirm_email(token):
    user = User.query.filter_by(email_token=token).first()
    if not user:
        return "Invalid or expired link", 404
    if user.is_confirmed:
        flash('Your account is already confirmed.', 'info')
    else:
        user.is_confirmed = True
        user.email_token = None  # Remove the token after confirmation
        user.status = 'new'
        # # Save subscription details
        # if not user.trial_end_date or user.trial_end_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        #     user.trial_start_date = datetime.now(timezone.utc)
        #     user.trial_end_date = datetime.now(timezone.utc) + timedelta(days=13)

        db.session.commit()
        logout_user()
        flash('Your email has been verified, login now', 'success')

    return redirect(url_for('main.login'))

# Notify registerer to check email for verification
@main.route('/confirmation-pending')
def confirmation_pending():
    user_id = request.args.get('user')
    user = User.query.filter_by(id=user_id).first()
    if user:
        user.verification_sent = True
        db.session.commit()
    return render_template('confirmation_pending.html', user=user.id)


# In case the user lost the time of the verification
@main.route('/resend-verification')
def resend_verification():
    user_id = request.args.get('user')
    is_user = User.query.filter_by(id=user_id).first()
    # Logic to resend the verification email
    if is_user and not is_user.is_confirmed:
        token = generate_token()
        is_user.email_token = token
        db.session.commit()
        send_verification_email(is_user.email, is_user.username, token)
        flash('A new verification email has been sent.', 'info')
    else:
        flash('Your account is already confirmed or you are not logged in.', 'warning')
    return redirect(url_for('main.confirmation_pending', user=is_user.id))

# Billing page
@main.route('/billing', methods=['GET'])
@login_required
@storage_exceeded_flag()
def billing():
    secret_form = SecretForm()
    form = PlanUpgradeForm()
    user = User.query.get(current_user.id)
    history_payment = Payment.query.filter_by(user_id=user.id).order_by(Payment.payment_date.desc()).all()
    plans = Plan.query.order_by(Plan.price).all()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'html': render_template('partials/billing_content.html', user=user, payments=history_payment, form=form, plans=plans, secret_form=secret_form),
            'title': 'Billing - Secure Secrets'
        })
    return render_template('billing.html', user=user, payments=history_payment, form=form, plans=plans, secret_form=secret_form, show_header=True, show_footer=True, current_user=current_user)

# Upgrade/Downgrade plan
@main.route('/change-plan', methods=['POST'])
@login_required
def change_plan():
    form = PlanUpgradeForm()
    if not form.validate_on_submit():
        flash("Invalid form submission.", "danger")
        return redirect(url_for('main.billing'))

    plan_id = form.plan_id.data
    if not plan_id:
        flash("Please select a valid plan.", "danger")
        return redirect(url_for('main.billing'))

    plan = db.get_or_404(Plan, plan_id)
    if plan.id == current_user.plan_id:
        flash("You are already on this plan.", "warning")
        return redirect(url_for('main.billing'))

    try:
        plan_ids = json.loads(plan.paypal_plan_id)
    except json.JSONDecodeError:
        flash("Error parsing PayPal plan IDs.", "danger")
        return redirect(url_for('main.billing'))

    if len(plan_ids) <= 1:
        flash("Invalid PayPal plan list for this plan.", "danger")
        return redirect(url_for('main.billing'))

    new_plan_id = plan_ids[1]  # Assuming second ID is the target plan
    user_subscription_id = current_user.paypal_subscription_id
    if not user_subscription_id:
        flash("User has no active PayPal subscription.", "danger")
        return redirect(url_for('main.billing'))

    updated_subscription = change_subscription_plan(user_subscription_id, new_plan_id)
    if updated_subscription:
        current_user.plan_id = plan_id
        current_user.next_billing_date = updated_subscription.get('billing_info', {}).get('next_billing_time')
        db.session.commit()
        flash("Your subscription plan has been updated successfully!", "success")
    else:
        flash("Failed to update subscription plan. Please try again.", "danger")

    return redirect(url_for('main.billing'))

@main.route('/paypal-approved')
def paypal_approval():
    new_subscription_id = session.get('pending_subscription_id')
    old_subscription_id = session.get('old_subscription_id')

    if not new_subscription_id:
        flash("No pending subscription found.", "danger")
        return redirect(url_for('main.billing'))

    # Update user subscription in the database
    current_user.paypal_subscription_id = new_subscription_id
    db.session.commit()

    time.sleep(5)  # Small delay before checking status

    # Verify if new subscription is active
    subscription_status = get_subscription_details(new_subscription_id)
    if subscription_status == "ACTIVE":
        if old_subscription_id:
            cancel_subscription(old_subscription_id, "User changed plan")
            print("Old subscription canceled successfully.")

        session.pop('pending_subscription_id', None)
        session.pop('old_subscription_id', None)

        flash("Your subscription has been updated successfully!", "success")
    else:
        flash("Subscription approval failed or was not completed.", "danger")

    return redirect(url_for('main.dashboard'))


# Webhook to check the results of the users subscription
@main.route("/webhook", methods=["POST"])
@csrf.exempt
def paypal_webhook():
    """Handles PayPal webhook events related to user subscriptions and payments."""
    print("Webhook route hit")
    print(f"Exempt views: {csrf._exempt_views}")
    try:
        if not verify_paypal_webhook(request.json, request.headers):
            return jsonify({"error": "Invalid webhook signature"}), 400

        data = request.get_json()
        print(f"Received PayPal webhook event: {data}")  # Or logging.info
        event_type = data.get('event_type')

        event_handlers = {
            "PAYMENT.SALE.COMPLETED": handle_payment_success,
            "BILLING.SUBSCRIPTION.CREATED": handle_subscription_created,
            "BILLING.SUBSCRIPTION.ACTIVATED": handle_subscription_activated,
            "BILLING.SUBSCRIPTION.CANCELLED": handle_subscription_canceled,
            "BILLING.SUBSCRIPTION.SUSPENDED": handle_subscription_suspended,
            "BILLING.SUBSCRIPTION.UPDATED": handle_subscription_updated,
            "PAYMENT.SALE.DENIED": handle_payment_failed,
        }

        if event_type in event_handlers:
            event_handlers[event_type](data)
        else:
            print(f"Unhandled event type: {event_type}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"Webhook handling error: {str(e)}")
        return jsonify({"error": "Webhook processing failed"}), 400

# Files where be downloaded
@main.route('/downloads/<filename>')
def download_file(filename):
    try:
        # Allow Twilio access
        if request.args.get("twilio") == "true":
            return _serve_file(filename, as_attachment=True)
        
        # Check if the request is for a preview
        is_preview = request.args.get('preview', 'false').lower() == 'true'

        # ✅ Step 1: check if file is public
        public_secret = SharedSecret.query.filter_by(file=filename, public=True).first()
        if public_secret:
            return _serve_file(filename, as_attachment=not is_preview)
        
        # ✅ Step 2: check if token in path (optional: allow ?token= or header)
        token = request.args.get('token') or request.view_args.get('token')
        if token:
            secret_link = SharedSecret.query.filter_by(file=filename, token=token).first()
            if secret_link:
                return _serve_file(filename, as_attachment=not is_preview)

        # ✅ Step 3: if not public, require login
        if not current_user.is_authenticated:
            return abort(403, description="Login required.")

        # ✅ Step 4: check ownership or private sharing
        owned_secret = Secret.query.filter_by(file=filename, user_id=current_user.id).first()
        shared_secret = SharedSecret.query.join(Secret).filter(
            Secret.file == filename,
            SharedSecret.email == current_user.email
        ).first()

        if not owned_secret and not shared_secret:
            return abort(403, description="You don't have permission to access this file.")

        # ✅ Step 5: serve file
        return _serve_file(filename, as_attachment=not is_preview)

    except Exception as e:
        print("Download error:", str(e))
        return abort(500)


@main.route('/terms-of-services')
def terms():

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    return render_template('terms.html', secret_form=secret_form, show_header=True, show_footer=True)

@main.route('/terms-of-use')
def terms_use():

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    return render_template('terms_use.html', secret_form=secret_form, show_header=True, show_footer=True)

@main.route('/about-us')
def about():

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
                'html': render_template('partials/about_content.html',
                                        secret_form=secret_form),
                'title': 'About Us - Secures Secrets'
            })
    return render_template('about.html', secret_form=secret_form, show_header=True, show_footer=True)

@main.route('/contact', methods=['GET' ,'POST'])
@limiter.limit("10 per minute")
def contact():
    secret_form = SecretForm()
    form = ContactUsForm(obj=current_user)
    site_key = os.environ.get("SITE_KEY")
    
    if not site_key:
        logger.error("SITE_KEY is not set in environment variables")
        flash('reCAPTCHA configuration error. Please try again later.', 'danger')
    
    if request.method == 'POST':
        # Check for bot submission with Wildberries HTML pattern
        name_data = request.form.get('name', '')
        if '<!DOCTYPE html>' in name_data and 'Wildberries' in name_data:
            # Silently redirect without logging or processing
            return redirect(url_for('main.contact'))
        
        # Log form data for non-bot submissions
        logger.info(f"Form data: {request.form}")
        
        if form.validate_on_submit():
            # Check for suspicious input
            if is_suspicious_input(form.name.data) or is_suspicious_input(form.message.data):
                logger.error("Suspicious input detected in form submission")
                flash('Invalid input detected. Please try again.', 'danger')
                return redirect(url_for('main.contact'))
            
            
            
            # Verify reCAPTCHA for non-authenticated users
            if not current_user.is_authenticated:
                # Get reCAPTCHA token from form (only for non-authenticated users)
                recaptcha_token = request.form.get('recaptcha_token')

                if not recaptcha_token:
                    logger.error("Missing reCAPTCHA token")
                    flash('reCAPTCHA verification failed. Please try again.', 'danger')
                    return redirect(url_for('main.contact'))
                
                is_valid, error_msg = create_assessment(recaptcha_token, recaptcha_action='contact_form', flask_request=request)
                if not is_valid:
                    logger.error(f"reCAPTCHA error: {error_msg}")
                    flash('reCAPTCHA verification failed. Please try again.', 'danger')
                    return redirect(url_for('main.contact'))
            else:
                is_valid = True  # Skip reCAPTCHA for authenticated users
            
            if is_valid:
                data = form.data
                logger.info(f"Contact Form submitted successfully: {data}")
                try:
                    contact_email(data["name"], data["email"], data["subject"], data["message"])
                    flash('Your message has been sent successfully!', 'success')
                    return redirect(url_for('main.contact'))
                except Exception as e:
                    logger.error(f"Error sending email from contact: {e}")
                    flash('An error occurred while sending your message. Please try again.', 'danger')
    
    if current_user.is_authenticated:
        base_template = 'base.html'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'html': render_template('partials/contact_content.html',
                                       form=form,
                                       secret_form=secret_form,
                                       base_template=base_template,
                                       site_key=site_key),
                'title': 'Contact Us - Secures Secrets'
            })
    else:
        base_template = 'base_0.html'
        show_footer = False
    
    return render_template('contact.html', form=form, secret_form=secret_form, base_template=base_template, site_key=site_key, show_header=True, show_footer=True)

@main.route('/privacy-policy')
def privacy():

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    return render_template('privacy.html', secret_form=secret_form, show_header=True, show_footer=True)

@main.route('/child-safety')
def safty():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    return render_template('child_safety.html', secret_form=secret_form, show_header=True, show_footer=True)


@main.route('/cookie-policy')
def cookie():

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    secret_form = SecretForm()
    return render_template('cookie.html', secret_form=secret_form, show_header=True, show_footer=True)

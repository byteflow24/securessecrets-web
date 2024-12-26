from flask import Blueprint, render_template, redirect, url_for, send_from_directory, flash, request, session, jsonify, current_app, abort, get_flashed_messages
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFError
from . import db
from .forms import SecretForm, RegisterForm, LoginForm, SearchForm, ShareForm, ProfileForm, ChangePasswordForm, PlanUpgradeForm, ForgetPaswdForm, CardDetailsForm
from .models import User, LoginHistory, Secret, Payment, Plan, SharedSecret, HistoryPayment, PublicSecrets
from .utils import get_unique_title, admin_only, current_user_only, require_pricing_session, generate_token, send_verification_email, is_safe_url, decrypt_secrets, tokenize_card, create_charge, populate_plan_choices, get_charge_details, get_ip, get_user_agent, is_encrypted, encrypt_secret, decrypt_secret, send_payment_email, recurring_payment, reset_password_email
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy import desc
from datetime import date, datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import os
import traceback


main = Blueprint('main', __name__)

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
                'username': form.username.data,
                'email': form.email.data,
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
            email_token = generate_token()
        )
        db.session.add(new_user)
        try:
            db.session.commit()
            login_user(new_user)  # Log in the new user after successful commit
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

# Log in server
@main.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    # Get next from both GET and POST
    next_page = request.args.get('next') or request.form.get('next')

    if form.validate_on_submit():
        password = form.password.data
        user = db.session.execute(db.select(User).where(User.email == form.user.data or User.username == form.user.data)).scalar()
        
        if not user:
            flash("That email/ username does not exist, please try again.", "danger")
            return redirect(url_for('main.login'))
        
        elif not check_password_hash(user.password, password):
            flash('Password incorrect, please try again.', "danger")
            return redirect(url_for('main.login'))
        
        else:
            if not user.is_confirmed:
                flash('Please confirm your email address before logging in.', 'warning')
                return redirect(url_for('main.confirmation_pending', user=user.id))
            login_user(user)

            # Update last login time
            ip_address = request.remote_addr  # This retrieves the client's IP address
    
            # Add a new entry in the LoginHistory table
            login_history = LoginHistory(user_id=user.id, login_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ip_address=ip_address)
            db.session.add(login_history)
            db.session.commit()
            # No need for the Session timeout in this page
            session.permanent = False
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            
            return redirect(url_for('main.dashboard'))
    
    # Fetch the public shared secrets, eager-load user and secret relationships
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

        if secret.public:
            # If a recent login exists and it's more recent than the current last_login
            if latest_login and (not secret.last_login or latest_login > secret.last_login):
                # Update the last_login to the latest login date
                secret.last_login = latest_login

                # Handle `period` and calculate `time_period` if `period` is present
                if secret.period:
                    try:
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

            # Update the associated PublicSecrets share_date if available
            public_secret = PublicSecrets.query.filter_by(shared_secret_id=secret.id).first()
            if public_secret:
                # Update share_date based on valid `time_period` or `date_time`
                if secret.time_period:
                    public_secret.share_date = secret.time_period
                elif date_time:
                    public_secret.share_date = date_time

    # Commit changes to the database
    db.session.commit()

    # Fetch all public shared secrets with eligible share_date, sorted by share_date (newest first)
    public_secrets = PublicSecrets.query.filter(
        PublicSecrets.share_date <= datetime.now()
    ).order_by(PublicSecrets.share_date.desc()).all()

    upload_folder = current_app.config['UPLOAD_FOLDER']

    # Check if files exist; delete secrets with missing files
    for public_secret in public_secrets[:]:
        if public_secret.file:  # If there's a file associated
            file_path = os.path.join(upload_folder, public_secret.file)
            if not os.path.exists(file_path):  # File is missing
                # Delete the secret from PublicSecrets
                db.session.delete(public_secret)
                public_secrets.remove(public_secret)

    # Decrypt and prepare public secrets for display
    decrypted_secrets = []
    for public_secret in public_secrets:
        public_secret.display_time = ''
        
         # Always format the share_date time
        public_secret.display_time = public_secret.share_date.strftime('%H:%M') if public_secret.share_date else ''

        # Decrypt the secret if it's encrypted
        if is_encrypted(public_secret.secret):
            public_secret.secret = decrypt_secret(public_secret.secret)

        # Append the public secret to the list
        decrypted_secrets.append(public_secret)
    
    return render_template('login.html', form=form, current_user=current_user, show_header=False, show_footer=True, public_secrets=decrypted_secrets)

# Log out server
@main.route('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.login'))

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

# Setting the profile
@main.route('/profile', methods=['GET', 'POST'])
@login_required
def update_profile():
    secret_form = SecretForm()
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    pr_form = ProfileForm(obj=current_user)
    login = LoginHistory.query.filter_by(user_id=current_user.id).all()
    last_login = LoginHistory.query.filter_by(user_id=current_user.id).order_by(LoginHistory.login_time.desc()).first()
    if pr_form.validate_on_submit():
        # Handle profile update (only profile details)
        current_user.username = pr_form.username.data
        current_user.phone = pr_form.phone.data
        current_user.country_code = pr_form.code.data
        db.session.commit()
        flash('Mobile number updated successfully!', 'success')
        return redirect(url_for('main.update_profile'))
    pr_form.code.data = current_user.country_code

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/profile_content.html', current_user=current_user, pr_form=pr_form, ps_form=ChangePasswordForm(), login_history=login, last_login=last_login, secret_form=secret_form)
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
def change_password():
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
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
def dashboard():
    secret_form = SecretForm()
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    # counting secrets for each user
    secrets = Secret.query.filter_by(user_id=current_user.id).count()
    last_login = current_user.login_history[-1] if current_user.login_history else None

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

        if secret.public:
            # If a recent login exists and it's more recent than the current last_login
            if latest_login and (not secret.last_login or latest_login > secret.last_login):
                # Update the last_login to the latest login date
                secret.last_login = latest_login

                # Handle `period` and calculate `time_period` if `period` is present
                if secret.period:
                    try:
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

            # Update the associated PublicSecrets share_date if available
            public_secret = PublicSecrets.query.filter_by(shared_secret_id=secret.id).first()
            if public_secret:
                # Update share_date based on valid `time_period` or `date_time`
                if secret.time_period:
                    public_secret.share_date = secret.time_period
                elif date_time:
                    public_secret.share_date = date_time

    # Commit changes to the database
    db.session.commit()

    # Fetch all public shared secrets with eligible share_date, sorted by share_date (newest first)
    public_secrets = PublicSecrets.query.filter(
        PublicSecrets.share_date <= datetime.now()
    ).order_by(PublicSecrets.share_date.desc()).all()

    upload_folder = current_app.config['UPLOAD_FOLDER']

    # Check if files exist; delete secrets with missing files
    for public_secret in public_secrets[:]:
        if public_secret.file:  # If there's a file associated
            file_path = os.path.join(upload_folder, public_secret.file)
            if not os.path.exists(file_path):  # File is missing
                # Delete the secret from PublicSecrets
                db.session.delete(public_secret)
                public_secrets.remove(public_secret)

    # Commit changes after deletion
    db.session.commit()

    # Decrypt and prepare public secrets for display
    decrypted_secrets = []
    for public_secret in public_secrets:
        public_secret.display_time = ''
        
        # Always format the share_date time
        public_secret.display_time = public_secret.share_date.strftime('%H:%M') if public_secret.share_date else ''

        # Decrypt the secret if it's encrypted
        if is_encrypted(public_secret.secret):
            public_secret.secret = decrypt_secret(public_secret.secret)

        # Append the public secret to the list
        decrypted_secrets.append(public_secret)

    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/dashboard_content.html', current_user=current_user, public_secrets=decrypted_secrets, secrets=secrets, last_login=last_login, secret_form=secret_form, show_secrets_list=False)
    
    return render_template('dashboard.html', current_user=current_user, show_header=True, show_footer=True, show_secrets_list=False, public_secrets=decrypted_secrets, secrets=secrets, last_login=last_login, secret_form=secret_form)

# List of all secerts for the user 
@main.route('/all-secrets', methods=['GET', 'POST'])
@login_required
def all_secrets():
    if not current_user.is_authenticated:
        return jsonify(error = "Unauthorized"), 401

    form = SearchForm()
    share_form = ShareForm()
    secret_form = SecretForm()

    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))

    # Fetch all secrets for the user
    query = db.select(Secret).where(Secret.user_id == current_user.id)
    user_secrets = db.session.execute(query).scalars().all()

    if not user_secrets:
        current_user.storage_used = 0
    db.session.commit()

    # Decrypt secrets
    decrypted_secrets = decrypt_secrets(user_secrets)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/all_secrets_content.html', user_secrets=decrypted_secrets, current_user=current_user, share_form=share_form, form=form, secret_form=secret_form)
    return render_template('all_secrets.html', user_secrets=decrypted_secrets, current_user=current_user, form=form, share_form=share_form, secret_form=secret_form, show_header=True, show_footer=True, show_secrets_list=True)

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
def add_secret():
    form = SecretForm()

    if form.validate_on_submit():
        try:
            # Check if both secret and file are missing
            if not form.secret.data.strip() and not request.form.get("uploadedFileName"):
                return jsonify(success=False, error="Please provide a secret or upload a file."), 400

            # Handle storage and file limits
            storage_limit = current_user.plan.storage_limit
            encrypted_secret = encrypt_secret(form.secret.data)
            secret_size = len(encrypted_secret.encode('utf-8'))

            if current_user.storage_used + secret_size > storage_limit:
                return jsonify(success=False, error=f"Adding this secret will exceed your {current_user.plan.plan} plan's storage limit."), 403

            # Generate a unique title
            unique_title = get_unique_title(form.title.data.strip(), current_user.id)
            
            # If a file was uploaded, validate and save it
            filename = request.form.get("uploadedFileName")
            current_user.storage_used += secret_size

            # Create and save the new secret
            new_secret = Secret(
                title=unique_title,
                secret=encrypted_secret,
                file=filename,
                date=date.today().strftime("%Y-%m-%d"),
                user_id=current_user.id,
            )
            db.session.add(new_secret)
            db.session.commit()
            return jsonify(
                success=True, title=new_secret.title,
                date=new_secret.date.today().strftime("%Y-%m-%d"),
                flash_message="New secret has been added successfully."), 200
        
        except IntegrityError:
            db.session.rollback()
            return jsonify(success=False, error="An error occurred while saving your secret. Please try again."), 500
    else:
        return jsonify(success=False, error="Form validation failed."), 400

# Uploading file
@main.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify(error = 'No file part in the request'), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify(error = 'No selected file'), 400

    # Check if user is authenticated and retrieve their storage limit
    if not current_user.is_authenticated:
        return jsonify(error = 'User not authenticated'), 401

    # Check file size
    try:
        file_size = len(file.read())
        file.seek(0)  # Reset file pointer
        if current_user.storage_used + file_size > current_user.plan.storage_limit:
            return jsonify(error = 'Exceeds storage limit'), 403
    except Exception as e:
        return jsonify(error = str(e)), 500

    # Save the file
    filename = secure_filename(file.filename)
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    file_path = os.path.join(upload_folder, filename)

    try:
        file.save(file_path)
        # Update storage usage
        current_user.storage_used += file_size
        db.session.commit()
        print("filename:",filename)
        return jsonify(message = 'File successfully uploaded', filename = filename), 200
    except Exception as e:
        return jsonify(error = str(e)), 500

# Route to fetch the user's current storage usage and limit, requiring login.
@main.route('/get-storage-info', methods=['GET'])
@login_required
def get_storage_info():
    try:
        used = current_user.storage_used
        total = current_user.plan.storage_limit
        return jsonify({'used': used, 'total': total})
    except Exception as e:
        print(f"Error fetching storage info: {e}")
        return jsonify({'error': str(e)}), 500

# Sharing secret server
@main.route('/share', methods=['POST'])
def share():
    form = ShareForm()

    # Default variable initialization
    sharing_type = None
    email, public, token, time_period, date, time, last_login = None, False, None, None, None, None, None

    if form.validate_on_submit():
        # Determine sharing type

        if form.date_period.data:
            sharing_type = "last_login"
            if not form.emails_login.data and not form.public_login.data:
                return jsonify({"success": False, "message": "Email or Public must be selected for Last Login Check."}), 400

            email = form.emails_login.data
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
                return jsonify({"success": False, "message": "Last login time not found."}), 400

            # Calculate the time period
            if date_period:
                time_period = last_login + timedelta(days=int(date_period))
                message = f"Your secret will be shared after {date_period} day/s from the last login."
        elif form.date.data and form.time.data:
            sharing_type = "scheduled"
            if not form.emails_scheduled.data and not form.public_scheduled.data:
                return jsonify({"success": False, "message": "Email or Public must be selected for Scheduled Sharing."}), 400

            date = form.date.data
            time = form.time.data
            if isinstance(time, str):  # Handle if time is submitted as a string
                time = datetime.strptime(time, "%H:%M").time()
            time_str = time.strftime("%H:%M")

            email = form.emails_scheduled.data
            public = form.public_scheduled.data
            message = f"Your secret is scheduled for {date} at {time_str}."
        else:
            return jsonify({"success": False, "message": "Invalid sharing type or missing fields!"}), 400

        # Create and save the shared secret
        print("Form submission data:", form.data)
        try:
            token = generate_token()
            secret = Secret.query.filter_by(id=request.args.get("secret_id")).first()

            # Add the new shared secret first
            new_shared_secret = SharedSecret(
                user_id=current_user.id,
                secret_id=request.args.get("secret_id"),
                email=email,
                public=public,
                last_login=last_login if sharing_type == "last_login" else None,
                period=date_period if sharing_type == "last_login" else None,
                time_period=time_period if sharing_type == "last_login" else None,
                token=token,
                date_to_send=date if sharing_type == "scheduled" else None,
                time_to_send=time_str if sharing_type == "scheduled" else None,
                received=False,
                delete_confirmed=form.confirm_deletion.data if sharing_type == "scheduled" else False,
            )
            db.session.add(new_shared_secret)
            db.session.commit()  # Commit to generate ID
            if public:
                # Add the public secret
                public_secrets = PublicSecrets(
                    shared_secret_id=new_shared_secret.id,
                    username=current_user.username,
                    title=secret.title,
                    secret=secret.secret,
                    file=secret.file,
                    share_date=(
                        time_period if sharing_type == "last_login"
                        else datetime.combine(date, time.time()) if sharing_type == "scheduled"
                        else None
                    )
                )
                db.session.add(public_secrets)
                db.session.commit()
            flash(message, "success")
            return jsonify(success=True, message=message), 200

        except Exception as e:
            db.session.rollback()
            error_message = str(e)
            print(f"Error occurred: {error_message}")  # Log the error for debugging
            flash(f"Error occurred: {error_message}")
            return jsonify(success= False, message= "An error occurred while sharing the secret.", error= error_message), 500

    # Log validation errors
    print("Validation errors:", form.errors)
    flash("Please fix the errors in the form.", "danger")
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
            shared_secret.delete_at = now + timedelta(hours=1)
            db.session.commit()
        else:
            # Check if delete_at is not None and if the current time is past the delete time
            if shared_secret.delete_at and now > shared_secret.delete_at:
                # Delete the secret after 1 minute of opening
                db.session.delete(shared_secret)
                db.session.commit()
                return "The link has expired.", 404
            
        # Retrieve the associated secret
        secret = db.get_or_404(Secret, shared_secret.secret_id)
        # Decrypting the secret
        decrypted_secret_content = decrypt_secret(secret.secret)
        return render_template('display_secret.html', decrypted_secret=decrypted_secret_content, secret=secret)
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
@main.route('/delete/<int:sec_id>', methods=['GET', 'POST'])
@login_required
def delete_secret(sec_id):
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    try:
        secret = db.get_or_404(Secret, sec_id)

        # Calculate the size of the secret's text (in bytes)
        text_size = len(secret.secret.encode('utf-8'))  # Convert the string to bytes and measure its length

        # Get the file size if the secret has a file
        file_size = 0
        if secret.file:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secret.file)

            # Check if the file is still referenced in PublicSecrets
            is_shared_publicly = PublicSecrets.query.filter_by(file=secret.file).first()
            if os.path.exists(file_path) and not is_shared_publicly:
                file_size = os.path.getsize(file_path)

                # Remove the file from the server
                os.remove(file_path)

        # Update the user's storage used
        total_size = text_size + file_size
        current_user.storage_used = max(0, current_user.storage_used - total_size)  # Prevent negative storage

        # Commit the changes to update storage
        db.session.commit()

        # Delete the secret from the database
        db.session.delete(secret)
        db.session.commit()
        flash('Secret has been deleted successfully.', 'success')
        return redirect(url_for('main.all_secrets'))

    except IntegrityError:
        db.session.rollback()
        # Handle error (e.g., notify the user, log the error, etc.)
        return "An error occurred while deleting the secret.", 500
    

# User to delete his account
@main.route('/delete-account/<int:user_id>', methods=['GET', 'POST'])
@login_required
def delete_account(user_id):
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    user = User.query.get(user_id)

    if user is None or user.id != current_user.id:
        flash("User not found or unauthorized action.", "danger")
        return redirect(url_for('main.update_profile'))
    
    # Only proceed if the user confirms deletion (no need for form submission now)
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Your account has been deleted. We're sad to see you leave ☹️.", "success")
    return redirect(url_for('main.login'))


# Editing secret
@main.route('/update-secret/<int:secret_id>', methods=['POST'])
@login_required
def update_secret(secret_id):
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401

    form = SecretForm()
    secret = db.get_or_404(Secret, secret_id)

    if form.validate_on_submit():
        try:
            # Encrypt secret data and calculate its size
            encrypted_secret = encrypt_secret(form.secret.data.strip())
            new_text_size = len(encrypted_secret.encode('utf-8'))
            old_text_size = len(secret.secret.encode('utf-8'))

            # Track file size changes
            new_file_size = 0
            old_file_size = 0
            file_changed = False

            if form.file.data:
                file = form.file.data
                filename = secure_filename(file.filename)

                if filename != secret.file:
                    file_changed = True
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    new_file_path = os.path.join(upload_folder, filename)
                    
                    # Calculate file size and reset pointer
                    file_size = file.seek(0, os.SEEK_END)  # Move pointer to end
                    new_file_size = file_size
                    file.seek(0)  # Reset pointer to start

                    # Initialize old_file_path and old_file_size
                    old_file_path = None
                    old_file_size = 0

                    # Handle old file
                    if secret.file:
                        old_file_path = os.path.join(upload_folder, secret.file)
                        old_file_size = os.path.getsize(old_file_path) if os.path.exists(old_file_path) else 0

                    # Calculate storage
                    new_storage_used = current_user.storage_used - old_text_size - old_file_size + new_text_size + new_file_size
                    if new_storage_used > current_user.plan.storage_limit:
                        return jsonify(success=False, error="Exceeds storage limit."), 403

                    # Save the new file if file has changed
                    if file_changed:
                        file.save(new_file_path)

                        # Delete old file if it exists
                        if old_file_path and os.path.exists(old_file_path):
                            os.remove(old_file_path)
                    
                    secret.file = filename
                else:
                    new_file_size = old_file_size

            # Check if storage limit will be exceeded
            total_new_storage = current_user.storage_used - old_text_size - old_file_size + new_text_size + new_file_size
            if total_new_storage > current_user.plan.storage_limit:
                return jsonify(success=False, error="Exceeds storage limit."), 403

            # Update secret fields if changed
            if form.title.data.strip() != secret.title:
                secret.title = form.title.data.strip()
            if encrypted_secret != secret.secret:
                secret.secret = encrypted_secret

            # Update storage and commit changes
            current_user.storage_used = total_new_storage
            secret.date = date.today().strftime("%Y-%m-%d")
            db.session.commit()

            # Decrypt the secret for display
            decrypted_secret = decrypt_secret(secret.secret)

            return jsonify(
                success=True,
                flash_message="Secret updated successfully!",
                secret={
                    "id": secret.id,
                    "secret": decrypted_secret,
                    "file": secret.file,
                    "date": secret.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "file_preview": secret.file.endswith(('.png', '.jpg', '.jpeg', '.gif')),
                }
            ), 200

        except Exception as e:
            db.session.rollback()
            return jsonify(success=False, error=str(e)), 500

    return jsonify(success=False, error="Form validation failed."), 400

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
        return render_template('partials/pricing_content.html', plans=plans)
    return render_template('pricing.html', current_user=current_user, plans=plans, show_header=True, show_footer=True)


# Payment methods
@main.route('/payment', methods=['GET', 'POST'])
@login_required
def payment():
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    form = CardDetailsForm()
    plan_id = current_user.plan_id
    plan = db.get_or_404(Plan, plan_id)
    amount = plan.price
    currency = plan.currency
    description = "new"
    if form.validate_on_submit():
        card = form.card_number.data
        ex_month, ex_year = form.exp_date.data.split('/')
        cvc = form.cvc.data
        name = form.name.data
        email = current_user.email
        phone_country_code = current_user.country_code
        phone_number = current_user.phone
        first_name = name

        try:
            token_id = tokenize_card(int(card), int(ex_month), int(ex_year), int(cvc), name)
            # Create charge and handle 3D Secure or redirect to Tap payment page
            print(token_id)
            charge_response = create_charge(amount, currency, description, email, phone_country_code, phone_number, first_name, plan_id, token_id['id'])
            
            if isinstance(charge_response, str):
                # If it's a URL (3D Secure), redirect
                return redirect(charge_response)

            if charge_response.get('status') == 'CAPTURED':
                payment_url = charge_response.get('transaction', {}).get('url')
                if payment_url:
                    return redirect(payment_url)

            flash("Failed to initiate payment. Please try again.", "danger")
            return redirect(url_for('main.payment'))

        except Exception as e:
            flash(str(e), "danger")
            return redirect(url_for('main.payment'))
    return render_template("card_details.html", form=form, show_header=False, show_footer=False)


# Payment completed
@main.route('/payment_complete')
@login_required
def payment_complete():
    charge_id = request.args.get('tap_id')
    plan_id = request.args.get('plan_id')
    user_ip = get_ip()
    user_agent = get_user_agent()
    plan = db.get_or_404(Plan, plan_id)

    if charge_id:
        try:
            charge_details = get_charge_details(charge_id)
            if charge_details.get('status') == 'CAPTURED':
                user = current_user

                # Check user validity before accessing user.id
                if user:
                    # Save payment details to the database
                    new_payment = Payment(
                        amount=charge_details['amount'],
                        currency=charge_details['currency'],
                        payment_method=charge_details['source']['payment_type'],
                        payment_status=charge_details['status'],
                        transaction_id=charge_details['id'],
                        track_id=charge_details['reference']['track'],
                        authorization_id=charge_details['transaction']['authorization_id'],
                        gateway_response_code=charge_details['gateway']['response']['code'],
                        gateway_response_message=charge_details['gateway']['response']['message'],
                        acquirer_response_code=charge_details['acquirer']['response']['code'],
                        acquirer_response_message=charge_details['acquirer']['response']['message'],
                        card_brand=charge_details['card']['brand'],
                        card_last_four=charge_details['card']['last_four'],
                        three_d_secure_status=charge_details['security']['threeDSecure']['status'],
                        user_id=user.id,
                        plan_id=plan_id,
                        ip_address=user_ip,
                        user_agent=user_agent
                    )

                    history = HistoryPayment(
                        user_id=user.id,
                        plan_id=plan_id,
                        amount=charge_details['amount'],
                        currency=charge_details['currency'],
                        payment_method=charge_details['source']['payment_type'],
                        payment_status=charge_details['status'],
                        transaction_id=charge_details['id'],
                        card_brand=charge_details['card']['brand'],
                        card_last_four=charge_details['card']['last_four'],
                        authorization_id=charge_details['transaction']['authorization_id']
                    )

                    # Save subscription details
                    # if not user.trial_end_date or user.trial_end_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                    #     user.trial_start_date = datetime.now(timezone.utc)
                    #     user.trial_end_date = datetime.now(timezone.utc) + timedelta(days=14)
                    #     user.subscription_start_date = user.trial_end_date + timedelta(days=1)
                    #     user.subscription_end_date = user.subscription_start_date + timedelta(days=30)
                    # else:
                    #     user.subscription_start_date = datetime.now(timezone.utc)
                    #     user.subscription_end_date = user.subscription_start_date + timedelta(days=30)

                    user.subscription_status = "active"
                    user.customer_id = charge_details['customer']['id']
                    user.card_id = charge_details['card']['id']

                    if 'payment_agreement' in charge_details:
                        user.payment_agreement_id = charge_details['payment_agreement']['id']

                    # Add payment and history payment records to the session
                    db.session.add(new_payment)
                    db.session.add(history)
                    db.session.flush()  # This prepares the session without committing
                    db.session.commit()

                    description = charge_details.get("description", "renewal")
                    if description == "new":
                        send_payment_email(user.email, user.username, plan.plan, plan.price, user.subscription_start_date, "upgrade", charge_details['card']['brand'], charge_details['card']['last_four'])
                        flash("Your plan has been successfully paid.", "success")
                    elif description == "upgrade":
                        send_payment_email(user.email, user.username, plan.plan, plan.price, user.subscription_start_date, "upgrade", charge_details['card']['brand'], charge_details['card']['last_four'])
                        flash("Your plan has been successfully upgraded.", "success")
                    elif description == "renewal":
                        send_payment_email(user.email, user.username, plan.price, user.subscription_start_date, "renewal", charge_details['card']['brand'], charge_details['card']['last_four'])
                        flash("Your subscription has been successfully renewed.", "success")

                    return redirect(url_for('main.dashboard'))
            else:
                flash(f"Payment failed: {charge_details.get('response', {}).get('message', 'Unknown error')}", "danger")
                return redirect(url_for('main.billing'))

        except Exception as e:
            flash(str(e), "danger")
            return redirect(url_for('main.billing'))

    return redirect(url_for('main.dashboard'))

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
        # Save subscription details
        if not user.trial_end_date or user.trial_end_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            user.trial_start_date = datetime.now(timezone.utc)
            user.trial_end_date = datetime.now(timezone.utc) + timedelta(days=14)
            user.subscription_start_date = user.trial_end_date + timedelta(days=1)
            user.subscription_end_date = user.subscription_start_date + timedelta(days=30)
        # else:
        #     user.subscription_start_date = datetime.now(timezone.utc)
        #     user.subscription_end_date = user.subscription_start_date + timedelta(days=30)
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
    print(user_id)
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
def billing():
    # If the user is not authenticated (session expired), return 401
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401  # Explicitly return 401 status for AJAX
    
    secret_form = SecretForm()
    form = PlanUpgradeForm()
    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))
    user = User.query.get(current_user.id)
    history_payment = HistoryPayment.query.filter_by(user_id=user.id).order_by(HistoryPayment.payment_date.desc()).all()
    plans = Plan.query.order_by(Plan.price).all()

    # Populate form choices using the helper function
    populate_plan_choices(form, user)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/billing_content.html', user=user, payments=history_payment, form=form, plan=plans, secret_form=secret_form)
    return render_template('billing.html', user=user, payments=history_payment, form=form, plan=plans, secret_form=secret_form, show_header=True, show_footer=True)

# to pay the plan if still not paid
@main.route('/pay_now', methods=['POST'])
@login_required
def pay_now():
    payment_method = request.form.get('payment_method')
    current_date = datetime.now(timezone.utc)
    date_email = datetime.now()

    if current_user.subscription_status != "active":
        user_plan = db.get_or_404(Plan, current_user.plan_id)
        amount = user_plan.price
        currency = user_plan.currency
        description = "renewal"

        try:
            if payment_method == 'saved_card':
                card_id = current_user.card_id
                payment_response = recurring_payment(
                    current_user.customer_id, card_id, get_ip(), 
                    current_user.payment_agreement_id, amount, currency, description
                )
                history = HistoryPayment(
                        user_id=current_user.id,
                        plan_id=user_plan.id,
                        amount=payment_response['amount'],
                        currency=payment_response['currency'],
                        payment_method=payment_response['source']['payment_type'],
                        payment_status=payment_response['status'],
                        transaction_id=payment_response['id'],
                        card_brand=payment_response['card']['brand'],
                        card_last_four=payment_response['card']['last_four'],
                        authorization_id=payment_response['transaction']['authorization_id']
                    )
            else:
                # Redirect user to payment page for new card payment
                return redirect(url_for('main.payment')) # Redirecting to the TAP payment page

            if payment_response['status'] == 'CAPTURED':
                flash("Payment was successful!", "success")
                current_user.subscription_end_date = current_date + timedelta(days=30) if user_plan.billing_cycle == 'monthly' else current_user.subscription_end_date
                current_user.subscription_status = "active"
                db.session.add(history)
                db.session.commit()
                send_payment_email(current_user.email, current_user.username, user_plan.plan, amount, date_email, 'renewal', payment_response['card']['brand'],payment_response['card']['last_four'])
            else:
                flash("Payment failed. Please try again.", "danger")
        except Exception as e:
            flash(str(e), "danger")

        return redirect(url_for('main.billing'))



# Upgrading plan
@main.route('/upgrade-plan', methods=['POST'])
@login_required
def upgrade_plan():
    form = PlanUpgradeForm()
    current_date = datetime.now(timezone.utc)
    date_email = datetime.now()
    # Populate form choices using the helper function
    populate_plan_choices(form, current_user)

    if form.plan_id.data == 0:
        flash("Please select a valid plan to upgrade.", "danger")
        return redirect(url_for('main.billing'))
    
    # Check if from datas exists
    if form.validate_on_submit():
        selected_plan_id = form.plan_id.data
        plan = db.get_or_404(Plan, selected_plan_id)
        amount = plan.price
        currency = plan.currency
        description = "upgrade"

        try:
            card_id = current_user.card_id
            payment_response = recurring_payment(
                current_user.customer_id, card_id, get_ip(), 
                current_user.payment_agreement_id, amount, currency, description
            )
            if payment_response['status'] == 'CAPTURED':
                flash(f"Plan changed to {plan.plan} successfully!", "success")
                current_user.subscription_end_date = current_date + timedelta(days=30) if plan.billing_cycle == 'monthly' else current_user.subscription_end_date
                current_user.subscription_status = "active"
                current_user.plan_id = plan.id
                history = HistoryPayment(
                        user_id=current_user.id,
                        plan_id=plan.id,
                        amount=payment_response['amount'],
                        currency=payment_response['currency'],
                        payment_method=payment_response['source']['payment_type'],
                        payment_status=payment_response['status'],
                        transaction_id=payment_response['id'],
                        card_brand=payment_response['card']['brand'],
                        card_last_four=payment_response['card']['last_four'],
                        authorization_id=payment_response['transaction']['authorization_id']
                    )
                db.session.add(history)
                db.session.commit()
                send_payment_email(current_user.email, current_user.username, plan.plan, amount, date_email, 'upgrade', payment_response['card']['brand'],payment_response['card']['last_four'])
            else:
                flash("Payment failed. Please try again.", "danger")
        except Exception as e:
            flash(str(e), "danger")

        return redirect(url_for('main.billing'))


# Files where be downloaded
@main.route('/downloads/<filename>')
def download_file(filename):
    try:
        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        # Get the absolute path of the file
        file_path = os.path.join(upload_folder, filename)
        abs_path = os.path.abspath(file_path)

        # Check if the file exists
        if not os.path.exists(abs_path):
            flash("File not found.", "danger")
            return abort(404)
        
        # For PDF and Office files, serve them inline (no download)
        if filename.endswith('.pdf'):
            return send_from_directory(
                os.path.dirname(abs_path), 
                os.path.basename(abs_path), 
                as_attachment=False,  # This prevents the file from being downloaded
                mimetype='application/pdf'  # Explicitly set the MIME type to PDF
            )
        
        # Check for Word, Excel, and PowerPoint files and serve inline
        elif filename.endswith(('.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
            # We can set the MIME type based on file extensions
            if filename.endswith(('.doc', '.docx')):
                mimetype = 'application/msword'
            elif filename.endswith(('.xls', '.xlsx')):
                mimetype = 'application/vnd.ms-excel'
            elif filename.endswith(('.ppt', '.pptx')):
                mimetype = 'application/vnd.ms-powerpoint'
            
            return send_from_directory(
                os.path.dirname(abs_path), 
                os.path.basename(abs_path), 
                as_attachment=False,  # Prevent download, show inline
                mimetype=mimetype  # Set the correct MIME type for each file type
            )
        
        # Send the file from the directory
        return send_from_directory(os.path.dirname(abs_path), os.path.basename(abs_path), as_attachment=True)

    except Exception as e:
        # Print the full traceback to help with debugging
        print("Error: ", str(e))
        traceback.print_exc()

        # Show a user-friendly error message
        flash(f"Error downloading file: {str(e)}", "danger")
        return abort(500)


@main.route('/terms-of-services')
def terms():
    return render_template('terms.html', show_header=True, show_footer=True)


@main.route('/about-us')
def about():
    secret_form = SecretForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/about_content.html', secret_form=secret_form)
    return render_template('about.html', secret_form=secret_form, show_header=True, show_footer=True)


@main.route('/contact-us')
def contact():
    secret_form = SecretForm()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('partials/contact_content.html', secret_form=secret_form)
    return render_template('contact.html', secret_form=secret_form, show_header=True, show_footer=True)


@main.route('/privacy-policy')
def privacy():
    secret_form = SecretForm()
    return render_template('privacy.html', secret_form=secret_form, show_header=True, show_footer=True)


@main.route('/cookie-policy')
def cookie():
    secret_form = SecretForm()
    return render_template('cookie.html', secret_form=secret_form, show_header=True, show_footer=True)

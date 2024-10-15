from flask import Blueprint, render_template, redirect, url_for, send_from_directory, flash, request, session, jsonify, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user
from . import db
from .forms import SecretForm, RegisterForm, LoginForm, SearchForm, ShareForm, ProfileForm, ChangePasswordForm, PlanUpgradeForm, ForgetPaswdForm
from .models import User, Secret, Payment, Plan, SharedSecret, HistoryPayment
from .utils import get_unique_title, admin_only, current_user_only, require_pricing_session, generate_token, send_verification_email, is_safe_url, create_charge, populate_plan_choices, get_charge_details, get_ip, get_user_agent, encrypt_secret, decrypt_secret, refund_method, send_payment_email, recurring_payment, reset_password_email
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timedelta, timezone, time
from sqlalchemy.exc import SQLAlchemyError
from smtplib import SMTPException
import os
import traceback


main = Blueprint('main', __name__)


# Registeration server @sign-up
@main.route('/register', methods=['GET', 'POST'])
@require_pricing_session()
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegisterForm()
    plan_id = request.args.get('plan_id')
    
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
        session['registration_data'] = {
            'email': form.email.data,
            'username': form.username.data,
            'password': generate_password_hash(form.password.data, method='pbkdf2:sha256', salt_length=16),
            'country_code': form.code.data,
            'phone': form.phone.data,
            'plan_id': plan_id  # Store selected plan
        }
        
        return redirect(url_for('main.payment', plan_id=plan_id))

    if 'form_data' in session:
        form.username.data = session['form_data'].get('username', '')
        form.email.data = session['form_data'].get('email', '')
        form.code.data = session['form_data'].get('code')
        form.phone.data = session['form_data'].get('phone')

    return render_template('register.html', form=form, current_user=current_user)


# Log in server
@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()

    next_page = request.args.get('next') or request.form.get('next')  # Get next from both GET and POST

    if form.validate_on_submit():
        password = form.password.data
        user = db.session.execute(db.select(User).where(User.email == form.user.data or User.username == form.user.data)).scalar()
        
        if not user:
            flash("That email/ username does not exist, please try again.", "danger")
            return redirect(url_for('main.login', next=next_page))
        
        elif not check_password_hash(user.password, password):
            flash('Password incorrect, please try again.', "danger")
            return redirect(url_for('main.login', next=next_page))
        
        else:
            if not user.is_confirmed:
                flash('Please confirm your email address before logging in.', 'warning')
                return redirect(url_for('main.confirmation_pending', user=user.id))
            login_user(user)
            # Update last login time
            user.last_login = datetime.now().strftime("%Y-%m-%d %H:%M")
            db.session.commit()
            # Session timeout, after 15 mins user will be logged out
            session.permanent = True
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            
            secrets = Secret.query.filter_by(user_id=user.id).all()
            if not secrets:
                return redirect(url_for('main.home'))
            else:
                return redirect(url_for('main.all_secrets', user_id=current_user.id))
    
    return render_template('login.html', form=form, current_user=current_user)


# Log out server
@main.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.home'))

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
            flash('This email is not registered in our system.', 'danger')
        return redirect(url_for('main.login'))


# User forgot password
@main.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    form = ForgetPaswdForm()
    token = request.args.get("token")
    user = User.query.filter_by(reset_pswd_token=token).first()
    print(user.reset_pswd_token)

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
    pr_form = ProfileForm(obj=current_user)
    if pr_form.validate_on_submit():
        # Handle profile update (only profile details)
        current_user.username = pr_form.username.data
        current_user.phone = pr_form.phone.data
        current_user.country_code = pr_form.code.data
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('main.update_profile'))
    return render_template('profile.html', current_user=current_user, pr_form=pr_form, ps_form=ChangePasswordForm())


@main.route('/change-password', methods=['POST'])
@login_required
def change_password():
    ps_form = ChangePasswordForm()
    print(request.form)
    if ps_form.validate_on_submit():
        print("here")
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
    else:
        # Debug validation errors
        print(ps_form.errors)

    return redirect(url_for('main.update_profile'))


# Home page
@main.route('/', methods=['GET', 'POST'])
def home():

    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))

    form = SecretForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            session['form_data'] = {
                'title': form.title.data,
                'secret': form.secret.data,
            }
            flash("You need to log in to save your secret!", "warning")
            return redirect(url_for('main.login', next=request.url))

        # Retrieve the storage limit based on the user's plan
        storage_limit = current_user.plan.storage_limit  # Storage limit is already set based on user's plan

        # Calculate the size of the secret text
        secret_size = len(form.secret.data.encode('utf-8'))  # Convert text to bytes

        # Initialize total size with the size of the secret text
        total_size = secret_size

        filename = ""
        if form.file.data:
            file = form.file.data
            if file:
                filename = secure_filename(file.filename)
                file_size = len(file.read())  # Get the size of the file in bytes
                file.seek(0)  # Reset file pointer

                total_size += file_size

                # Check if the new file + secret will exceed the user's storage limit
                if current_user.storage_used + total_size > storage_limit:
                    flash(f"Adding this secret will exceed your {current_user.plan.plan} plan's storage limit.", "warning")
                    return redirect(url_for('main.all_secrets', user_id=current_user.id))

                # Save the file
                upload_folder = current_app.config['UPLOAD_FOLDER']
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)

        # Update the user's storage used (text + file)
        current_user.storage_used += total_size
        db.session.commit()

        # Generate a unique title
        unique_title = get_unique_title(form.title.data, current_user.id)

        # Encrypt the secret text
        encrypted_secret = encrypt_secret(form.secret.data)

        # Create a new Secret instance and add it to the database
        new_secret = Secret(
            title=unique_title,
            secret=encrypted_secret,
            file=filename,
            date=date.today().strftime("%B %d, %Y"),
            user_id=current_user.id
        )
        try:
            db.session.add(new_secret)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("An error occurred while saving your secret.", "warning")
            return redirect(request.url)

        # Clear session form data
        session.pop('form_data', None)
        return redirect(url_for('main.all_secrets', user_id=new_secret.user_id))

    if 'form_data' in session:
        form.title.data = session['form_data'].get('title', '')
        form.secret.data = session['form_data'].get('secret', '')

    return render_template('index.html', form=form, current_user=current_user)


# @main.route('/trigger-tasks', methods=['GET'])
# def trigger_tasks():
#     from .celery_worker import initiate_recurring_payment_task, trial_end_reminder_task, not_paied_reminder_task
#     initiate_recurring_payment_task.apply_async()
#     trial_end_reminder_task.apply_async()
#     not_paied_reminder_task.apply_async()
#     return "Tasks have been triggered!"

# List of all secerts for the user 
@main.route('/all-secrets/<int:user_id>', methods=['GET', 'POST'])
@login_required
@current_user_only
def all_secrets(user_id):
    form = SearchForm()
    share_form = ShareForm()
    query = db.select(Secret).where(Secret.user_id == user_id)

    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))

    if form.validate_on_submit():
        search_term = f"{form.search.data}" if form.search.data else None
        date_filter = form.date_filter.data
        alpha_filter = form.alpha_filter.data

        if search_term:
            query = query.where(Secret.title.ilike(search_term))
        if date_filter:
            if date_filter == "latest":
                query = query.order_by(Secret.date.desc())
            else:
                query = query.order_by(Secret.date.asc())
        if alpha_filter:
            if alpha_filter == "A-Z":
                query = query.order_by(Secret.title.asc())
            else:
                query = query.order_by(Secret.title.desc())

    user_secrets = db.session.execute(query).scalars().all()
    decrypted_secrets = []
    for secret in user_secrets:
        decrypted_secret_content = decrypt_secret(secret.secret)
        secret.secret = decrypted_secret_content
        decrypted_secrets.append(secret)

    return render_template('all_secrets.html', user_secrets=decrypted_secrets, current_user=current_user, form=form, share_form=share_form)

# Toggle pinned
@main.route('/toggle_pin/<int:secret_id>', methods=['POST'])
def toggle_pin(secret_id):
    secret = db.get_or_404(Secret, secret_id)
    secret.pinned = not secret.pinned
    db.session.commit()
    return jsonify(success=True)

# Toggle starred
@main.route('/toggle_star/<int:secret_id>', methods=['POST'])
def toggle_star(secret_id):
    secret = db.get_or_404(Secret, secret_id)
    secret.starred = not secret.starred
    db.session.commit()
    return jsonify(success=True)


# Sharing button
@main.route('/share', methods=['POST'])
def share():
    form = ShareForm()
    if form.validate_on_submit():
        email = form.email.data
        date = form.date.data if form.date.data else datetime.now().date()
        time = form.time.data.time() if form.time.data else datetime.now().time()
        confirm_deletion = form.confirm_deletion.data
        token = generate_token()

        try:
            # Save the sharing details to the database
            new_shared_secret = SharedSecret(
                user_id=current_user.id,
                secret_id=request.args.get("secret_id"),
                email=email,
                token=token,
                date_to_send=date,
                time_to_send=time,
                received=False,
                delete_confirmed=confirm_deletion
            )
            db.session.add(new_shared_secret)
            db.session.commit()

            flash(f"Your secret is scheduled to be sent on {date} at {time.strftime('%H:%M')}.", "success")
            return redirect(url_for('main.all_secrets', user_id=current_user.id))
        except (SQLAlchemyError, SMTPException) as e:
            db.session.rollback()
            flash(f"An error occurred: {e}", "warning")
            return redirect(url_for('main.all_secrets', user_id=current_user.id))

    return redirect(url_for('main.all_secrets', user_id=current_user.id))


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
            # Check if the current time is past the delete time
            if now > shared_secret.delete_at:
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
    
    
# Deleteing secret
@main.route('/delete/<int:sec_id>', methods=['GET', 'POST'])
@login_required
def delete_secret(sec_id):
    try:
        secret = db.get_or_404(Secret, sec_id)

        # Calculate the size of the secret's text (in bytes)
        text_size = len(secret.secret.encode('utf-8'))  # Convert the string to bytes and measure its length

        # Get the file size if the secret has a file
        file_size = 0
        if secret.file:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secret.file)
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)

                # Remove the file from the server
                os.remove(file_path)

        # Update the user's storage used
        total_size = text_size + file_size
        current_user.storage_used -= total_size

        # Commit the changes to update storage
        db.session.commit()

        # Delete the secret from the database
        db.session.delete(secret)
        db.session.commit()

        return redirect(url_for('main.all_secrets', user_id=secret.user_id))

    except IntegrityError:
        db.session.rollback()
        # Handle error (e.g., notify the user, log the error, etc.)
        return "An error occurred while deleting the secret.", 500
    

# User to delete his account
@main.route('/delete-account/<int:user_id>', methods=['GET', 'POST'])
@login_required
def delete_account(user_id):
    user = User.query.get(user_id)

    if user is None or user.id != current_user.id:
        flash("User not found or unauthorized action.", "danger")
        return redirect(url_for('main.update_profile'))
    
    # Only proceed if the user confirms deletion (no need for form submission now)
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Your account has been deleted. We're sad to see you go.", "success")
    return redirect(url_for('main.home'))


# Editing secret
@main.route('/update-secret/<int:secret_id>', methods=['POST'])
@login_required
def update_secret(secret_id):
    form = SecretForm()
    secret = db.get_or_404(Secret, secret_id)
    
    if form.validate_on_submit():
        # Encrypting the secret
        encrypted_secret = encrypt_secret(form.secret.data)

        # Calculate the size of the new text field (secret)
        new_text_size = len(encrypted_secret.encode('utf-8'))
        old_text_size = len(secret.secret.encode('utf-8'))

        # Check if any fields have changed
        title_changed = form.title.data != secret.title
        secret_changed = encrypted_secret != secret.secret
        file_changed = form.file.data and form.file.data.filename != secret.file

        # Initialize variables to track file size changes
        new_file_size = 0
        old_file_size = 0

        if file_changed:
            # Handle file upload and check storage
            file = form.file.data
            if file:
                filename = secure_filename(file.filename)
                new_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

                # Get the size of the new file
                new_file_size = len(file.read())
                file.seek(0)  # Reset file pointer after reading it

                # Get the size of the old file (if it exists)
                if secret.file:
                    old_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secret.file)
                    if os.path.exists(old_file_path):
                        old_file_size = os.path.getsize(old_file_path)

                # Save the new file
                file.save(new_file_path)
                secret.file = filename

                # Optionally delete the old file
                if old_file_size > 0 and os.path.exists(old_file_path):
                    os.remove(old_file_path)

        # Calculate the new storage used, accounting for both text and file changes
        storage_used = current_user.storage_used - old_text_size - old_file_size + new_text_size + new_file_size

        # Check if the new storage exceeds the user's plan limit
        if storage_used > current_user.plan.storage_limit:
            flash("You have exceeded your storage limit. Please delete some files or secrets.", "danger")
            return redirect(url_for('main.all_secrets', user_id=current_user.id))

        # Update the user's storage used
        current_user.storage_used = storage_used

        # Update the secret fields if they have changed
        if title_changed:
            secret.title = form.title.data
        if secret_changed:
            secret.secret = encrypted_secret

        # Commit changes only if something has changed
        if title_changed or secret_changed or file_changed:
            secret.date = date.today().strftime("%B %d, %Y")
            db.session.commit()

        return redirect(url_for('main.all_secrets', user_id=current_user.id))

    return render_template('edit_secret.html', form=form)


# Pricing page
@main.route('/pricing')
def pricing():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    session['from_pricing'] = True
    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))
    plan = db.session.execute(db.select(Plan).order_by(Plan.id)).scalars().all()
    return render_template('pricing.html', current_user=current_user, plans=plan)


# Payment methods
@main.route('/payment', methods=['GET', 'POST'])
def payment():
    # Retrieve user data from session
    registration_data = session.get('registration_data')
    if not registration_data:
        flash("Missing registration data. Please try again.", "danger")
        return redirect(url_for('main.pricing'))

    plan_id = registration_data.get('plan_id')
    plan = db.get_or_404(Plan, plan_id)
    
    amount = 0.1
    currency = plan.currency
    description = "Refund, saving card details"
    email = registration_data.get('email')
    phone_country_code = registration_data.get('country_code')
    phone_number = registration_data.get('phone')
    first_name = registration_data.get('username')

    try:
        # Create charge and handle 3D Secure or redirect to Tap payment page
        charge_response = create_charge(amount, currency, description, email, phone_country_code, phone_number, first_name, plan_id)
        
        if isinstance(charge_response, str):
            # If it's a URL (3D Secure), redirect
            return redirect(charge_response)

        if charge_response.get('status') == 'INITIATED':
            payment_url = charge_response.get('transaction', {}).get('url')
            if payment_url:
                return redirect(payment_url)

        flash("Failed to initiate payment. Please try again.", "danger")
        return redirect(url_for('main.pricing'))

    except Exception as e:
        flash(str(e), "danger")
        return redirect(url_for('main.pricing'))


# Payment completed
@main.route('/payment_complete')
def payment_complete():
    charge_id = request.args.get('tap_id')
    planId = request.args.get('plan_id')
    user_ip = get_ip()
    user_agent = get_user_agent()
    plan = db.get_or_404(Plan, planId)

    if charge_id:
        try:
            # Fetch the charge details to verify payment status
            charge_details = get_charge_details(charge_id)

            if charge_details['status'] == 'CAPTURED':
                registration_data = session.get('registration_data')
                user = None  # Define the user variable to hold either new or existing user
                
                # Check and handle user registration
                if registration_data:
                    existing_user = db.session.execute(
                        db.select(User).where(User.email == registration_data['email'])
                    ).scalar()
                    if existing_user:
                        login_user(existing_user)
                        user = existing_user  # Use existing user
                    else:
                        token = generate_token()
                        new_user = User(
                            email=registration_data['email'],
                            username=registration_data['username'],
                            password=registration_data['password'],
                            country_code=registration_data['country_code'],
                            phone=registration_data['phone'],
                            email_token = token
                        )
                        db.session.add(new_user)
                        db.session.commit()
                        login_user(new_user)
                        user = new_user  # Use new user
                
                if user:  # Ensure user (new or existing) is defined
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
                        user_id=user.id,  # Use user.id (new or existing)
                        plan_id=planId,
                        ip_address=user_ip,
                        user_agent=user_agent
                    )

                    history = HistoryPayment(
                        user_id=user.id,  # Use user.id (new or existing)
                        plan_id=planId,
                        amount=charge_details['amount'],
                        currency=charge_details['currency'],
                        payment_method=charge_details['source']['payment_type'],
                        payment_status=charge_details['status'],
                        transaction_id=charge_details['id'],
                        card_brand=charge_details['card']['brand'],
                        card_last_four=charge_details['card']['last_four'],
                        authorization_id=charge_details['transaction']['authorization_id']
                    )

                    if registration_data and not existing_user:
                        refund_response = refund_method(charge_id=charge_details["id"], 
                                                        amount=charge_details["amount"], 
                                                        currency=charge_details["currency"])
                        if refund_response and refund_response['status'] == 'REFUNDED':
                            new_payment.payment_status = refund_response['status']
                            new_payment.gateway_response_code = refund_response['gateway']['response']['code']
                            new_payment.gateway_response_message = refund_response['gateway']['response']['message']
                            new_payment.acquirer_response_code = refund_response['acquirer']['response']['code']
                            new_payment.acquirer_response_message = refund_response['acquirer']['response']['message']

                            history.payment_status = refund_response['status']

                    user.plan_id = planId

                    # Manage subscription details
                    if not user.trial_end_date or user.trial_end_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                        user.trial_start_date = datetime.now(timezone.utc)
                        user.trial_end_date = datetime.now(timezone.utc) + timedelta(days=14)
                        user.subscription_start_date = user.trial_end_date + timedelta(days=1)
                        user.subscription_end_date = user.subscription_start_date + timedelta(days=30)
                    else:
                        user.subscription_start_date = datetime.now(timezone.utc)
                        user.subscription_end_date = user.subscription_start_date + timedelta(days=30)

                    user.subscription_status = "active"
                    user.customer_id = charge_details['customer']['id']
                    user.card_id = charge_details['card']['id']

                    if 'payment_agreement' in charge_details:
                        user.payment_agreement_id = charge_details['payment_agreement']['id']

                    # Add payment to the session
                    db.session.add(new_payment)
                    
                    # Add history payment to the session
                    db.session.add(history)

                    # Commit all changes at once
                    db.session.commit()

                    # Send appropriate email and flash messages
                    if registration_data and not existing_user and not user.verification_sent:
                        # Send verification email after payment
                        send_verification_email(user.email, user.username, user.email_token)
                        user.verification_sent = True
                        db.session.commit()
                        # delete the session
                        session.pop('registration_data', None)

                        print(current_user.id)
                        return redirect(url_for("main.confirmation_pending", user=user.id)) 
                    else:
                        description = charge_details.get("description", "renewal")
                        
                        # Add the flash messages only if the user is not new or already verified
                        if description == "upgrade":
                            send_payment_email(user.email, user.username, plan.plan, plan.price, user.subscription_start_date, "upgrade", charge_details['card']['brand'], charge_details['card']['last_four'])
                            flash("Your plan has been successfully upgraded.", "success")
                        elif description == "renewal":
                            send_payment_email(user.email, user.username, plan.price, user.subscription_start_date, "renewal", charge_details['card']['brand'], charge_details['card']['last_four'])
                            flash("Your subscription has been successfully renewed.", "success")

                    return redirect(url_for('main.home'))

            else:
                flash(f"Payment failed: {charge_details.get('response', {}).get('message', 'Unknown error')}", "danger")
                if current_user.is_authenticated:
                    return redirect(url_for('main.billing'))
                else:
                    return redirect(url_for('main.pricing'))

        except Exception as e:
            flash(str(e), "danger")
            if current_user.is_authenticated:
                return redirect(url_for('main.billing'))
            else:
                return redirect(url_for('main.pricing'))

    return redirect(url_for('main.home'))



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
        db.session.commit()
        flash('Your email has been verified, login now', 'success')

    return redirect(url_for('main.login'))


# Notify registerer to check email for verification
@main.route('/confirmation-pending')
def confirmation_pending():
    user = request.args.get('user')
    return render_template('confirmation_pending.html', user=user)


# In case the user lost the time of the verification
@main.route('/resend-verification')
def resend_verification():
    user = request.args.get('user')
    is_user = db.get_or_404(User, user)
    # Logic to resend the verification email
    if is_user and not is_user.is_confirmed:
        token = generate_token()
        is_user.email_token = token
        db.session.commit()
        send_verification_email(is_user.email, is_user.username, token)
        flash('A new verification email has been sent.', 'info')
    else:
        flash('Your account is already confirmed or you are not logged in.', 'warning')
    return redirect(url_for('main.confirmation_pending'))


# Billing page
@main.route('/billing', methods=['GET'])
@login_required
def billing():
    form = PlanUpgradeForm()
    if current_user.is_authenticated and not current_user.is_confirmed:
        return redirect(url_for('main.confirmation_pending'))
    user = User.query.get(current_user.id)
    history_payment = HistoryPayment.query.filter_by(user_id=user.id).order_by(HistoryPayment.payment_date.desc()).all()
    plans = Plan.query.order_by(Plan.price).all()

    # Populate form choices using the helper function
    populate_plan_choices(form, user)

    return render_template('billing.html', user=user, payments=history_payment, form=form, plan=plans)

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
        email = current_user.email
        phone_country_code = current_user.country_code
        phone_number = current_user.phone
        first_name = current_user.username

        try:
            if payment_method == 'saved_card':
                card_id = current_user.card_id
                payment_response = recurring_payment(
                    current_user.customer_id, card_id, get_ip(), 
                    current_user.payment_agreement_id, amount, currency, description
                )
            else:
                # Redirect user to TAP hosted payment page for new card payment
                payment_url = create_charge(
                    amount, currency, description, email, phone_country_code, 
                    phone_number, first_name, user_plan.id
                )
                return redirect(payment_url)  # Redirecting to the TAP payment page

            if payment_response['status'] == 'CAPTURED':
                flash("Payment was successful!", "success")
                current_user.subscription_end_date = current_date + timedelta(days=30) if user_plan.billing_cycle == 'monthly' else current_user.subscription_end_date
                current_user.subscription_status = "active"
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
    

    if form.validate_on_submit():
        selected_plan_id = form.plan_id.data
        plan = db.get_or_404(Plan, selected_plan_id)
        amount = plan.price
        currency = plan.currency
        description = "upgrade"
        email = current_user.email
        # phone_country_code = current_user.country_code
        # phone_number = current_user.phone
        # first_name = current_user.username

        try:
            card_id = current_user.card_id
            payment_response = recurring_payment(
                current_user.customer_id, card_id, get_ip(), 
                current_user.payment_agreement_id, amount, currency, description
            )
            if payment_response['status'] == 'CAPTURED':
                flash(f"Upgrading for {plan.plan} succeeded!", "success")
                current_user.subscription_end_date = current_date + timedelta(days=30) if plan.billing_cycle == 'monthly' else current_user.subscription_end_date
                current_user.subscription_status = "active"
                current_user.plan_id = plan.id
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
    return render_template('terms.html')


@main.route('/about-us')
def about():
    return render_template('about.html')


@main.route('/contact-us')
def contact():
    return render_template('contact.html')


@main.route('/privacy-policy')
def privacy():
    return render_template('privacy.html')


@main.route('/cookie-policy')
def cookie():
    return render_template('cookie.html')

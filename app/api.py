from flask import Blueprint, request, jsonify, current_app, url_for, abort, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from . import db, blacklist
from .models import User, LoginHistory, Secret, SharedSecret, Payment, Plan
from .utils import generate_token, send_verification_email, decrypt_secret, is_encrypted, decrypt_secrets, encrypt_secret, get_subscription_details, get_unique_title, convert_utc_to_local, subscription_ended, change_subscription_plan, reset_password_email, cancel_subscription, generate_access_token, contact_email, verify_transaction, generate_apple_jwt, parse_apple_transaction
from datetime import datetime, timedelta, timezone, date
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, get_jwt
from sqlalchemy.orm import joinedload
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename
import mimetypes, uuid, traceback, time, json, os, requests
import jwt

api = Blueprint('api', __name__, url_prefix='/api')

########################################### Protecting routes ###########################################

# === API Protection ===
@api.route('/protected')
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify(logged_in_as=current_user), 200

########################################### PRICING API ###########################################

# === Pricing ===
@api.route('/pricing', methods=['GET'])
def api_pricing():
    plans = db.session.execute(db.select(Plan).order_by(Plan.id)).scalars().all()

    plans_data = [
        {
            "id": plan.id,
            "name": plan.plan,
            "price": plan.price,
            "currency": plan.currency,
            "billing_cycle": plan.billing_cycle,
            "storage_limit_mb": plan.storage_limit,
            "description": plan.description,
            "apple_product_id": plan.apple_product_id,
        }
        for plan in plans
    ]

    return jsonify({"plans": plans_data}), 200

########################################### PAYMENT PROCESS API ###########################################

# === Payment Info ===
@api.route('/payment-info', methods=['GET'])
@jwt_required()
def api_payment_info():
    user_id = get_jwt_identity()
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    client_id = os.environ.get("PAYPAL_SENDBOX_CLIENT_ID")
    paypal_plan_id = json.loads(user.plan.paypal_plan_id)[0]

    if not client_id or not paypal_plan_id:
        return jsonify({"status": "error", "message": "Missing PayPal config"}), 400

    return jsonify({
        "client_id": client_id,
        "paypal_plan_id": paypal_plan_id,
        "plan_name": user.plan.name,
        "price": user.plan.price
    }), 200

# === Subscription Process ===
@api.route('/process-subscription', methods=['POST'])
@jwt_required()
def api_process_subscription():
    user_id = get_jwt_identity()
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json()
    subscription_id = data.get('subscription_id')

    if not subscription_id:
        return jsonify({"status": "error", "message": "Missing subscription_id"}), 400

    try:
        subscription_data = get_subscription_details(subscription_id)
        status = subscription_data.get("status", "UNKNOWN")
        start_time = convert_utc_to_local(subscription_data.get("start_time"), user.time_zone)
        billing_info = subscription_data.get("billing_info", {})
        subscriber = subscription_data.get("subscriber", {})

        trial_end = None
        next_billing_date = None
        failed_payments = billing_info.get("failed_payments_count", 0)

        for cycle in billing_info.get("cycle_executions", []):
            if cycle["sequence"] == 1 and cycle["tenure_type"] == "TRIAL":
                trial_end = billing_info.get("next_billing_time")
            elif (cycle["sequence"] == 1 or cycle["sequence"] == 2) and cycle["tenure_type"] == "REGULAR":
                next_billing_date = billing_info.get("next_billing_time")

        # Update DB
        user.paypal_subscription_id = subscription_id
        user.paypal_payer_id = subscriber.get("payer_id")
        user.subscription_status = status
        user.trial_start_date = start_time
        user.trial_end_date = convert_utc_to_local(trial_end, user.time_zone)
        user.subscription_start_date = start_time
        user.next_billing_date = convert_utc_to_local(next_billing_date, user.time_zone)
        user.fialed_payments = failed_payments
        user.updated_at = convert_utc_to_local(datetime.now(), user.time_zone)
        user.status = None

        db.session.commit()

        return jsonify({
            "status": "success",
            "subscription_status": status,
            "trial_end_date": trial_end,
            "next_billing_date": next_billing_date
        }), 200

    except requests.exceptions.RequestException as e:
        print("Error:", e)
        return jsonify({"status": "error", "message": "Failed to fetch subscription details"}), 500


########################################### REGISTRATION API ###########################################

# === Register ===
@api.route('/register', methods=['POST'])
def register_api():
    data = request.get_json()

    required_fields = ['username', 'email', 'password', 'confirm_password', 'code', 'phone', 'plan_id']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    username = data['username'].lower()
    email = data['email'].lower().strip()
    password = data['password']
    confirm_password = data['confirm_password']
    country_code = data['code']
    phone = data['phone']
    plan_id = data['plan_id']

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    existing_user = db.session.execute(db.select(User).where(User.email == email)).scalar()
    existing_user_name = db.session.execute(db.select(User).where(User.username == username)).scalar()

    if existing_user:
        return jsonify({'error': 'Email already exists. Please log in instead.'}), 409
    if existing_user_name:
        return jsonify({'error': 'Username already in use. Please choose another.'}), 409

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
    token = generate_token()

    new_user = User(
        email=email,
        username=username,
        password=hashed_password,
        country_code=country_code,
        phone=phone,
        plan_id=plan_id,
        email_token=token
    )

    db.session.add(new_user)
    try:
        db.session.commit()
        send_verification_email(new_user.email, new_user.username, new_user.email_token)
        return jsonify({'message': 'User registered successfully. Please check your email to confirm your account.'}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Registration error: {e}")
        return jsonify({'error': 'An error occurred during registration. Please try again.'}), 500
    

# === User's timezone ===
@api.route('/update-timezone', methods=['POST'])
@jwt_required()
def api_update_timezone():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()
    time_zone = data.get("time_zone")
    if not time_zone:
        return jsonify({"error": "Time zone not provided"}), 400

    user.time_zone = time_zone
    db.session.commit()

    return jsonify({"message": "Time zone updated successfully"}), 200


########################################### LOGIN API ###########################################

@api.route('/login', methods=['POST'])
def login_api():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing JSON body'}), 400

    user_input = data.get('user')
    password = data.get('password')

    if not user_input or not password:
        return jsonify({'error': 'Username/email and password are required'}), 400

    user = db.session.execute(
        db.select(User).where(
            (User.email == user_input.lower().strip()) | 
            (User.username == user_input.lower())
        )
    ).scalar()

    if not user:
        return jsonify({'error': 'User does not exist'}), 404

    if not check_password_hash(user.password, password):
        return jsonify({'error': 'Incorrect password'}), 401

    if not user.is_confirmed:
        return jsonify({'error': 'Email not confirmed'}), 403

    ip_address = request.remote_addr
    login_history = LoginHistory(
        user_id=user.id, 
        login_time=datetime.now(timezone.utc), 
        ip_address=ip_address
    )
    db.session.add(login_history)
    db.session.commit()

    access_token = create_access_token(identity=str(user.id), expires_delta=timedelta(hours=24))

    return jsonify({
        'access_token': access_token,
        'user_id': user.id
    }), 200

########################################### LOGOUT API ###########################################

@api.route('/logout', methods=['POST'])
@jwt_required()
def api_logout():
    jti = get_jwt()["jti"]
    blacklist.add(jti)
    return jsonify({"msg": "Logged out successfully"}), 200

########################################### DASHBOARD API ###########################################

@api.route('/dashboard', methods=['GET'])
@jwt_required()
def dashboard_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Redirect new users to payment
    if user.status == "new":
        token = generate_access_token(
            user_id=user.id,
            secret_key=current_app.config['JWT_SECRET_KEY']
        )

        charge_url = url_for('main.payment', token=token, _external=True)

        return jsonify({
            'error': 'Payment required',
            'payment_token': token,
            'redirect_url': charge_url
        }), 402

    secrets_count = Secret.query.filter_by(user_id=user.id).count()
    last_login = user.login_history[-1].login_time if user.login_history else None

    plan_name = user.plan.plan if user.plan else 'INACTIVE'
    next_billing_date = user.next_billing_date.strftime('%Y-%m-%d') if user.next_billing_date else 'INACTIVE'
    
    storage_used_mb = round(user.storage_used / (1024 * 1024), 2)
    storage_limit_mb = round(user.plan.storage_limit / (1024 * 1024), 2) if user.plan else 0
    storage_percentage = (
        round((user.storage_used / user.plan.storage_limit) * 100, 2)
        if user.plan and user.plan.storage_limit else 0
    )

    subscription_approval = get_subscription_details(user.paypal_subscription_id)
    if not subscription_approval:
        approval_link = "pass"
    else:
        if subscription_approval.get("status") == "APPROVAL_PENDING":
            approval_link = next(
                (link["href"] for link in subscription_approval.get("links", []) if link["rel"] == "approve"),
                "pass"
            )
        else:
            approval_link = "pass"

    return jsonify({
        "username": user.username,
        "email": user.email,
        "plan": plan_name,
        "plan_id": user.plan_id,
        "next_billing_date": next_billing_date,
        "secrets_count": f"{secrets_count}/10" if plan_name == 'Basic' else secrets_count,
        "last_login": last_login.strftime('%Y-%m-%d %H:%M:%S') if last_login else None,
        "storage_used_mb": storage_used_mb,
        "storage_limit_mb": storage_limit_mb,
        "storage_percentage": storage_percentage,
        "approval_link": approval_link
    }), 200


########################################### PUBLIC SECRETS API ###########################################

@api.route('/public-secrets', methods=['GET'])
def public_secrets_api():
    now = datetime.now()
    current_date = now.date()
    current_time = now.time()

    shared_secret = db.session.execute(
        db.select(SharedSecret)
        .where(
            SharedSecret.public == True,
            (SharedSecret.time_period != None) | (SharedSecret.time_to_send != None)
        )
        .options(joinedload(SharedSecret.user), joinedload(SharedSecret.secret))
    ).scalars().all()

    for secret in shared_secret:
        latest_login = db.session.execute(
            db.select(LoginHistory.login_time)
            .where(LoginHistory.user_id == secret.user_id)
            .order_by(desc(LoginHistory.login_time))
            .limit(1)
        ).scalar_one_or_none()

        if latest_login and (secret.last_login is None or latest_login > secret.last_login):
            secret.last_login = latest_login
            if secret.period:
                try:
                    secret.time_period = latest_login + timedelta(days=int(secret.period))
                except ValueError:
                    continue

        if secret.date_to_send == current_date and secret.time_to_send == current_time:
            date_time = datetime.combine(secret.date_to_send, secret.time_to_send)
        else:
            date_time = None

        public_secret = SharedSecret.query.filter_by(id=secret.id).first()
        if public_secret:
            if secret.time_period:
                public_secret.share_date = secret.time_period
            elif date_time:
                public_secret.share_date = date_time

    db.session.commit()

    public_secrets =  SharedSecret.query.filter(
        SharedSecret.share_date <= now
    ).order_by(SharedSecret.share_date.desc()).all()

    upload_folder = current_app.config['UPLOAD_FOLDER']
    for ps in public_secrets[:]:
        if ps.file:
            file_path = os.path.join(upload_folder, ps.file)
            if not os.path.exists(file_path):
                db.session.delete(ps)
                public_secrets.remove(ps)

    db.session.commit()

    decrypted_secrets = []
    for ps in public_secrets:
        if ps.snapshot_secret:
            secret_text = decrypt_secret(ps.snapshot_secret) if is_encrypted(ps.snapshot_secret) else ps.snapshot_secret
        else:
            secret_text = ""

        decrypted_secrets.append({
            "id": ps.id,
            "title": ps.title,
            "secret": secret_text,
            "display_time": ps.share_date.strftime('%H:%M') if ps.share_date else '',
            "file": ps.file,
            "username": ps.username if ps.username else 'Unknown'
        })

    return jsonify({'public_secrets': decrypted_secrets}), 200


########################################### ALL SECRETS API ###########################################

# === List of all secerts for the user ===
@api.route('/all-secrets', methods=['GET'])
@jwt_required()
def all_secrets_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, user_id)

    if not user or not user.is_confirmed:
        return jsonify({'error': 'User not found or not confirmed'}), 403

    # Fetch all secrets for the user
    query = db.select(Secret).where(Secret.user_id == user.id)
    user_secrets = db.session.execute(query.order_by(Secret.date.desc())).scalars().all()

    # Reset storage if no secrets
    if not user_secrets:
        user.storage_used = 0
        db.session.commit()

    # Decrypt user secrets
    decrypted_user_secrets = decrypt_secrets(user_secrets)

    # Serialize user secrets
    user_secrets_data = [{
        'id': s.id,
        'title': s.title,
        'secret': s.secret,
        'date': s.date.isoformat(),
        'filename': s.file,
    } for s in decrypted_user_secrets]

    # Fetch shared secrets
    shared_secrets = db.session.execute(
        db.select(SharedSecret)
        .options(db.joinedload(SharedSecret.secret))
        .where(SharedSecret.user_id == user.id)
        .order_by(SharedSecret.date_to_send.desc())
    ).scalars().all()

    shared_secrets_data = []
    for shared in shared_secrets:
        if shared.snapshot_secret and is_encrypted(shared.snapshot_secret):
            shared.snapshot_secret = decrypt_secret(shared.snapshot_secret)

        if shared.date_to_send and shared.time_to_send:
            combined = datetime.combine(shared.date_to_send, shared.time_to_send)
            status = 'shared' if combined <= datetime.now() else 'pending'
        else:
            status = 'shared' if shared.received else 'pending'

        shared_secrets_data.append({
            'id': shared.id,
            'public': bool(shared.public),
            'email': shared.email,
            'title': shared.title if shared.title else '',
            'secret': shared.snapshot_secret if shared.snapshot_secret else '',
            'file': shared.file if shared.file else None,
            'date_to_send': shared.date_to_send.isoformat() if shared.date_to_send else None,
            'time_to_send': shared.time_to_send.isoformat() if shared.time_to_send else None,
            "share_date": shared.share_date.isoformat() if shared and shared.share_date else None,
            "time_period": shared.time_period.isoformat() if shared.time_period else None,
            'status': status,
        })

    return jsonify({
        'user_secrets': user_secrets_data,
        'shared_secrets': shared_secrets_data
    }), 200

# === Search and Filter === 
@api.route('/search-secrets', methods=['POST'])
@jwt_required()
def search_secrets_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify({'error': 'User not found'}), 403

    data = request.get_json()
    search_term = data.get('search')
    date_filter = data.get('date_filter')
    alpha_filter = data.get('alpha_filter')

    query = db.select(Secret).where(Secret.user_id == user.id)

    if search_term:
        search_pattern = f"{search_term}%"
        query = query.where(Secret.title.ilike(search_pattern))

    if date_filter:
        query.order_by(Secret.date.desc() if date_filter == "latest" else Secret.date.asc())
    if alpha_filter:
        query = query.order_by(Secret.title.asc() if alpha_filter == "A-Z" else Secret.title.desc())

    secrets = db.session.execute(query).scalars().all()
    decrypted_secrets = decrypt_secrets(secrets)

    secret_list = [{
        'id': s.id,
        'title': s.title,
        'secret': s.secret,
        'date': s.date.isoformat(),
        'filename': s.file,
    } for s in decrypted_secrets]

    return jsonify({'secrets': secret_list}), 200

# === Add secret === 
@api.route('/add-secret', methods=['POST'])
@jwt_required()
def add_secret_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify({'success': False, 'error': 'User not authorized'}), 403

    data = request.get_json()
    title = data.get('title', '').strip()
    secret_text = data.get('secret', '').strip()
    filename = data.get('filename')  # optional

    # Secret limit check (e.g., 10 secrets for Basic plan)
    secret_limit = 10
    user_secrets = db.session.execute(
        db.select(Secret).where(Secret.user_id == user.id)
    ).scalars().all()

    if user.plan.plan == 'Basic' and len(user_secrets) >= secret_limit:
        return jsonify(success=False, error=f"You have reached the maximum limit of {secret_limit} secrets for your Basic plan."), 403

    # Require at least secret or file
    if not secret_text and not filename:
        return jsonify(success=False, error="Please provide a secret or upload a file."), 400

    # Storage size check
    storage_limit = user.plan.storage_limit
    encrypted_secret = encrypt_secret(secret_text)
    secret_size = len(encrypted_secret.encode('utf-8'))

    if user.storage_used + secret_size > storage_limit:
        return jsonify(success=False, error=f"Adding this secret will exceed your {user.plan.plan} plan's storage limit."), 403

    try:
        # Generate unique title
        unique_title = get_unique_title(title or "Untitled", user.id)

        # Update storage usage
        user.storage_used += secret_size

        new_secret = Secret(
            title=unique_title,
            secret=encrypted_secret,
            file=filename,
            date=date.today().strftime("%Y-%m-%d"),
            user_id=user.id,
        )
        db.session.add(new_secret)
        db.session.commit()

        return jsonify(
            success=True,
            title=new_secret.title,
            date=new_secret.date,
            flash_message="New secret has been added successfully."
        ), 200

    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="An error occurred while saving your secret. Please try again."), 500
    
# === Uploading a file ===
@api.route('/upload', methods=['POST'])
@jwt_required()
def upload_file_api():
    try:
        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id))

        if not user:
            return jsonify(error='User not authorized'), 401

        if 'file' not in request.files:
            return jsonify(error='No file part in the request'), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify(error='No selected file'), 400

        # Read file size to check against user's limit
        file_bytes = file.read()
        file_size = len(file_bytes)
        file.seek(0)

        if user.storage_used + file_size > user.plan.storage_limit:
            return jsonify(error='Exceeds storage limit'), 403

        # Generate unique filename
        original_filename = secure_filename(file.filename)
        unique_prefix = uuid.uuid4().hex
        filename = f"{unique_prefix}_{original_filename}"

        # Save path
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)

        # Save the file
        file.save(file_path)

        # Update user storage
        user.storage_used += file_size
        db.session.commit()

        # Return result
        mime, _ = mimetypes.guess_type(filename)
        return jsonify(
            message='File successfully uploaded',
            filename=filename,
            mimetype=mime
        ), 200

    except Exception as e:
        print("[❌ Upload Error]", str(e))
        return jsonify(error='Server error during upload'), 500
    
# === Route to fetch the user's current storage usage and limit, requiring login ===
@api.route('/get-storage-info', methods=['GET'])
@jwt_required()
def get_storage_info_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify(error='User not authenticated'), 401
    
    try:
        return jsonify({
            'used': user.storage_used,
            'total': user.plan.storage_limit
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching storage info: {e}")
        return jsonify(error='Failed to retrieve storage info'), 500

# === Editing Secret ===
@api.route('/update-secret/<int:secret_id>', methods=['PUT'])
@jwt_required()
def update_secret_api(secret_id):
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if not user:
        return jsonify(success=False, error="User not found."), 404

    secret = Secret.query.filter_by(id=secret_id, user_id=user.id).first()
    if not secret:
        return jsonify(success=False, error="Secret not found."), 404

    # Accept both JSON and multipart/form-data (for file upload)
    form_data = request.form or request.json
    file = request.files.get('file')

    title = form_data.get('title', '').strip()
    secret_text = form_data.get('secret', '').strip()

    if not title or not secret_text:
        return jsonify(success=False, error="Title and secret are required."), 400

    try:
        encrypted_secret = encrypt_secret(secret_text)
        new_text_size = len(encrypted_secret.encode('utf-8'))
        old_text_size = len(secret.secret.encode('utf-8'))

        upload_folder = current_app.config['UPLOAD_FOLDER']
        new_file_size = 0
        old_file_size = 0
        file_changed = False

        if file:
            filename = secure_filename(file.filename)
            if filename != secret.file:
                file_changed = True
                new_file_path = os.path.join(upload_folder, filename)

                file_size = file.seek(0, os.SEEK_END)
                new_file_size = file_size
                file.seek(0)

                old_file_path = os.path.join(upload_folder, secret.file) if secret.file else None
                old_file_size = os.path.getsize(old_file_path) if old_file_path and os.path.exists(old_file_path) else 0

                new_storage_used = user.storage_used - old_text_size - old_file_size + new_text_size + new_file_size
                if new_storage_used > user.plan.storage_limit:
                    return jsonify(success=False, error="Exceeds storage limit."), 403

                file.save(new_file_path)

                if old_file_path and os.path.exists(old_file_path):
                    os.remove(old_file_path)

                secret.file = filename
        else:
            old_file_size = os.path.getsize(os.path.join(upload_folder, secret.file)) if secret.file else 0

        total_new_storage = user.storage_used - old_text_size - old_file_size + new_text_size + new_file_size
        if total_new_storage > user.plan.storage_limit:
            return jsonify(success=False, error="Exceeds storage limit."), 403

        if title != secret.title:
            secret.title = title
        if encrypted_secret != secret.secret:
            secret.secret = encrypted_secret

        user.storage_used = total_new_storage
        secret.date = date.today().strftime("%Y-%m-%d")
        db.session.commit()

        decrypted_secret = decrypt_secret(secret.secret)

        return jsonify(
            success=True,
            flash_message="Secret updated successfully!",
            secret={
                "id": secret.id,
                "title": secret.title,
                "secret": decrypted_secret,
                "file": secret.file,
                "date": secret.date.strftime("%Y-%m-%d"),
                "file_preview": secret.file.endswith(('.png', '.jpg', '.jpeg', '.gif')) if secret.file else False,
            }
        ), 200

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=str(e)), 500
    
# === Deleting secret === 
@api.route('/delete-secret/<int:sec_id>', methods=['DELETE'])
@jwt_required()
def delete_secret_api(sec_id):
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify(error='User not authenticated'), 401

    try:
        secret = db.get_or_404(Secret, sec_id)

        # Ensure the user owns the secret
        if secret.user_id != user.id:
            return jsonify(error='Unauthorized access to this secret'), 403

        # Calculate size of secret text
        text_size = len(secret.secret.encode('utf-8'))
        file_size = 0

        # Handle file deletion if exists
        if secret.file:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secret.file)

            is_shared_publicly = db.session.execute(
                db.select(SharedSecret).filter_by(file=secret.file)
            ).scalar()

            if os.path.exists(file_path) and not is_shared_publicly:
                file_size = os.path.getsize(file_path)
                os.remove(file_path)

        # Update user's storage
        total_size = text_size + file_size
        user.storage_used = max(0, user.storage_used - total_size)

        db.session.delete(secret)
        db.session.commit()

        return jsonify(success=True, message='Secret deleted successfully'), 200

    except IntegrityError:
        db.session.rollback()
        return jsonify(error='A database error occurred while deleting the secret'), 500
    except Exception as e:
        current_app.logger.error(f"Error deleting secret {sec_id}: {e}")
        return jsonify(error='An unexpected error occurred'), 500
    

# === Deleting shared secret === 
@api.route('/delete-shared-secret/<int:sec_id>', methods=['DELETE'])
@jwt_required()
def delete_shared_secret_api(sec_id):
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify(error='User not authenticated'), 401

    try:
        secret = db.get_or_404(SharedSecret, sec_id)

        db.session.delete(secret)
        db.session.commit()

        return jsonify(success=True, message='Secret deleted successfully'), 200

    except IntegrityError:
        db.session.rollback()
        return jsonify(error='A database error occurred while deleting the secret'), 500
    except Exception as e:
        current_app.logger.error(f"Error deleting secret {sec_id}: {e}")
        return jsonify(error='An unexpected error occurred'), 500


# === Sharing Secret === 
@api.route('/share-secret', methods=['POST'])
@jwt_required()
def share_secret_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if not user:
        return jsonify(success=False, message="User not found"), 404

    data = request.get_json()
    secret_id = data.get("secret_id")
    if not secret_id:
        return jsonify(success=False, message="Missing 'secret_id'"), 400

    secret = Secret.query.filter_by(id=secret_id, user_id=user.id).first()
    if not secret:
        return jsonify(success=False, message="Secret not found"), 404

    responses = []

    # === LAST LOGIN SHARING ===
    if data.get("date_period"):
        date_period = int(data["date_period"])
        emails = [e.strip() for e in data.get("email_login", "").split(",") if e.strip()]
        public = data.get("public_login", False)
        confirm_deletion = data.get("public_confirm_deletion", False)

        if not emails and not public:
            return jsonify(success=False, message="You must provide emails or enable public sharing for last login"), 400
        
        last_login_entry = LoginHistory.query.filter_by(user_id=user.id).order_by(LoginHistory.login_time.desc()).first()
        if not last_login_entry:
            return jsonify(success=False, message="Last login time not found"), 400

        last_login = last_login_entry.login_time
        time_period = last_login + timedelta(days=date_period)
        token = generate_token() if emails else None

        shared_secret = SharedSecret(
            user_id=user.id,
            secret_id=secret_id,
            email=emails or None,
            username=user.username,
            public=public,
            title=secret.title,
            snapshot_secret=secret.secret,
            file=secret.file,
            last_login=last_login,
            period=date_period,
            time_period=time_period,
            public_delete_confirm=confirm_deletion,
            token=token,
            received=False,
            share_date=time_period
        )
        db.session.add(shared_secret)
        db.session.commit()

        responses.append(f"Shared via last login — will activate after {date_period} day(s) from last login.")

    # === SCHEDULED SHARING ===
    if data.get("date") and data.get("time"):
        emails = [e.strip() for e in data.get("email_scheduled", "").split(",") if e.strip()]
        public = data.get("public_scheduled", False)
        confirm_deletion = data.get("scheduled_confirm_deletion", False)

        if not emails and not public:
            return jsonify(success=False, message="You must provide emails or enable public sharing for scheduled sharing"), 400

        try:
            date_str = data["date"]
            time_str = data["time"]
            local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify(success=False, message="Invalid date/time format. Expected YYYY-MM-DD and HH:MM"), 400

        # Convert to UTC
        share_datetime_utc = convert_utc_to_local(local_dt, user.time_zone)
        date_to_send = share_datetime_utc
        time_to_send = share_datetime_utc
        token = generate_token() if emails else None

        shared_secret = SharedSecret(
            user_id=user.id,
            secret_id=secret_id,
            email=emails or None,
            username=user.username,
            public=public,
            title=secret.title,
            snapshot_secret=secret.secret,
            file=secret.file,
            date_to_send=date_to_send,
            time_to_send=time_to_send,
            schedule_delete_confirm=confirm_deletion,
            token=token,
            received=False,
            share_date=share_datetime_utc
        )
        db.session.add(shared_secret)
        db.session.commit()

        responses.append(f"Scheduled to share on {date_str} at {time_str}")

    if not responses:
        return jsonify(success=False, message="No valid sharing configuration found."), 400

    # Get the latest shared secret just created
    latest_shared = db.session.query(SharedSecret)\
        .filter_by(user_id=user.id, secret_id=secret_id)\
        .order_by(SharedSecret.id.desc())\
        .first()

    # Decrypt if needed
    if latest_shared and latest_shared.snapshot_secret and is_encrypted(latest_shared.snapshot_secret):
        latest_shared.snapshot_secret = decrypt_secret(latest_shared.snapshot_secret)

    # Calculate status
    if latest_shared.date_to_send and latest_shared.time_to_send:
        combined = datetime.combine(latest_shared.date_to_send, latest_shared.time_to_send)
        status = 'shared' if combined <= datetime.now() else 'pending'
    else:
        status = 'shared' if latest_shared.received else 'pending'

    # Return the secret info
    return jsonify({
        "success": True,
        "messages": responses,
        "secret": {
            "id": latest_shared.id,
            "public": bool(latest_shared.public),
            "email": latest_shared.email,
            "title": latest_shared.title or '',
            "secret": latest_shared.snapshot_secret or '',
            "file": latest_shared.file or None,
            "date_to_send": latest_shared.date_to_send.isoformat() if latest_shared.date_to_send else None,
            "time_to_send": latest_shared.time_to_send.isoformat() if latest_shared.time_to_send else None,
            "share_date": latest_shared.share_date.isoformat() if latest_shared.share_date else None,
            "time_period": latest_shared.time_period.isoformat() if latest_shared.time_period else None,
            "status": status
        }
    }), 200


########################################### PROFILE API ###########################################

# === Profile === 
@api.route('/profile', methods=['GET'])
@jwt_required()
# @subscription_ended(api=True)
def api_profile():
    try:
        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id))

        if not user:
            return jsonify(success=False, error="User not found."), 404

        if request.method == 'GET':
            login_history = LoginHistory.query.filter_by(user_id=user.id).all()
            last_login = LoginHistory.query.filter_by(user_id=user.id).order_by(LoginHistory.login_time.desc()).first()

            next_billing_date = user.next_billing_date.strftime('%Y-%m-%d') if user.next_billing_date else 'INACTIVE'

            storage_used_mb = round(user.storage_used / (1024 * 1024), 2)
            storage_limit_mb = round(user.plan.storage_limit / (1024 * 1024), 2) if user.plan else 0

            return jsonify(
                success=True,
                user={
                    "username": user.username,
                    "email": user.email,
                    "phone": user.phone,
                    "country_code": user.country_code,
                    "plan": user.plan.plan if user.plan else "Free",
                    "subscription_status": user.subscription_status,
                    "next_bill": next_billing_date,
                    "storage_used": storage_used_mb,
                    "storage_limit": storage_limit_mb,
                },
                login_history=[
                    {
                        "ip": log.ip_address,
                        # "user_agent": log.user_agent,
                        "login_time": log.login_time.strftime("%Y-%m-%d %H:%M:%S")
                    } for log in login_history
                ],
                last_login={
                    "ip": last_login.ip_address,
                    # "user_agent": last_login.user_agent,
                    "login_time": last_login.login_time.strftime("%Y-%m-%d %H:%M:%S")
                } if last_login else None
            ), 200


    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify(success=False, error=f"Server error: {str(e)}"), 500

# === Updating Phone ===
@api.route('/update-phone', methods=['GET', 'PUT'])
@jwt_required()
def api_update_phone():
    try:
        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id))

        if not user:
            return jsonify(success=False, error="User not found."), 404

        if request.method == 'GET':
            return jsonify(
                success=True,
                user={

                    "phone": user.phone,
                    "country_code": user.country_code,

                }), 200
        
        elif request.method == 'PUT':
            data = request.get_json()
            phone = data.get('phone', '').strip()
            code = data.get('country_code', '').strip()

            if not phone or not code:
                return jsonify(success=False, error="Phone, and country code are required."), 400

            user.phone = phone
            user.country_code = code

            db.session.commit()

            return jsonify(success=True, message="Phone number updated successfully!"), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify(success=False, error=f"Server error: {str(e)}"), 500
        

# === Changing password ===
@api.route('/change-password', methods=['PATCH'])
@jwt_required()
# @subscription_ended(api=True)
def api_change_password():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify(success=False, error="User not found."), 404
    
    data = request.get_json()

    if not data:
        return jsonify(success=False, error="Missing JSON data."), 400

    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()

    if not current_password or not new_password or not confirm_password:
        return jsonify(success=False, error="All password fields are required."), 400

    if not check_password_hash(user.password, current_password):
        return jsonify(success=False, error="Current password is incorrect."), 401

    if new_password != confirm_password:
        return jsonify(success=False, error="New passwords do not match."), 400

    try:
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=16)
        db.session.commit()
        return jsonify(success=True, message="Password changed successfully!"), 200
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=str(e)), 500

# === Delete Account ===
@api.route('/delete-account', methods=['DELETE'])
@jwt_required()
def api_delete_account():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))

    if user is None:
        return jsonify(success=False, error="User not found."), 404

    try:
        # Cancel PayPal subscription
        if user.paypal_subscription_id:
            cancel_subscription(user.paypal_subscription_id, "Deleting my account.")
            time.sleep(5)

        # Delete the user account
        db.session.delete(user)
        db.session.commit()

        return jsonify(success=True, message="Your account has been deleted!"), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(e)
        return jsonify(success=False, error="Failed to delete account. Please try again."), 500


########################################### BILLING API ###########################################
# === Retrieving plan === 
@api.route('/plan', methods=['GET'])
@jwt_required()
def api_plan():
    try:
        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id))

        if not user:
            return jsonify(success=False, error="User not found."), 404

        if request.method == 'GET':
            next_billing_date = user.next_billing_date.strftime('%Y-%m-%d') if user.next_billing_date else 'INACTIVE'
            storage_used_mb = round(user.storage_used / (1024 * 1024), 2)
            storage_limit_mb = round(user.plan.storage_limit / (1024 * 1024), 2) if user.plan else 0

            return jsonify(
                success=True,
                plan={
                    "plan_id": user.plan.id,
                    "plan": user.plan.plan if user.plan else "Free",
                    "bill_cycle": user.plan.billing_cycle,
                    "subscription_status": user.subscription_status,
                    "next_bill": next_billing_date,
                    "storage_used": storage_used_mb,
                    "storage_limit": storage_limit_mb,
                    "features": user.plan.description,
                    "apple_product_id": user.plan.apple_product_id,
                }
            ), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify(success=False, error=f"Server error: {str(e)}"), 500

# === Billing ===
@api.route('/billing', methods=['GET'])
@jwt_required()
@subscription_ended(api=True)
def billing_api():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))

    if not user:
        return jsonify(success=False, error="User not found."), 404

    # Fetch payment history and available plans
    history_payment = Payment.query.filter_by(user_id=user.id).order_by(Payment.payment_date.desc()).all()
    plans = Plan.query.order_by(Plan.price).all()

    # Serialize payment history
    payment_data = [{
        'id': payment.id,
        'amount': payment.amount,
        'status': payment.status,
        'payment_date': payment.payment_date.strftime('%Y-%m-%d %H:%M:%S'),
        'transaction_id': payment.transaction_id,
        'plan_name': payment.plan.name if payment.plan else None
    } for payment in history_payment]

    # Serialize plan details
    plans_data = [{
        'id': plan.id,
        'name': plan.name,
        'price': plan.price,
        'storage_limit': plan.storage_limit,
        'features': plan.features
    } for plan in plans]

    # Serialize user subscription status
    billing_info = {
        'username': user.username,
        'subscription_status': user.subscription_status,
        'next_billing_date': user.next_billing_date.strftime('%Y-%m-%d') if user.next_billing_date else None,
        'plan_id': user.plan_id,
        'plan_name': user.plan.name if user.plan else None
    }

    return jsonify(success=True, billing_info=billing_info, payment_history=payment_data, available_plans=plans_data), 200

# === Change Plan via Apple Subscription ===
@api.route('/change-plan-apple', methods=['POST'])
@jwt_required()
def change_plan_apple():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user:
        return jsonify(success=False, error="User not found."), 404

    data = request.get_json()
    if not data or 'transaction_id' not in data or 'plan_id' not in data:
        return jsonify(success=False, error="Missing transaction ID or plan ID."), 400

    plan_id = data['plan_id']
    plan = Plan.query.get(plan_id)
    if not plan:
        return jsonify(success=False, error="Plan not found."), 404

    transaction_id = data['transaction_id']
    token = generate_apple_jwt()
    apple_data, status_code, error = verify_transaction(transaction_id, token)

    if status_code != 200:
        return jsonify(success=False, error="Apple API error", details=apple_data or error), status_code

    transaction_info = parse_apple_transaction(apple_data)
    if not transaction_info:
        return jsonify(success=False, error="Failed to parse Apple transaction"), 400

    product_id = transaction_info.get("productId")
    expires_date = transaction_info.get("expiresDate")

    print("Product ID:",product_id,"\n", "Apple Product ID db:",plan.apple_product_id)

    if plan.apple_product_id != product_id:
        return jsonify(success=False, error="Apple product does not match the selected plan."), 400

    # Update subscription
    user.plan_id = plan.id
    user.next_billing_date = convert_utc_to_local(expires_date, user.time_zone)
    user.subscription_status = "ACTIVE"
    user.subscription_start_date = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    user.payment_source = "Apple App Store"
    db.session.commit()

    return jsonify(success=True, message="Plan changed successfully", next_billing_date=user.next_billing_date), 200


# ====== APPLE API ======

@api.route('/verify-apple-subscription', methods=['POST'])
@jwt_required()
def verify_apple_subscription():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()
    transaction_id = data.get("transaction_id")
    if not transaction_id:
        return jsonify({"error": "transaction_id is required"}), 400

    token = generate_apple_jwt()
    apple_data, status_code, error = verify_transaction(transaction_id, token)

    if status_code != 200:
        return jsonify({"error": "Apple API error", "details": apple_data or error}), status_code

    transaction_info = parse_apple_transaction(apple_data)
    if not transaction_info:
        return jsonify({"error": "Failed to parse Apple transaction"}), 400

    print("Transaction Info:", transaction_info)

    product_id = transaction_info.get("productId")
    expires_date = transaction_info.get("expiresDate")

    plan = Plan.query.filter_by(apple_product_id=product_id).first()
    if not plan:
        return jsonify({"error": "Plan matching productId not found"}), 400

    # Update user subscription (only if new user / first subscription)
    if user.subscription_status != "ACTIVE":
        user.plan_id = plan.id
        user.next_billing_date = convert_utc_to_local(expires_date, user.time_zone)
        user.subscription_status = "ACTIVE"
        user.subscription_start_date = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        user.payment_source = "Apple App Store"
        user.status = None
        db.session.commit()
        print("New commit has been updated!")
    return jsonify({"success": True, "message": "Subscription verified", "expires_date": str(expires_date)}), 200



########################################### FORGOT PASSWORD API ###########################################

@api.route('/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.get_json()
    email = data.get("email")

    user = User.query.filter_by(email=email).first()
    if user:
        if user.reset_pswd_token:
            user.reset_pswd_token = None
        token = generate_token()
        user.reset_pswd_token = token
        db.session.commit()
        reset_password_email(user.email, user.username, token)

    # Always return generic success message to prevent email enumeration
    return jsonify({"message": "A reset link has been sent."}), 200

########################################### DEL PB-S BY ADMIN API ###########################################

@api.route('/delete-pubsecret/<int:pb_secret_id>', methods=['DELETE'])
@jwt_required()
def api_delete_published_secret(pb_secret_id):
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))

    # Check admin authorization
    if not user or user.username != "admin":
        return jsonify({"error": "You are not authorized to delete this secret."}), 403

    secret = SharedSecret.query.get(pb_secret_id)
    if not secret:
        return jsonify({"error": "Secret not found."}), 404

    try:
        db.session.delete(secret)
        db.session.commit()
        return jsonify({"message": "Secret deleted successfully."}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        print(e)
        return jsonify({"error": "Failed to delete the secret."}), 500
    

@api.route('/download/<filename>', methods=['GET'])
@jwt_required(optional=True)
def download_file_api(filename):
    try:
        upload_folder = current_app.config['UPLOAD_FOLDER']
        abs_path = os.path.abspath(os.path.join(upload_folder, filename))

        print("Checking file path:", abs_path, "Exists?", os.path.exists(abs_path))


        # ✅ Check if file exists
        if not os.path.exists(abs_path):
            return abort(404, description="File not found.")

        # ✅ Determine MIME type
        mimetype, _ = mimetypes.guess_type(abs_path)
        if mimetype is None:
            mimetype = 'application/octet-stream'

        # ✅ Publicly shared file?
        public_entry = SharedSecret.query.filter_by(file=filename, public=True).first()
        if public_entry:
            return send_file(abs_path, mimetype=mimetype, conditional=True)

        # ✅ Get user from token if available
        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id)) if user_id else None

        if user:
            # ✅ File owned by user?
            owned = Secret.query.filter_by(file=filename, user_id=user.id).first()
            if owned:
                return send_file(abs_path, mimetype=mimetype, conditional=True)

            # ✅ File shared with user via email?
            shared = SharedSecret.query.join(Secret).filter(
                Secret.file == filename,
                SharedSecret.email == user.email
            ).first()
            if shared:
                return send_file(abs_path, mimetype=mimetype, conditional=True)
            

        # ❌ If no access
        return abort(403, description="You don't have permission to access this file.")

    except Exception as e:
        print("[API Download Error]", str(e))
        traceback.print_exc()
        return abort(500)

########################################### CONTACT US API ###########################################

@api.route('/contact-us', methods=['POST'])
@jwt_required()
def contact_us():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))

    if not user:
        return jsonify(success=False, error='User not found'), 404

    data = request.get_json()

    # Validate required fields
    required_fields = ['name', 'email', 'subject', 'message']
    for field in required_fields:
        if not data.get(field):
            return jsonify(success=False, error=f'Missing field: {field}'), 400

    try:
        contact_email(data["name"], data["email"], data["subject"], data["message"])
        return jsonify(success=True, message="Your message has been sent successfully."), 200
    except Exception as e:
        return jsonify(success=False, error="An error occurred while sending your message."), 500
from . import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, DECIMAL, TIMESTAMP, func, Date, Text, text
from flask_login import UserMixin

# Users DB
class User(UserMixin, db.Model):
    __tablename__ = "users"
    
    id = db.Column(Integer, primary_key=True)
    plan_id = db.Column(Integer, ForeignKey('plans.id'), nullable=True)
    next_plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=True)
    paypal_payer_id = db.Column(String(20), nullable=True)
    email = db.Column(String(255), unique=True, nullable=False)
    password = db.Column(String(255), nullable=False)
    username = db.Column(String(50), unique=True, nullable=False)
    country_code = db.Column(String(4), nullable=True)
    phone = db.Column(String(20), nullable=True)
    storage_used = db.Column(Integer, default=0, nullable=False)
    payment_source = db.Column(String(50), nullable=True)
    verification_sent = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    email_token = db.Column(db.String(64), nullable=True)
    reset_pswd_token = db.Column(db.String(64), nullable=True)

    # Subscription-related fields
    transaction_id = db.Column(db.String(35), unique=True, nullable=True)
    purchase_token = db.Column(db.String(255), nullable=False)
    paypal_subscription_id = db.Column(String(25), unique=True, nullable=True)
    trial_start_date = db.Column(TIMESTAMP, nullable=True)
    trial_end_date = db.Column(TIMESTAMP, nullable=True)

    subscription_start_date = db.Column(TIMESTAMP, nullable=True)
    next_billing_date = db.Column(TIMESTAMP, nullable=True)
    subscription_status = db.Column(String(20), nullable=True)
    fialed_payments = db.Column(Integer, nullable=True)
    updated_at = db.Column(TIMESTAMP, nullable=True)
    status = db.Column(String(4), nullable=True)
    time_zone = db.Column(db.String(50), nullable=True)

    secrets = db.relationship('Secret', back_populates='user', cascade="all, delete-orphan")
    payments = db.relationship('Payment', back_populates='user', cascade="all, delete-orphan")
    plan = db.relationship('Plan', back_populates='users')
    shared_secrets = db.relationship('SharedSecret', back_populates='user', cascade="all, delete-orphan")
    history_payments = db.relationship('HistoryPayment', back_populates='user')
    login_history = db.relationship('LoginHistory', back_populates='user', cascade="all, delete-orphan")


class PendingSubscription(db.Model):
    __tablename__ = "pending_subscription"
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(35), unique=True, nullable=False)
    product_id = db.Column(db.String(20), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    expires_date = db.Column(TIMESTAMP, nullable=True)
    status = db.Column(db.String(50), default="PENDING")
    created_at = db.Column(TIMESTAMP, nullable=True)
    updated_at = db.Column(TIMESTAMP, nullable=True)
    trial_start_date = db.Column(TIMESTAMP, nullable=True)
    trial_end_date = db.Column(TIMESTAMP, nullable=True)
    payment_source = db.Column(String(50), nullable=True)
    purchase_token = db.Column(db.String(255), nullable=False)

    plan = db.relationship('Plan', back_populates='pending_subscription')


class LoginHistory(db.Model):
    __tablename__ = "login_history"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    login_time = db.Column(TIMESTAMP, nullable=False, default=func.now())
    ip_address = db.Column(String(45), nullable=False)
    
    # Relationship to access user from the login history
    user = db.relationship('User', back_populates='login_history')


# Secrets DB
class Secret(db.Model):
    __tablename__ = "secrets"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(String(100), nullable=False)
    secret = db.Column(Text, nullable=False)
    file = db.Column(String(255), nullable=True)
    date = db.Column(Date, nullable=True)
    share = db.Column(Boolean, default=False)
    pinned = db.Column(Boolean, default=False)
    starred = db.Column(Boolean, default=False)

    user = db.relationship('User', back_populates='secrets')
    shared_secrets = db.relationship('SharedSecret', back_populates='secret', passive_deletes=True)

    
# Payments DB
class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    plan_id = db.Column(Integer, ForeignKey('plans.id'), nullable=True)
    amount = db.Column(DECIMAL(10, 2), nullable=True)
    currency = db.Column(String(10), nullable=True)
    payment_date = db.Column(TIMESTAMP, default=func.now())
    payment_method = db.Column(String(50), nullable=True)
    payment_status = db.Column(String(50), nullable=True)
    transaction_id = db.Column(String(255), nullable=True)
    track_id = db.Column(String(255), nullable=True)
    authorization_id = db.Column(String(255), nullable=True)
    gateway_response_code = db.Column(String(50), nullable=True)
    gateway_response_message = db.Column(String(255), nullable=True)
    acquirer_response_code = db.Column(String(50), nullable=True)
    acquirer_response_message = db.Column(String(255), nullable=True)
    card_brand = db.Column(String(50), nullable=True)
    card_last_four = db.Column(String(4), nullable=True)
    three_d_secure_status = db.Column(String(50), nullable=True)
    ip_address = db.Column(String(45), nullable=True)
    user_agent = db.Column(String(255), nullable=True)

    user = db.relationship('User', back_populates='payments')
    plan = db.relationship('Plan', back_populates='payments')



# History Payments DB
class HistoryPayment(db.Model):
    __tablename__ = "history_payments"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    plan_id = db.Column(Integer, ForeignKey('plans.id', ondelete='SET NULL'), nullable=True)
    amount = db.Column(DECIMAL(10, 2), nullable=False)
    currency = db.Column(String(10), nullable=False)
    payment_date = db.Column(TIMESTAMP, default=func.now())
    payment_method = db.Column(String(50), nullable=False)
    payment_status = db.Column(String(50), nullable=False)
    transaction_id = db.Column(String(255), nullable=False)
    card_brand = db.Column(String(50), nullable=True)
    card_last_four = db.Column(String(4), nullable=True)
    authorization_id = db.Column(String(255), nullable=True)

    user = db.relationship('User', back_populates='history_payments')
    plan = db.relationship('Plan', back_populates='history_payments')


# Plans DB
class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(Integer, primary_key=True)  
    plan = db.Column(String(10), nullable=False)
    price = db.Column(DECIMAL(10, 2), nullable=False)
    currency = db.Column(String(10), nullable=False)
    description = db.Column(db.JSON, nullable=False)
    billing_cycle = db.Column(String(10), nullable=False) 
    storage_limit = db.Column(Integer, nullable=False)
    paypal_plan_id = db.Column(db.JSON, nullable=True)
    product_id = db.Column(String(50), nullable=True)
    app_product_id = db.Column(String(100), nullable=True)

    users = db.relationship('User', back_populates='plan')
    payments = db.relationship('Payment', back_populates='plan')
    history_payments = db.relationship('HistoryPayment', back_populates='plan')
    pending_subscription = db.relationship('PendingSubscription', back_populates='plan')


# Shared Secrets Table
class SharedSecret(db.Model):
    __tablename__ = 'shared_secrets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    secret_id = db.Column(db.Integer, db.ForeignKey('secrets.id', ondelete='SET NULL'), nullable=True)
    username = db.Column(String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    public = db.Column(db.Boolean, default=False)
    last_login = db.Column(TIMESTAMP, nullable=True)
    period = db.Column(db.String(5), nullable=True)
    time_period = db.Column(TIMESTAMP, nullable=True)
    token = db.Column(db.String(255), unique=True, nullable=True)
    date_to_send = db.Column(db.DateTime, nullable=True)
    time_to_send = db.Column(db.Time, nullable=True)
    received = db.Column(db.Boolean, default=False)
    schedule_delete_confirm = db.Column(db.Boolean, default=False)
    public_delete_confirm = db.Column(db.Boolean, default=False)
    received_time = db.Column(TIMESTAMP, nullable=True)
    delete_at = db.Column(TIMESTAMP, nullable=True)

    # Snapshot fields
    title = db.Column(db.String(100), nullable=True)
    snapshot_secret = db.Column(db.Text, nullable=True)
    file = db.Column(db.String(255), nullable=True)
    share_date = db.Column(TIMESTAMP, nullable=True)

    user = db.relationship('User', back_populates='shared_secrets')
    secret = db.relationship('Secret', back_populates='shared_secrets')



class PublicSecrets(db.Model):
    __tablename__ = 'public_secrets'

    id = db.Column(db.Integer, primary_key=True)
    shared_secret_id = db.Column(db.Integer, db.ForeignKey('shared_secrets.id', ondelete='CASCADE'), nullable=False)
    username = db.Column(String(50), nullable=True)
    title = db.Column(String(100), nullable=True)
    secret = db.Column(String, nullable=True)
    file = db.Column(String, nullable=True)
    share_date = db.Column(TIMESTAMP, nullable=True)



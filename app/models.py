from . import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, DECIMAL, TIMESTAMP, func, Date, Text
from flask_login import UserMixin

# Users DB
class User(UserMixin, db.Model):
    __tablename__ = "users"
    
    id = db.Column(Integer, primary_key=True)
    plan_id = db.Column(Integer, ForeignKey('plans.id'), nullable=True)
    email = db.Column(String(255), unique=True, nullable=False)
    password = db.Column(String(255), nullable=False)
    username = db.Column(String(255), unique=True, nullable=False)
    country_code = db.Column(String(4), nullable=True)
    phone = db.Column(String(20), nullable=True)
    storage_used = db.Column(Integer, default=0, nullable=False)
    customer_id = db.Column(String(255), nullable=True)
    card_id = db.Column(String(255), nullable=True)
    payment_agreement_id = db.Column(String(255), nullable=True)
    verification_sent = db.Column(db.Boolean, default=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    email_token = db.Column(db.String(64), nullable=True)
    reset_pswd_token = db.Column(db.String(64), nullable=True)

    # Subscription-related fields
    trial_start_date = db.Column(TIMESTAMP, nullable=True)
    trial_end_date = db.Column(TIMESTAMP, nullable=True)

    subscription_start_date = db.Column(TIMESTAMP, nullable=True)
    subscription_end_date = db.Column(TIMESTAMP, nullable=True)
    subscription_status = db.Column(String(20), nullable=False, default="inactive")


    secrets = db.relationship('Secret', back_populates='user', cascade="all, delete-orphan")
    payments = db.relationship('Payment', back_populates='user', cascade="all, delete-orphan")
    plan = db.relationship('Plan', back_populates='users')
    shared_secrets = db.relationship('SharedSecret', back_populates='user')
    history_payments = db.relationship('HistoryPayment', back_populates='user')
    login_history = db.relationship('LoginHistory', back_populates='user', cascade="all, delete-orphan")


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
    shared_secrets = db.relationship('SharedSecret', back_populates='secret', cascade='all, delete-orphan', passive_deletes=True)

    
# Payments DB
class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    plan_id = db.Column(Integer, ForeignKey('plans.id'), nullable=True)
    amount = db.Column(DECIMAL(10, 2), nullable=False)
    currency = db.Column(String(10), nullable=False)
    payment_date = db.Column(TIMESTAMP, default=func.now())
    payment_method = db.Column(String(50), nullable=False)
    payment_status = db.Column(String(50), nullable=False)
    transaction_id = db.Column(String(255), nullable=False)
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
    plan = db.Column(String(10), unique=True, nullable=False)
    price = db.Column(DECIMAL(10, 2), nullable=False)
    currency = db.Column(String(10), nullable=False)
    description = db.Column(db.JSON, nullable=False)
    billing_cycle = db.Column(String(10), nullable=False) 
    storage_limit = db.Column(Integer, nullable=False)

    users = db.relationship('User', back_populates='plan')
    payments = db.relationship('Payment', back_populates='plan')
    history_payments = db.relationship('HistoryPayment', back_populates='plan')


class SharedSecret(db.Model):
    __tablename__ = 'shared_secrets'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    secret_id = db.Column(db.Integer, db.ForeignKey('secrets.id', ondelete='CASCADE'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    date_to_send = db.Column(db.DateTime, nullable=False)
    time_to_send = db.Column(db.Time)
    received = db.Column(db.Boolean, default=False)
    delete_confirmed = db.Column(db.Boolean, default=False)
    received_time = db.Column(TIMESTAMP, nullable=True, default=func.now())
    delete_at = db.Column(TIMESTAMP, nullable=True)

    user = db.relationship('User', back_populates='shared_secrets')
    secret = db.relationship('Secret', back_populates='shared_secrets')

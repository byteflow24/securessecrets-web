from flask import Flask, session, redirect, url_for, flash, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_compress import Compress
from datetime import timedelta

db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
bootstrap = Bootstrap()
migrate = Migrate()

# Manages session expiration by logging out inactive users and clearing expired session data.
def session_expiration_handler():
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(minutes=15)

    if current_user.is_authenticated:
        session.modified = True  # Update session activity timestamp
    else:
        if 'user_id' in session:  # If the user is logged out but session data exists
            session.clear()  # Clear session data
            flash('Your session has expired. Please log in again.', 'warning')
            return redirect(url_for('main.login'))

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    # Create the SQLAlchemy engine with pool_pre_ping
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True
    }

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    Migrate(app, db)
    bootstrap.init_app(app)
    Compress(app)

    # Set the session lifetime for Flask-Login remember me functionality
    login_manager.remember_cookie_duration = timedelta(minutes=15)

    @app.before_request
    def check_session_expiration():
        result = session_expiration_handler()
        if result:  # Redirect if the session expired
            return result

    # Import inside function to avoid circular import
    with app.app_context():
        from .routes import main as main_blueprint
        app.register_blueprint(main_blueprint)

    return app



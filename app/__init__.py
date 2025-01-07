from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_compress import Compress
from flask_talisman import Talisman

db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
bootstrap = Bootstrap()
migrate = Migrate()

csp = {
    'default-src': ["'self'"],
    'script-src': [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://code.jquery.com",
        "https://www.googletagmanager.com",
        "https://use.fontawesome.com",
        "https://cdnjs.cloudflare.com",
    ],
    'style-src': [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
    ],
    'font-src': [
        "'self'",
        "https://cdn.jsdelivr.net",
        "https://fonts.gstatic.com",
    ],
    'img-src': [
        "'self'",
        "https://pagead2.googlesyndication.com",
    ],
    'connect-src': [
        "'self'",
        "https://ep1.adtrafficquality.google",
    ],
    'frame-src': [
        "'self'",
        "https://googleads.g.doubleclick.net",
    ],
}

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
    CSRFProtect(app)
    Talisman(app, content_security_policy=csp)

    # Import inside function to avoid circular import
    with app.app_context():
        from .routes import main as main_blueprint
        app.register_blueprint(main_blueprint)

    return app



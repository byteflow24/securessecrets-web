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
    'script-src': ["'self'", "https://pagead2.googlesyndication.com"],
    'frame-src': ["https://googleads.g.doubleclick.net", "https://google.com"],
    'frame-ancestors': ["'self'", "https://google.com", "https://googleads.g.doubleclick.net"]
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



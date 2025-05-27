from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_compress import Compress
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
bootstrap = Bootstrap()
migrate = Migrate()
jwt = JWTManager()

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
    jwt.init_app(app)

    # Import inside function to avoid circular import
    with app.app_context():
        from .routes import main as main_blueprint, paypal_webhook
        from .api import api as api_blueprint

        app.register_blueprint(main_blueprint) #main
        app.register_blueprint(api_blueprint) #api

        csrf.exempt(paypal_webhook)
        csrf.exempt(api_blueprint)

    return app



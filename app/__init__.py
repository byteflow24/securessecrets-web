from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_compress import Compress
from flask_jwt_extended import JWTManager
from werkzeug.middleware.proxy_fix import ProxyFix
import os

db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
bootstrap = Bootstrap()
migrate = Migrate()
jwt = JWTManager()

blacklist = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    jti = jwt_payload["jti"]
    return jti in blacklist

def create_app():
    app = Flask(__name__)

    env = os.getenv('FLASK_ENV', 'development')
    if env == 'production':
        app.config.from_object('config.ProductionConfig')
    else:
        app.config.from_object('config.DevelopmentConfig')

    # # ✅ Debug: check which upload folder is being used
    # print("UPLOAD_FOLDER is:", app.config['UPLOAD_FOLDER'])

    # SQLAlchemy engine options
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True
    }

    # Optional: ProxyFix for production
    if app.config.get("USE_PROXY_FIX"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Ensure upload folder exists in development
    if env == 'development':
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    Migrate(app, db)
    bootstrap.init_app(app)
    Compress(app)
    jwt.init_app(app)

    # --- ✅ Add Security Headers ---
    @app.after_request
    def add_security_headers(response):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://code.jquery.com "
                "https://cdn.jsdelivr.net "
                "https://cdnjs.cloudflare.com "
                "https://*.googletagmanager.com "
                "https://*.google-analytics.com "
                "https://*.googlesyndication.com "
                "https://*.doubleclick.net "
                "https://*.adtrafficquality.google "
                "https://use.fontawesome.com "
                "https://www.google.com "
                "https://www.gstatic.com; "
            "style-src 'self' 'unsafe-inline' "
                "https://cdn.jsdelivr.net "
                "https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://use.fontawesome.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: "
                "https://*.google-analytics.com "
                "https://*.googlesyndication.com "
                "https://*.adtrafficquality.google; "
            "connect-src 'self' "
                "https://*.googletagmanager.com "
                "https://*.google-analytics.com "
                "https://*.adtrafficquality.google "
                "https://csi.gstatic.com; "
            "frame-src 'self' "
                "https://*.googletagmanager.com "
                "https://*.googlesyndication.com "
                "https://*.doubleclick.net "
                "https://*.adtrafficquality.google "
                "https://www.google.com; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none'; "
            "media-src 'self';"
        )
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    # Import blueprints
    with app.app_context():
        from .routes import main as main_blueprint, paypal_webhook
        from .api import api as api_blueprint

        app.register_blueprint(main_blueprint)
        app.register_blueprint(api_blueprint)

        csrf.exempt(paypal_webhook)
        csrf.exempt(api_blueprint)

    return app


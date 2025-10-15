import os
from datetime import timedelta

class BaseConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///dev.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GB.
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'dev-jwt-secret'
    JWT_BLACKLIST_ENABLED = True
    JWT_BLACKLIST_TOKEN_CHECKS = ["access"]

    # SERVER_NAME = 'www.securessecrets.com'
    # APPLICATION_ROOT = '/'
    # PREFERRED_URL_SCHEME = 'https'

class DevelopmentConfig(BaseConfig):
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')

class ProductionConfig(BaseConfig):
    UPLOAD_FOLDER = '/var/data/uploads'

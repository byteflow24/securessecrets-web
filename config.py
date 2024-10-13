import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB limit
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)

    SERVER_NAME = 'advocate-phones-isolation-airports.trycloudflare.com'
    APPLICATION_ROOT = '/'
    PREFERRED_URL_SCHEME = 'https'

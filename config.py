import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB limit
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)

    # SERVER_NAME = 'progress-absolutely-amplifier-indicated.trycloudflare.com'
    # APPLICATION_ROOT = '/'
    # PREFERRED_URL_SCHEME = 'https'

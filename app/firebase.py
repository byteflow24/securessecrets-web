import os
import firebase_admin
from firebase_admin import credentials

FBSVC_SERVICE_ACCOUNT_SDK = os.environ.get("FBSVC_SERVICE_ACCOUNT_SDK")

cred = credentials.Certificate(FBSVC_SERVICE_ACCOUNT_SDK)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

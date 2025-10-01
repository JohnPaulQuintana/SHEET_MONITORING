import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase Admin with credentials from .env
if not firebase_admin._apps:
    cred = credentials.Certificate({
        "type": os.getenv("FIRESTORE_TYPE"),
        "project_id": os.getenv("FIRESTORE_PROJECT_ID"),
        "private_key_id": os.getenv("FIRESTORE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIRESTORE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("FIRESTORE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIRESTORE_CLIENT_ID"),
        "auth_uri": os.getenv("FIRESTORE_AUTH_URI"),
        "token_uri": os.getenv("FIRESTORE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIRESTORE_AUTH_PROVIDER_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIRESTORE_CLIENT_CERT_URL"),
        "universe_domain": os.getenv("FIRESTORE_UNIVERSE_DOMAIN"),
    })
    firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv

load_dotenv()

FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "serviceAccount.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

from app.config import db

def get_user_by_email(email: str):
    doc_ref = db.collection("users").document(email)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None

def get_all_users():
    users = db.collection("users").stream()
    return [u.to_dict() for u in users]

def create_user(email: str, role: str):
    db.collection("users").document(email).set({
        "email": email,
        "role": role
    })

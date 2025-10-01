from app.config import db
from datetime import datetime

def get_assignments_for_user(email: str):
    assignments = db.collection("assignments").where("user_email", "==", email).stream()
    return [a.to_dict() for a in assignments]

def get_all_assignments():
    assignments = db.collection("assignments").stream()
    return [a.to_dict() for a in assignments]

def update_last_checked(sheet_id: str):
    assignments_ref = db.collection("assignments")
    query = assignments_ref.where("sheet_id", "==", sheet_id).limit(1).get()
    if query:
        doc = query[0]
        doc.reference.update({"last_checked": datetime.utcnow()})

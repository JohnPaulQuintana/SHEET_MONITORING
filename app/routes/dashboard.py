from datetime import datetime
import os
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.routes.auth import require_auth
from app.services.sheets_service import get_assignments_for_user, get_all_assignments
import firebase_admin
from firebase_admin import auth as firebase_auth, firestore
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import requests

# -----------------------
# Setup
# -----------------------
router = APIRouter()
db = firestore.client()
templates = Jinja2Templates(directory="app/templates")

# Google API setup using environment variables
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
service_account_info = {
    "type": os.getenv("TYPE"),
    "project_id": os.getenv("PROJECT_ID"),
    "private_key_id": os.getenv("PRIVATE_KEY_ID"),
    "private_key": os.getenv("PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("CLIENT_EMAIL"),
    "client_id": os.getenv("CLIENT_ID"),
    "auth_uri": os.getenv("AUTH_URI"),
    "token_uri": os.getenv("TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("CLIENT_CERT_URL"),
}

creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)

# -----------------------
# Utility Functions
# -----------------------
def format_sheets(sheets_docs):
    sheets = []
    for doc in sheets_docs:
        data = doc.to_dict()
        last_modified_dt = None
        if data.get("last_modified"):
            try:
                last_modified_dt = datetime.fromisoformat(data["last_modified"])
            except Exception:
                pass

        sheets.append({
            "id": doc.id,
            "name": data.get("name"),
            "url": data.get("url"),
            "modified_by": data.get("last_modified_by") or "-",
            "modified_email": data.get("last_modified_email") or "-",
            "last_modified_dt": last_modified_dt.isoformat() if last_modified_dt else None,
            "status": data.get("status", "unknown"),
            "tabs": data.get("tabs", []),
            "history": [
                {
                    "modified_dt": h.get("last_modified"),
                    "modified_by": h.get("last_modified_by"),
                    "modified_email": h.get("last_modified_email"),
                    "status": h.get("status")
                } for h in data.get("history", [])
            ]
        })
    return sheets



# -----------------------
# Dashboard
# -----------------------
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: dict = Depends(require_auth)):
    if isinstance(user, RedirectResponse):
        return user

    uid = user.get("uid", "")
    role = user.get("role", "user")

    if role == "developer":
        users_list = [{
            "uid": u.uid,
            "email": u.email,
            "role": u.custom_claims.get("role") if u.custom_claims else "user"
        } for u in firebase_auth.list_users().iterate_all()]

        user_sheets_ref = db.collection("sheets").document(uid).collection("user_sheets")
        sheets_docs = user_sheets_ref.stream()
        sheets = format_sheets(sheets_docs)

        return templates.TemplateResponse("admin/dashboard.html", {
            "request": request,
            "user": user,
            "users_list": users_list,
            "sheets": sheets,
            "now": datetime.utcnow().isoformat(),
        })
    else:
        sheets = get_all_assignments()
        return templates.TemplateResponse("user_dashboard.html", {
            "request": request,
            "user": user,
            "sheets": sheets
        })

# -----------------------
# Manage Accounts
# -----------------------
@router.get("/dashboard/manage_accounts", response_class=HTMLResponse)
def manage_accounts_page(request: Request, user: dict = Depends(require_auth)):
    if user.get("role") != "developer":
        return RedirectResponse("/dashboard")

    users_list = [{
        "uid": u.uid,
        "email": u.email,
        "role": u.custom_claims.get("role") if u.custom_claims else "user"
    } for u in firebase_auth.list_users().iterate_all()]

    return templates.TemplateResponse("admin/manage_accounts.html", {
        "request": request,
        "user": user,
        "users": users_list
    })

@router.post("/dashboard/manage_accounts/add_user")
async def add_user(email: str = Form(...), password: str = Form(...), role: str = Form(...), user: dict = Depends(require_auth)):
    if user.get("role") != "developer":
        return JSONResponse(status_code=403, content={"detail": "Unauthorized"})
    try:
        new_user = firebase_auth.create_user(email=email, password=password)
        firebase_auth.set_custom_user_claims(new_user.uid, {"role": role})
        return JSONResponse({"detail": "User created successfully"})
    except Exception as e:
        return JSONResponse({"detail": f"Error creating user: {str(e)}"}, status_code=400)


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
# Utility: Format Sheets
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
            "last_modified_dt": last_modified_dt.isoformat() if last_modified_dt else None
        })
    return sheets



# -----------------------
# Dashboard
# -----------------------
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: dict = Depends(require_auth)):
    # If token expired, require_auth may return RedirectResponse
    if isinstance(user, RedirectResponse):
        return user

    uid = user.get("uid", "")
    role = user.get("role", "user")

    if role == "developer":
        # Fetch Firebase users
        users_list = []
        for u in firebase_auth.list_users().iterate_all():
            users_list.append({
                "uid": u.uid,
                "email": u.email,
                "role": u.custom_claims.get("role") if u.custom_claims else "user"
            })

        # Fetch developer's sheets
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
    
    users_list = []
    page = firebase_auth.list_users().iterate_all()
    for u in page:
        users_list.append({
            "uid": u.uid,
            "email": u.email,
            "role": u.custom_claims.get("role") if u.custom_claims else "user"
        })

    return templates.TemplateResponse("admin/manage_accounts.html", {
        "request": request,
        "user": user,
        "users": users_list
    })


# -----------------------
# Add Firebase User
# -----------------------
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


# -----------------------
# Sheets Page
# -----------------------
@router.get("/dashboard/online_sheets", response_class=HTMLResponse)
async def get_sheets(request: Request, user: dict = Depends(require_auth)):
    uid = user.get("uid")
    user_sheets_ref = db.collection("sheets").document(uid).collection("user_sheets")
    sheets_docs = user_sheets_ref.stream()
    sheets = format_sheets(sheets_docs)

    return templates.TemplateResponse("dashboard_online_sheets.html", {
        "request": request,
        "user": user,
        "sheets": sheets,
        "users_list": [],
        "active_users": 0,
        "now": datetime.utcnow().isoformat(),
    })


# -----------------------
# Add New Sheet
# -----------------------
@router.post("/dashboard/online_sheets/add")
async def add_sheet(name: str = Form(...), url: str = Form(...), user: dict = Depends(require_auth)):
    uid = user.get("uid")
    user_sheets_ref = db.collection("sheets").document(uid).collection("user_sheets")

    # Check duplicate
    if any(True for _ in user_sheets_ref.where("name", "==", name).stream()):
        return JSONResponse({"detail": "Sheet with this name already exists"}, status_code=400)
    if any(True for _ in user_sheets_ref.where("url", "==", url).stream()):
        return JSONResponse({"detail": "Sheet with this URL already exists"}, status_code=400)

    # Fetch initial metadata
    meta = get_sheet_metadata(url)

    # Store sheet
    doc_ref = user_sheets_ref.document()
    doc_ref.set({
        "name": name,
        "url": url,
        "created_at": datetime.utcnow().isoformat(),
        "last_modified": meta["modifiedTime"] if meta else None,
        "last_modified_by": meta["lastUser"] if meta else None,
        "last_modified_email": meta["lastUserEmail"] if meta else None
    })

    return JSONResponse({"detail": "Sheet added successfully"})


# -----------------------
# Google Sheet Metadata
# -----------------------
def get_sheet_metadata(sheet_url: str):
    try:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
    except Exception:
        return None

    try:
        file = drive_service.files().get(
            fileId=sheet_id,
            fields="modifiedTime,lastModifyingUser"
        ).execute()

        return {
            "modifiedTime": file.get("modifiedTime"),
            "lastUser": file.get("lastModifyingUser", {}).get("displayName"),
            "lastUserEmail": file.get("lastModifyingUser", {}).get("emailAddress")
        }
    except Exception:
        return None


# -----------------------
# Check Updates Endpoint
# -----------------------
@router.get("/dashboard/online_sheets/check_updates")
async def check_updates(user: dict = Depends(require_auth)):
    uid = user.get("uid")
    user_sheets_ref = db.collection("sheets").document(uid).collection("user_sheets")
    sheets_docs = user_sheets_ref.stream()

    updated_sheets = []

    for doc in sheets_docs:
        data = doc.to_dict()
        url = data.get("url")
        last_modified = data.get("last_modified")

        meta = get_sheet_metadata(url)
        if not meta:
            continue

        latest_modified = meta["modifiedTime"]

        if latest_modified and (not last_modified or latest_modified > last_modified):
            doc.reference.update({
                "last_modified": latest_modified,
                "last_modified_by": meta["lastUser"],
                "last_modified_email": meta["lastUserEmail"],
                "last_checked": datetime.utcnow().isoformat()
            })
            updated_sheets.append({
                "id": doc.id,
                "name": data.get("name"),
                "url": url,
                "modified_by": meta["lastUser"],
                "modified_email": meta["lastUserEmail"],
                "last_modified_dt": latest_modified
            })

    return JSONResponse({
        "updated_sheets": updated_sheets,
        "checked_at": datetime.utcnow().isoformat()
    })

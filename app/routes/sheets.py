from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routes.auth import require_auth
import os
import requests
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import firebase_admin
from firebase_admin import firestore

router = APIRouter()
db = firestore.client()
templates = Jinja2Templates(directory="app/templates")

# -----------------------
# Google API Setup
# -----------------------
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

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
sheets_service = build("sheets", "v4", credentials=creds)

# -----------------------
# Utility functions
# -----------------------
def normalize_url(url: str) -> str:
    return url.rstrip("/")

def is_sheet_reachable(url: str) -> bool:
    try:
        response = requests.head(url, timeout=5)
        return response.status_code == 200
    except:
        return False

def extract_sheet_id(sheet_url: str) -> str | None:
    try:
        return sheet_url.split("/d/")[1].split("/")[0]
    except Exception:
        return None

def get_sheet_metadata(sheet_url: str):
    sheet_id = extract_sheet_id(sheet_url)
    if not sheet_id:
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

def get_sheet_tabs(sheet_url: str):
    sheet_id = extract_sheet_id(sheet_url)
    if not sheet_id:
        return []
    try:
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheets = spreadsheet.get("sheets", [])
        return [s["properties"]["title"] for s in sheets]
    except Exception:
        return []

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
            "tabs": data.get("tabs", [])
        })
    return sheets

# -----------------------
# Routes
# -----------------------
@router.get("/dashboard/online_sheets", response_class=HTMLResponse)
async def online_sheets(request: Request, user: dict = Depends(require_auth)):
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

@router.post("/dashboard/online_sheets/add")
async def add_sheet(name: str = Form(...), url: str = Form(...), user: dict = Depends(require_auth)):
    uid = user.get("uid")
    user_sheets_ref = db.collection("sheets").document(uid).collection("user_sheets")
    normalized_url = normalize_url(url)

    # Check duplicate
    if any(True for _ in user_sheets_ref.where("name", "==", name).stream()):
        return JSONResponse({"detail": "Sheet with this name already exists"}, status_code=400)
    if any(True for _ in user_sheets_ref.where("url", "==", normalized_url).stream()):
        return JSONResponse({"detail": "Sheet with this URL already exists"}, status_code=400)

    meta = get_sheet_metadata(normalized_url)
    reachable = is_sheet_reachable(normalized_url)
    tabs = get_sheet_tabs(normalized_url)

    history = []
    if meta:
        history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "last_modified": meta.get("modifiedTime"),
            "last_modified_by": meta.get("lastUser"),
            "last_modified_email": meta.get("lastUserEmail"),
            "status": "added"
        })

    doc_ref = user_sheets_ref.document()
    doc_ref.set({
        "name": name,
        "url": normalized_url,
        "created_at": datetime.utcnow().isoformat(),
        "added_by": user.get("email"),
        "last_modified": meta.get("modifiedTime") if meta else None,
        "last_modified_by": meta.get("lastUser") if meta else None,
        "last_modified_email": meta.get("lastUserEmail") if meta else None,
        "status": "reachable" if reachable else "unreachable",
        "tabs": tabs,
        "history": history
    })

    return JSONResponse({"detail": "Sheet added successfully", "tabs": tabs})

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
        status = data.get("status", "unknown")

        meta = get_sheet_metadata(url)
        reachable = is_sheet_reachable(url)
        tabs = get_sheet_tabs(url)

        updated = False
        update_data = {
            "last_checked": datetime.utcnow().isoformat(),
            "status": "reachable" if reachable else "unreachable",
            "tabs": tabs
        }

        if meta:
            latest_modified = meta.get("modifiedTime")
            if latest_modified and (not last_modified or latest_modified > last_modified):
                update_data.update({
                    "last_modified": latest_modified,
                    "last_modified_by": meta.get("lastUser"),
                    "last_modified_email": meta.get("lastUserEmail")
                })
                history = data.get("history", [])
                history.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "last_modified": latest_modified,
                    "last_modified_by": meta.get("lastUser"),
                    "last_modified_email": meta.get("lastUserEmail"),
                    "status": "updated"
                })
                update_data["history"] = history
                updated = True

        if updated or status != update_data["status"] or data.get("tabs", []) != tabs:
            doc.reference.update(update_data)
            updated_sheets.append({
                "id": doc.id,
                "name": data.get("name"),
                "url": url,
                "modified_by": update_data.get("last_modified_by"),
                "modified_email": update_data.get("last_modified_email"),
                "status": update_data["status"],
                "last_modified_dt": update_data.get("last_modified"),
                "tabs": tabs
            })

    return JSONResponse({
        "updated_sheets": updated_sheets,
        "checked_at": datetime.utcnow().isoformat()
    })

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from firebase_admin import auth as firebase_auth
from app.config import db
import logging
import datetime

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# -----------------------
# Logger setup
# -----------------------
logger = logging.getLogger("auth")
logging.basicConfig(level=logging.INFO)

# -----------------------
# Session cookie lifetime
# -----------------------
SESSION_DURATION = datetime.timedelta(days=7)  # 7 days

# -----------------------
# Login page
# -----------------------
@router.get("/login")
def login_page(request: Request):
    token = request.cookies.get("token")
    if token:
        try:
            # Verify Firebase session cookie
            decoded = firebase_auth.verify_session_cookie(token, check_revoked=False, app=None, clock_tolerance=5)
            return RedirectResponse(url="/dashboard")
        except Exception:
            # Invalid or expired cookie -> render login
            pass

    return templates.TemplateResponse("login.html", {"request": request})

# -----------------------
# AJAX login endpoint
# -----------------------
@router.post("/login")
async def login_ajax(request: Request):
    data = await request.json()
    id_token = data.get("idToken")
    if not id_token:
        logger.warning("Login attempt without ID token")
        raise HTTPException(status_code=400, detail="ID token required")

    try:
        # Create a Firebase session cookie from the ID token
        session_cookie = firebase_auth.create_session_cookie(
            id_token, expires_in=SESSION_DURATION
        )

        # Decode just for logging/user lookup
        decoded_token = firebase_auth.verify_id_token(id_token)
        email = decoded_token.get("email")
        uid = decoded_token["uid"]

        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            logger.warning(f"Unregistered user login attempt: {email}")
            raise HTTPException(status_code=403, detail="User not registered")

        response = JSONResponse({"detail": "Login successful", "user": user_doc.to_dict()})
        # Store session cookie in HttpOnly cookie
        response.set_cookie(
            key="token",
            value=session_cookie,
            httponly=True,
            samesite="lax",
            secure=True,
            max_age=int(SESSION_DURATION.total_seconds()),
        )
        logger.info(f"Login successful for: {email}")
        return response

    except firebase_auth.ExpiredIdTokenError:
        logger.error("Expired ID token")
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except Exception as e:
        logger.exception(f"Authentication failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

# -----------------------
# Logout
# -----------------------
@router.get("/logout")
def logout():
    logger.info("Logout requested")
    response = RedirectResponse("/auth/login")
    response.delete_cookie("token")
    return response

# -----------------------
# Dependency for protected routes
# -----------------------
def require_auth(request: Request):
    token = request.cookies.get("token")
    if not token:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            raise HTTPException(status_code=401, detail="Not authenticated")
        else:
            return RedirectResponse("/auth/login")

    try:
        decoded = firebase_auth.verify_session_cookie(token, check_revoked=True)
        uid = decoded["uid"]

        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            raise HTTPException(status_code=403, detail="User not registered")

        user_data = user_doc.to_dict()
        user_data["uid"] = uid
        user_data["email"] = decoded.get("email")
        return user_data

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

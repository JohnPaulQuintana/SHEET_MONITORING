from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from firebase_admin import auth as firebase_auth
from app.config import db
import logging
import time

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# -----------------------
# Logger setup
# -----------------------
logger = logging.getLogger("auth")
logging.basicConfig(level=logging.INFO)

# -----------------------
# Leeway for token validation (seconds)
# -----------------------
TOKEN_LEEWAY = 300  # 5 minutes

# -----------------------
# Login page
# -----------------------
@router.get("/login")
def login_page(request: Request):
    token = request.cookies.get("token")
    if token:
        try:
            # Verify token (skip revoked check for simplicity)
            decoded = firebase_auth.verify_id_token(token, check_revoked=False)
            # If valid, redirect to dashboard
            return RedirectResponse(url="/dashboard")
        except Exception:
            # If token invalid/expired, continue to login page
            pass

    # Render login page normally
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
        # Decode Firebase token, skip revocation for smoother handling
        decoded_token = firebase_auth.verify_id_token(id_token, check_revoked=False)
        logger.info(f"Decoded token: {decoded_token}")

        # Optional: custom leeway validation
        now = int(time.time())
        exp = decoded_token.get("exp", 0)
        iat = decoded_token.get("iat", 0)
        if now > exp + TOKEN_LEEWAY:
            logger.warning("Token expired")
            raise HTTPException(status_code=401, detail="Token expired. Please login again.")
        if now < iat - TOKEN_LEEWAY:
            logger.warning("Token issued in the future")
            raise HTTPException(status_code=401, detail="Token issued in the future")

        email = decoded_token.get("email")
        uid = decoded_token["uid"]
        user_doc = db.collection("users").document(uid).get()

        if not user_doc.exists:
            logger.warning(f"Unregistered user login attempt: {email}")
            raise HTTPException(status_code=403, detail="User not registered")

        response = JSONResponse({"detail": "Login successful", "user": user_doc.to_dict()})
        # Set secure HttpOnly cookie for session
        response.set_cookie(
            key="token",
            value=id_token,
            httponly=True,
            samesite="lax",
            max_age=3600  # 1 hour
        )
        logger.info(f"Login successful for: {email}")
        return response

    except firebase_auth.ExpiredIdTokenError:
        logger.error("Expired token")
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except firebase_auth.InvalidIdTokenError:
        logger.error("Invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")
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
        # For AJAX, return JSON
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            raise HTTPException(status_code=401, detail="Not authenticated")
        else:
            return RedirectResponse("/auth/login")

    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=False)
        uid = decoded["uid"]
        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            raise HTTPException(status_code=403, detail="User not registered")

        user_data = user_doc.to_dict()
        # Include uid/email from Firebase token if needed
        user_data["uid"] = uid
        user_data["email"] = decoded.get("email")
        return user_data

    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


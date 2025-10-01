from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from app.routes import auth, dashboard

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

app.include_router(auth.router, prefix="/auth")
app.include_router(dashboard.router)

# Redirect 401 Unauthorized to login page
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    path = request.url.path

    # Skip redirect for login POST or other auth API routes
    if path.startswith("/auth/login") and request.method == "POST":
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    # Detect AJAX requests
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    # Redirect for normal page navigation
    if exc.status_code in (401, 403):
        return RedirectResponse("/auth/login")

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


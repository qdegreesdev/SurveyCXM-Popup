import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import logging
import secrets
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from loguru import logger

from config import settings
from routes.popup import router as popup_router
from database import get_db_service

# Configure logger to write to a file
logger.add("app.log", rotation="5 MB", retention="10 days", enqueue=True)

security = HTTPBasic()

def verify_docs_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username.strip(), "admin")
    correct_password = secrets.compare_digest(credentials.password.strip(), settings.admin_secret)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

app = FastAPI(
    title="SurveyCXM Login Intelligence Popup API",
    description="Delivers NPS delta, demographic breakdown, critical issues, and AI summary on login",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

@app.get("/docs", include_in_schema=False)
async def get_protected_docs(credentials: HTTPBasicCredentials = Depends(verify_docs_auth)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="SurveyCXM API Docs")

@app.get("/redoc", include_in_schema=False)
async def get_protected_redoc(credentials: HTTPBasicCredentials = Depends(verify_docs_auth)):
    return get_redoc_html(openapi_url="/openapi.json", title="SurveyCXM API ReDoc")

@app.get("/openapi.json", include_in_schema=False)
async def get_protected_openapi(credentials: HTTPBasicCredentials = Depends(verify_docs_auth)):
    return get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(popup_router, prefix="/api", tags=["Popup Intelligence"])

from routes.review_suggestion import router as review_suggestion_router
app.include_router(review_suggestion_router, prefix="/api", tags=["Review Suggestion"])


@app.on_event("startup")
async def startup():
    logger.info("🚀 SurveyCXM Popup API starting up...")
    svc = get_db_service()
    if svc:
        logger.info("✅ Database pre-warmed successfully")
    else:
        logger.warning("⚠️  Running without DB — mock data mode active")
    
    # Display the API link in the console so it can be clicked
    logger.info("🌐 API is available at: http://127.0.0.1:8000/")


@app.get("/")
def root():
    return {
        "service": "SurveyCXM Login Intelligence Popup API",
        "version": "1.0.0",
        "docs": "/docs",
    }

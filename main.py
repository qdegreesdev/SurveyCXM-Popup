import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

# Configure logger to write to a file
logger.add("app.log", rotation="5 MB", retention="10 days", enqueue=True)

# Intercept uvicorn logs
for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = [InterceptHandler()]
    logging_logger.propagate = False

from routes.popup import router as popup_router
from config import settings

# Pre-warm DB connection on startup
from database import get_db_service

app = FastAPI(
    title="SurveyCXM Login Intelligence Popup API",
    description="Delivers NPS delta, demographic breakdown, critical issues, and AI summary on login",
    version="1.0.0",
)

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

"""
Popup API Route

DATE LOGIC:
  - Accept `last_login` as ISO datetime string from the frontend.
  - current_period  : last_login → now      (what changed since you were here)
  - previous_period : equal window before last_login  (for comparison)
  - All W1/W2 week concepts removed.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Form, BackgroundTasks, Request, Depends, Header
from fastapi.responses import PlainTextResponse, FileResponse
import os
import uuid
from loguru import logger

from config import settings
import database
from database import get_db_service
from services.ai_service import generate_ai_summary, answer_user_question
from services.mock_data import get_mock_popup_data
from services.tts_service import generate_audio_file
import json
import secrets
from services.popup_service import parse_datetime, aggregate_issues, _DEFAULT_LAST_LOGIN_HOURS

router = APIRouter()

def verify_secret(provided_key: str, expected_key: str) -> bool:
    if not provided_key or not expected_key:
        return False
    clean_provided = provided_key.strip('"')
    clean_expected = expected_key.strip('"')
    return secrets.compare_digest(clean_provided, clean_expected)

def verify_admin(x_admin_secret: str = Header(None)):
    if not x_admin_secret or not verify_secret(x_admin_secret, settings.admin_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/audio/{filename}")
async def get_audio(filename: str):
    import asyncio
    # Security: Prevent Path Traversal attacks
    clean_filename = os.path.basename(filename)
    if clean_filename != filename or not filename.endswith(".mp3"):
        raise HTTPException(status_code=400, detail="Invalid audio filename")

    audio_dir = os.path.abspath(os.path.join("static", "audio"))
    filepath = os.path.abspath(os.path.join(audio_dir, filename))

    if not filepath.startswith(audio_dir):
        raise HTTPException(status_code=400, detail="Access denied")

    # Wait up to 30 seconds for the audio file to be generated in the background
    for _ in range(60):
        if os.path.exists(filepath):
            return FileResponse(filepath, media_type="audio/mpeg")
        await asyncio.sleep(0.5)

    raise HTTPException(status_code=404, detail="Audio file not found or generation timed out")


from services.rate_limiter import rate_limiter

@router.post("/ask-ai")
async def ask_ai(
    request: Request,
    client_id: int = Form(...),
    user_last_login_date: str = Form(...),
    user_current_login_date: str = Form(...),
    question: str = Form(..., description="User question about CX metrics"),
    secretKey: str = Form(..., description="API secret key or admin secret"),
    chat_history: Optional[str] = Form(None, description="Optional JSON array of previous chat messages")
):
    rate_limiter.check_rate_limit(request, "ask_ai", settings.rate_limit_ask_ai)
    if not (verify_secret(secretKey, settings.api_secret_key) or verify_secret(secretKey, settings.admin_secret)):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if client_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid client ID. Must be a positive integer.")

    logger.info(f"API Request: POST /api/ask-ai | client_id={client_id}")

    clean_question = (question or "").strip()
    if not clean_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(clean_question) > settings.max_question_length:
        raise HTTPException(status_code=400, detail=f"Question exceeds maximum length of {settings.max_question_length} characters.")
    question = clean_question
    current_login_dt = parse_datetime(user_current_login_date, is_end_date=True)
    last_login_dt    = parse_datetime(user_last_login_date, default_offset_hours=_DEFAULT_LAST_LOGIN_HOURS)

    if last_login_dt > current_login_dt:
        raise HTTPException(status_code=400, detail="Last login date cannot be in the future relative to the current login date.")

    if settings.use_mock_data:
        return {"answer": "Database is unavailable. Cannot answer questions without real time data."}

    db = get_db_service()
    if not database.DB_AVAILABLE or db is None:
        return {"answer": "Database is unavailable. Cannot answer questions without real time data."}

    client_info = db.get_client_by_id(client_id)
    if not client_info:
        return {"answer": "Invalid client ID or client is inactive."}
    survey_ids = db.get_survey_ids_by_client(client_id) or []
    if not survey_ids:
        return {"answer": "No active surveys found for this client."}

    try:
        import asyncio

        # Concurrently fetch live metrics with error isolation
        results = await asyncio.gather(
            asyncio.to_thread(db.get_nps_data_for_surveys, survey_ids, last_login_dt, current_login_dt),
            asyncio.to_thread(db.get_demographic_breakdown_for_surveys, survey_ids, last_login_dt, current_login_dt),
            asyncio.to_thread(db.get_customer_voice_data_for_surveys, survey_ids, last_login_dt, current_login_dt),
            asyncio.to_thread(db.get_survey_comparison, survey_ids, last_login_dt, current_login_dt),
            return_exceptions=True
        )

        nps_data = results[0] if not isinstance(results[0], Exception) else {}
        demographics = results[1] if not isinstance(results[1], Exception) else []
        voice = results[2] if not isinstance(results[2], Exception) else {}
        survey_comparison = results[3] if not isinstance(results[3], Exception) else []

        if not nps_data:
            nps_data = {
                "current": 0,
                "previous": 0,
                "delta": 0,
                "total_responses": 0,
                "promoters_pct": 0,
                "passives_pct": 0,
                "detractors_pct": 0,
                "current_period_label": f"{last_login_dt.strftime('%d/%m/%Y')} to {current_login_dt.strftime('%d/%m/%Y')}"
            }

        demographics = demographics or []
        survey_comparison = survey_comparison or []
        voice = voice or {}
        critical_issues = await asyncio.to_thread(aggregate_issues, voice.get("high_severity_records", []))
        parsed_chat_history = []
        if chat_history:
            try:
                parsed_chat_history = json.loads(chat_history)
                if not isinstance(parsed_chat_history, list):
                    parsed_chat_history = []
            except Exception as parse_err:
                logger.warning(f"Failed to parse chat_history JSON: {parse_err}")
                parsed_chat_history = []

        answer = await asyncio.to_thread(
            answer_user_question,
            nps_data,
            demographics,
            critical_issues,
            question,
            survey_comparison,
            parsed_chat_history
        )
        return {"answer": answer}
    except Exception as e:
        logger.error(f"Ask AI endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating AI response.")


@router.post("/login-popup-summary")
async def login_popup_summary(
    request: Request,
    background_tasks: BackgroundTasks,
    client_id: int = Form(...),
    user_last_login_date: str = Form(...),
    user_current_login_date: str = Form(...),
    secretKey: str = Form(...)
):
    rate_limiter.check_rate_limit(request, "login_popup_summary", settings.rate_limit_popup_summary)
    if not (verify_secret(secretKey, settings.api_secret_key) or verify_secret(secretKey, settings.admin_secret)):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if client_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid client ID. Must be a positive integer.")

    logger.info(f"API Request: POST /api/login-popup-summary | client_id={client_id}")
    """
    Dedicated endpoint that accepts Form Data, securely queries the user's real name,
    and returns a pre-formatted HTML AI Summary wrapped in <p> and <strong> tags 
    alongside a personalized greeting.
    """
    try:
        last_login_dt = parse_datetime(user_last_login_date, default_offset_hours=_DEFAULT_LAST_LOGIN_HOURS)
        current_login_dt = parse_datetime(user_current_login_date, is_end_date=True)
            
        if last_login_dt > current_login_dt:
            raise HTTPException(status_code=400, detail="Last login date cannot be in the future relative to the current login date.")

        # Build human-readable dates for AI
        last_login_label = last_login_dt.strftime("%b %d, %Y")
        
        # Try explicit base_url from .env
        if settings.base_url:
            base_url = settings.base_url.rstrip("/")
        else:
            # Fallback: construct dynamically from headers (works behind proxy without middleware)
            host = request.headers.get("x-forwarded-host") or request.headers.get("host")
            scheme = request.headers.get("x-forwarded-proto", "http")
            if host:
                base_url = f"{scheme}://{host}"
            else:
                base_url = str(request.base_url).rstrip("/")
        db = get_db_service()
        if not db or not db._ensure_connection() or not database.DB_AVAILABLE or settings.use_mock_data:
            summary_text = "Database is unavailable. Cannot fetch real time data for your briefing."
            summary_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
            background_tasks.add_task(generate_audio_file, text=summary_text, filename=summary_audio_filename)
            return {
                "greeting": f"Good day Client {client_id}",
                "ai_summary": "<p><strong>Database is unavailable.</strong> Cannot fetch real time data for your briefing.</p>",
                "ai_summary_audio_url": f"{base_url}/api/audio/{summary_audio_filename}" if summary_audio_filename else None,
                "top_alert_VOC": [],
                "voc_audio_url": None,
                "is_data_found": 0
            }

        # 0. Validate Client
        client_info = db.get_client_by_id(client_id)
        if not client_info:
            summary_text = "Invalid client ID or client is inactive."
            summary_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
            background_tasks.add_task(generate_audio_file, text=summary_text, filename=summary_audio_filename)
            return {
                "greeting": f"Good day Client {client_id}",
                "ai_summary": "<p><strong>Invalid client ID.</strong> Cannot fetch data.</p>",
                "ai_summary_audio_url": f"{base_url}/api/audio/{summary_audio_filename}" if summary_audio_filename else None,
                "top_alert_VOC": [],
                "voc_audio_url": None,
                "is_data_found": 0
            }

        # 1. Fetch Client Name
        client_name = client_info.get("company_name", f"Client {client_id}")
        
        hour = datetime.now().hour
        greeting_time = "Good Morning"
        if 12 <= hour < 17:
            greeting_time = "Good Afternoon"
        elif hour >= 17:
            greeting_time = "Good Evening"
        greeting = f"{greeting_time}, {client_name}"
        # 2. Fetch surveys
        survey_ids = db.get_survey_ids_by_client(client_id)
        if not survey_ids:
            summary_text = f"Welcome back! Currently, there are no active surveys associated with your account."
            summary_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
            background_tasks.add_task(generate_audio_file, text=summary_text, filename=summary_audio_filename)
            return {
                "greeting": greeting,
                "ai_summary": f"<p>{summary_text}</p>",
                "ai_summary_audio_url": f"{base_url}/api/audio/{summary_audio_filename}" if summary_audio_filename else None,
                "top_alert_VOC": [],
                "voc_audio_url": None,
                "is_data_found": 0
            }
        # 3. Fetch analytics
        import asyncio
        nps_data = await asyncio.to_thread(db.get_nps_data_for_surveys, survey_ids, last_login_dt, current_login_dt)
        
        if not nps_data:
            summary_text = f"Welcome back! There is no new data available since your last login on {last_login_label}."
            summary_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
            background_tasks.add_task(generate_audio_file, text=summary_text, filename=summary_audio_filename)
            return {
                "greeting": greeting,
                "ai_summary": f"<p>Welcome back! There is <strong>no new data available</strong> since your last login on <strong>{last_login_label}</strong>.</p>",
                "ai_summary_audio_url": f"{base_url}/api/audio/{summary_audio_filename}" if summary_audio_filename else None,
                "top_alert_VOC": [],
                "voc_audio_url": None,
                "is_data_found": 0
            }

        demographics, voice, survey_comparison = await asyncio.gather(
            asyncio.to_thread(db.get_demographic_breakdown_for_surveys, survey_ids, last_login_dt, current_login_dt),
            asyncio.to_thread(db.get_customer_voice_data_for_surveys, survey_ids, last_login_dt, current_login_dt),
            asyncio.to_thread(db.get_survey_comparison, survey_ids, last_login_dt, current_login_dt)
        )
        critical_issues = await asyncio.to_thread(aggregate_issues, voice.get("high_severity_records", []))

        ai = await asyncio.to_thread(generate_ai_summary, nps_data, demographics, critical_issues, survey_comparison, last_login_label, current_login_dt, html_format=True)

        top_alert_voc = ai.get("critical_vocs", [])
        if not top_alert_voc:
            top_alert_voc = [{"verbatim": "No VOC found from your last login."}]
            voc_tts_text = "No critical feedback found from your last login."
        else:
            voc_texts = []
            for i, v in enumerate(top_alert_voc):
                text = f"Feedback {i+1}: {v.get('verbatim', '')}"
                if v.get('extra_info'):
                    text += f". From: {v.get('extra_info')}"
                voc_texts.append(text)
            voc_tts_text = "Here is the top customer feedback. " + " ".join(voc_texts)

        # Generate audio for summary and VOCs in the background
        summary_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
        voc_audio_filename = f"tts_{uuid.uuid4().hex}.mp3"
        
        background_tasks.add_task(generate_audio_file, text=ai.get("summary", ""), filename=summary_audio_filename)
        background_tasks.add_task(generate_audio_file, text=voc_tts_text, filename=voc_audio_filename)

        return {
            "greeting": greeting,
            "ai_summary": ai.get("summary", ""),
            "ai_summary_audio_url": f"{base_url}/api/audio/{summary_audio_filename}" if summary_audio_filename else None,
            "top_alert_VOC": top_alert_voc,
            "voc_audio_url": f"{base_url}/api/audio/{voc_audio_filename}" if voc_audio_filename else None,
            "is_data_found": 1
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Login Popup Summary endpoint error: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



@router.get("/health")
async def health():
    """
    Health check endpoint returning both database and RAG vector store health status.
    """
    db = get_db_service()
    db_health = db.test_connection() if db else {"connected": False, "error": "DB service not initialized"}
    
    from services.rag_service import rag_service
    rag_health = rag_service.test_health()
    
    is_db_connected = db_health.get("connected", False)
    is_rag_healthy = rag_health.get("status") == "healthy"
    
    return {
        "status": "healthy" if (is_db_connected and is_rag_healthy) else "degraded",
        "connected": is_db_connected,
        "database": db_health,
        "rag": rag_health
    }

@router.post("/clear-cache", dependencies=[Depends(verify_admin)])
async def clear_cache():
    """
    Clears any internal cache (like the database connection pool instance)
    so that the application is forced to establish a fresh connection on the next request.
    """
    try:
        from database import reset_db_service
        reset_db_service()
        return {"status": "success", "message": "Cache cleared successfully."}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache.")


@router.get("/logs", dependencies=[Depends(verify_admin)])
async def get_logs(lines: int = Query(100, description="Number of tail lines to return")):
    """
    Returns the most recent log details from the server as plain text.
    Protected by admin authorization header (x-admin-secret).
    """
    try:
        from collections import deque
        lines = min(max(1, lines), 1000)
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        log_file = os.path.join(project_dir, "app.log")
        
        if not os.path.exists(log_file):
            return PlainTextResponse("Log file not found or empty.", media_type="text/plain; charset=utf-8")
        
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            tail_lines = list(deque(f, maxlen=lines))

        return PlainTextResponse("".join(tail_lines), media_type="text/plain; charset=utf-8")
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to read logs.")


@router.post("/clear-logs", dependencies=[Depends(verify_admin)])
async def clear_logs():
    """Clears the app.log file and outputs a clear sequence to the terminal."""
    try:
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        log_file = os.path.join(project_dir, "app.log")
        if os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.truncate(0)
        # Send clear screen ANSI code to the terminal
        print("\033c", end="")
        return {"status": "success", "message": "Logs and terminal cleared successfully."}
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear logs.")


@router.post("/clear-pycache", dependencies=[Depends(verify_admin)])
async def clear_pycache():
    """Removes project __pycache__ directories and .pyc files recursively (excluding venv and .git)."""
    try:
        import shutil
        
        project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        exclude_dirs = {"venv", ".venv", "env", ".git", ".idea", ".vscode", "data", "static", "node_modules"}
        
        cleared_dirs = 0
        cleared_files = 0
        
        for root, dirs, files in os.walk(project_dir, topdown=True):
            # Exclude virtual environments and git dirs from traversal
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            # Remove __pycache__ folders
            for d in list(dirs):
                if d == "__pycache__":
                    cache_path = os.path.join(root, d)
                    try:
                        shutil.rmtree(cache_path)
                        cleared_dirs += 1
                        dirs.remove(d)
                    except Exception as err:
                        logger.warning(f"Could not delete {cache_path}: {err}")
            
            # Remove orphan .pyc or .pyo files
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    file_path = os.path.join(root, f)
                    try:
                        os.remove(file_path)
                        cleared_files += 1
                    except Exception as err:
                        logger.warning(f"Could not delete {file_path}: {err}")
                
        return {
            "status": "success",
            "message": f"Cleared {cleared_dirs} project __pycache__ directories and {cleared_files} bytecode files."
        }
    except Exception as e:
        logger.error(f"Error clearing pycache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear pycache.")





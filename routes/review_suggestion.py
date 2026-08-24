import json
import secrets
from fastapi import APIRouter, HTTPException, Form, Request
from services.review_suggestion_service import generate_review_suggestion
from services.rate_limiter import rate_limiter
from loguru import logger
from config import settings

router = APIRouter()

def verify_secret(provided_key: str, expected_key: str) -> bool:
    if not provided_key or not expected_key:
        return False
    clean_provided = provided_key.strip('"')
    clean_expected = expected_key.strip('"')
    return secrets.compare_digest(clean_provided, clean_expected)

@router.post("/survey_review_suggestion")
def get_review_suggestion(
    request: Request,
    secretKey: str = Form(...),
    survey_summary: str = Form(...)
):
    try:
        rate_limiter.check_rate_limit(request, "survey_review_suggestion", settings.rate_limit_review_suggestion)
        # Validate secret key using constant-time comparison
        if not (verify_secret(secretKey, settings.api_secret_key) or verify_secret(secretKey, settings.admin_secret)):
            raise HTTPException(status_code=401, detail="Invalid secret key")

        logger.info("API Request: POST /api/survey_review_suggestion")

        # Payload size safety check (max 50 KB raw string)
        if len(survey_summary) > 50000:
            raise HTTPException(status_code=400, detail="Payload size exceeds limit of 50KB")

        # Clean up any surrounding quotes added by curl
        if survey_summary.startswith('"') and survey_summary.endswith('"'):
            survey_summary = survey_summary[1:-1]
            
        # Clean up literal backslashes that curl might have preserved
        survey_summary = survey_summary.replace('\\"', '"')
        
        # Parse the JSON string from the form data
        survey_data = json.loads(survey_summary)
        
        # In case it was double-encoded and parsed as a string, parse again
        if isinstance(survey_data, str):
            survey_data = json.loads(survey_data)
            
        if not isinstance(survey_data, list):
            raise HTTPException(status_code=400, detail="survey_summary must be a JSON list")
        
        if len(survey_data) == 0:
            raise HTTPException(status_code=400, detail="survey_summary list cannot be empty")

        if len(survey_data) > settings.max_survey_summary_items:
            raise HTTPException(status_code=400, detail=f"survey_summary list exceeds maximum of {settings.max_survey_summary_items} items")

        # Validate item structure
        sanitized_summary = []
        for idx, item in enumerate(survey_data):
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"Item at index {idx} must be a JSON object")
            
            sanitized_summary.append({
                "sequence": item.get("sequence", idx + 1),
                "question": str(item.get("question", "")).strip()[:500],
                "answer": str(item.get("answer", "")).strip()[:1000]
            })
        
        # Pass the parsed and sanitized data to the service
        suggestions = generate_review_suggestion(sanitized_summary)
        return {"suggestions": suggestions}
        
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError: {e} | Payload preview: {survey_summary[:100]}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON format in survey_summary: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in review suggestion endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating review suggestions.")

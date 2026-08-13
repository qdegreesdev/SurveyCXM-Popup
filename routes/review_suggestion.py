import json
from fastapi import APIRouter, HTTPException, Form
from services.review_suggestion_service import generate_review_suggestion
from loguru import logger

router = APIRouter()

@router.post("/survey_review_suggestion")
def get_review_suggestion(
    secretKey: str = Form(...),
    survey_summary: str = Form(...)
):
    try:
        # Clean up any surrounding quotes added by curl
        if secretKey.startswith('"') and secretKey.endswith('"'):
            secretKey = secretKey[1:-1]
            
        # Validate the secretKey
        if secretKey != "my_secret_123":
            raise HTTPException(status_code=401, detail="Invalid secret key")
        
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
        
        # Pass the parsed data to the service
        suggestions = generate_review_suggestion(survey_data)
        return {"suggestions": suggestions}
        
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError: {e} | Payload after cleaning: {survey_summary}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON format in survey_summary: {str(e)}")
    except Exception as e:
        logger.error(f"Error in review suggestion endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

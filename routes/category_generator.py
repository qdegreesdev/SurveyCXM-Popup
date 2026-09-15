import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, Form, Request
from loguru import logger
from config import settings
import database
from database import get_db_service
from services.rate_limiter import rate_limiter
from services.category_service import validate_industry_name, generate_industry_categories

router = APIRouter()

def verify_secret(provided_key: str, expected_key: str) -> bool:
    if not provided_key or not expected_key:
        return False
    clean_provided = provided_key.strip('"')
    clean_expected = expected_key.strip('"')
    return secrets.compare_digest(clean_provided, clean_expected)

@router.post("/generate-categories")
async def generate_categories(
    request: Request,
    secretKey: str = Form(...),
    client_id: int = Form(...),
    survey_id: int = Form(...),
    industry_name: str = Form(...),
    category_creation_count: int = Form(5, description="Number of main categories to create (default 5)"),
    subcategory_creation_count: int = Form(3, description="Number of sub-categories per main category (default 3)")
):
    """
    Generate main categories and sub-categories based on industry name.
    """
    # 0. Rate Limiting Check
    rate_limiter.check_rate_limit(request, "generate_categories", settings.rate_limit_category_generation)

    # 1. Validate Secret Key
    if not (verify_secret(secretKey, settings.api_secret_key) or verify_secret(secretKey, settings.admin_secret)):
        raise HTTPException(status_code=401, detail="Invalid secret key")

    # 2. Validate client_id & survey_id
    if client_id <= 0:
        raise HTTPException(status_code=400, detail="client_id must be a valid positive integer.")
    if survey_id <= 0:
        raise HTTPException(status_code=400, detail="survey_id must be a valid positive integer.")

    # 3. Validate creation counts
    if category_creation_count < 1 or category_creation_count > 20:
        raise HTTPException(status_code=400, detail="category_creation_count must be between 1 and 20.")
    if subcategory_creation_count < 1 or subcategory_creation_count > 20:
        raise HTTPException(status_code=400, detail="subcategory_creation_count must be between 1 and 20.")

    # 4. Validate industry_name
    is_valid_ind, cleaned_industry_or_err = validate_industry_name(industry_name)
    if not is_valid_ind:
        raise HTTPException(status_code=400, detail=f"Invalid industry_name: {cleaned_industry_or_err}")

    industry_name = cleaned_industry_or_err

    logger.info(f"API Request: POST /api/generate-categories | client_id={client_id}, survey_id={survey_id}, industry='{industry_name}', categories_count={category_creation_count}, subcategories_count={subcategory_creation_count}")

    # 5. Generate Main Categories & Sub-Categories based on requested counts
    categories = generate_industry_categories(
        industry_name=industry_name,
        client_id=client_id,
        survey_id=survey_id,
        category_creation_count=category_creation_count,
        subcategory_creation_count=subcategory_creation_count
    )

    # 6. Push Generated Categories to Database when DB is available
    db = get_db_service()
    if db and database.DB_AVAILABLE and not settings.use_mock_data:
        categories = db.save_generated_categories(client_id=client_id, survey_id=survey_id, categories=categories)

    return {
        "status": "success",
        "client_id": client_id,
        "survey_id": survey_id,
        "industry_name": industry_name,
        "category_creation_count": category_creation_count,
        "subcategory_creation_count": subcategory_creation_count,
        "categories": categories
    }

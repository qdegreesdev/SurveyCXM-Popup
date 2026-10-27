"""
SurveyCXM Documentation RAG Route

Provides dedicated endpoints for:
1. Dense semantic documentation vector retrieval & LLM grounded Q&A (/doc-rag-search)
2. Admin vector store index synchronization (/sync-documentation)
"""

import asyncio
import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Form, Request, Depends, Header
from loguru import logger

from config import settings
from services.rate_limiter import rate_limiter
from services.rag_service import rag_service
from services.ai_service import answer_rag_question

router = APIRouter()


def verify_secret(provided_key: str, expected_key: str) -> bool:
    """Safely verifies a provided API secret against expected key using constant-time comparison."""
    if not provided_key or not expected_key:
        return False
    clean_provided = provided_key.strip('"')
    clean_expected = expected_key.strip('"')
    return secrets.compare_digest(clean_provided, clean_expected)


def verify_admin(x_admin_secret: str = Header(None)):
    """Dependency verifying admin credentials via request header."""
    if not x_admin_secret or not verify_secret(x_admin_secret, settings.admin_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/doc-rag-search")
async def doc_rag_search(
    request: Request,
    question: str = Form(..., description="User question about SurveyCXM features, setups, or workflows"),
    secretKey: str = Form(..., description="API secret key or admin secret"),
    chat_history: Optional[str] = Form(None, description="Optional JSON array of previous chat messages")
):
    """
    Dedicated Documentation RAG Search API endpoint.
    Performs dense semantic vector search against indexed official SurveyCXM module documentation
    and generates clear, step-by-step guidance grounded in the knowledge base.
    """
    rate_limiter.check_rate_limit(request, "doc_rag_search", settings.rate_limit_doc_rag_search)
    if not (verify_secret(secretKey, settings.api_secret_key) or verify_secret(secretKey, settings.admin_secret)):
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_question = (question or "").strip()
    if not clean_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(clean_question) > settings.max_question_length:
        raise HTTPException(status_code=400, detail=f"Question exceeds maximum length of {settings.max_question_length} characters.")
    question = clean_question

    logger.info(f"API Request: POST /api/doc-rag-search | question='{question[:60]}...'")

    parsed_chat_history = []
    if chat_history:
        try:
            parsed_chat_history = json.loads(chat_history)
            if not isinstance(parsed_chat_history, list):
                parsed_chat_history = []
        except Exception as parse_err:
            logger.warning(f"Failed to parse chat_history JSON: {parse_err}")
            parsed_chat_history = []

    try:
        # Search documentation vector store
        doc_context = await asyncio.to_thread(rag_service.search_documentation, question, 3, 0.42)

        # Generate grounded response using documentation context
        answer = await asyncio.to_thread(
            answer_rag_question,
            question,
            doc_context,
            parsed_chat_history
        )

        return {
            "answer": answer
        }
    except Exception as e:
        logger.error(f"Doc RAG search error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating RAG response.")


@router.post("/sync-documentation", dependencies=[Depends(verify_admin)])
async def sync_documentation(force: bool = Form(False)):
    """Admin endpoint to re-index documentation_categories into ChromaDB vector store."""
    try:
        result = await asyncio.to_thread(rag_service.sync_documentation_index, force=force)
        return result
    except Exception as e:
        logger.error(f"Error syncing documentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync documentation: {e}")

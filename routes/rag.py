"""
SurveyCXM Documentation RAG Route

Provides dedicated endpoints for:
1. Multi-Stage Hybrid RAG documentation retrieval & LLM grounded Q&A (/doc-rag-search)
2. Real-Time Token Streaming with sub-250ms TTFT (/doc-rag-search/stream)
3. Semantic Response Caching (< 5 ms lookup for previously answered queries)
4. Contextual Query Rewriting (resolving multi-turn references)
5. Production Observability and Telemetry Tracing
6. Admin vector store index synchronization (/sync-documentation)
"""

import asyncio
import json
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Form, Request, Depends, Header
from fastapi.responses import StreamingResponse
from loguru import logger

from config import settings
from services.rate_limiter import rate_limiter
from services.rag_service import rag_service
from services.ai_service import answer_rag_question, stream_rag_question
from services.cache_service import cache_service
from services.query_rewriter import rewrite_query_async
from services.observability_service import observability_service, TraceRecord

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
    chat_history: Optional[str] = Form(None, description="Optional JSON array of previous chat messages"),
    stream: bool = Form(False, description="Enable SSE real-time token streaming")
):
    """
    Dedicated Documentation RAG Search API endpoint.
    Performs Multi-Stage Hybrid Retrieval (Dense ONNX vectors + Sparse BM25 + FlashRank reranking),
    supports Semantic Caching, Contextual Query Rewriting, and Real-Time SSE Token Streaming.
    """
    start_req_time = time.time()
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

    # 1. Contextual Query Rewriting for Multi-Turn Conversations
    effective_question, was_rewritten = await rewrite_query_async(question, parsed_chat_history)

    # 2. Semantic Response Cache Check (< 15 ms lookup)
    cached_result = cache_service.get(namespace="doc_rag", query=effective_question)
    if cached_result:
        total_lat_ms = (time.time() - start_req_time) * 1000
        observability_service.record_trace(TraceRecord(
            endpoint="doc-rag-search",
            raw_question=question,
            rewritten_question=effective_question,
            was_rewritten=was_rewritten,
            cache_hit=True,
            cache_hit_type=cached_result.get("hit_type"),
            cache_similarity=cached_result.get("similarity", 1.0),
            retrieval_ms=0.0,
            llm_time_ms=0.0,
            total_latency_ms=total_lat_ms,
            stream_mode=stream,
            tokens_prompt_est=0,
            tokens_completion_est=len(cached_result["answer"].split()) * 2,
            status="success"
        ))

        if stream:
            return StreamingResponse(
                cache_service.stream_cached_response(cached_result["answer"]),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        return {
            "answer": cached_result["answer"],
            "cached": True,
            "hit_type": cached_result.get("hit_type")
        }

    # 3. Hybrid Retrieval + LLM Synthesis Pipeline
    try:
        t_retrieval_start = time.time()
        doc_context = await asyncio.to_thread(rag_service.search_documentation, effective_question, 3, 0.42)
        retrieval_ms = (time.time() - t_retrieval_start) * 1000

        # Streaming Path
        if stream:
            async def _stream_and_track():
                tokens_accum = []
                t_llm_start = time.time()
                try:
                    async for chunk in stream_rag_question(
                        question=effective_question,
                        doc_context=doc_context,
                        chat_history=parsed_chat_history
                    ):
                        yield chunk
                        if chunk.startswith("data: "):
                            data_part = chunk[6:].strip()
                            if data_part != "[DONE]":
                                try:
                                    p = json.loads(data_part)
                                    if p.get("token"):
                                        tokens_accum.append(p["token"])
                                except Exception:
                                    pass

                    full_answer = "".join(tokens_accum).strip()
                    llm_ms = (time.time() - t_llm_start) * 1000
                    total_ms = (time.time() - start_req_time) * 1000

                    if full_answer:
                        cache_service.set(namespace="doc_rag", query=effective_question, answer=full_answer)

                    observability_service.record_trace(TraceRecord(
                        endpoint="doc-rag-search",
                        raw_question=question,
                        rewritten_question=effective_question,
                        was_rewritten=was_rewritten,
                        cache_hit=False,
                        retrieval_ms=retrieval_ms,
                        llm_time_ms=llm_ms,
                        total_latency_ms=total_ms,
                        stream_mode=True,
                        tokens_prompt_est=len(effective_question.split()) * 2 + 1000,
                        tokens_completion_est=len(full_answer.split()) * 2,
                        status="success"
                    ))
                except Exception as stream_err:
                    observability_service.record_trace(TraceRecord(
                        endpoint="doc-rag-search",
                        raw_question=question,
                        rewritten_question=effective_question,
                        was_rewritten=was_rewritten,
                        cache_hit=False,
                        retrieval_ms=retrieval_ms,
                        llm_time_ms=0.0,
                        total_latency_ms=(time.time() - start_req_time) * 1000,
                        stream_mode=True,
                        status="error",
                        error_message=str(stream_err)
                    ))
                    raise

            return StreamingResponse(
                _stream_and_track(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )

        # Standard Non-Streaming Path
        t_llm_start = time.time()
        answer = await asyncio.to_thread(
            answer_rag_question,
            effective_question,
            doc_context,
            parsed_chat_history
        )
        llm_ms = (time.time() - t_llm_start) * 1000
        total_ms = (time.time() - start_req_time) * 1000

        # Cache valid response
        cache_service.set(namespace="doc_rag", query=effective_question, answer=answer)

        # Record telemetry trace
        observability_service.record_trace(TraceRecord(
            endpoint="doc-rag-search",
            raw_question=question,
            rewritten_question=effective_question,
            was_rewritten=was_rewritten,
            cache_hit=False,
            retrieval_ms=retrieval_ms,
            llm_time_ms=llm_ms,
            total_latency_ms=total_ms,
            stream_mode=False,
            tokens_prompt_est=len(effective_question.split()) * 2 + 1000,
            tokens_completion_est=len(answer.split()) * 2,
            status="success"
        ))

        return {
            "answer": answer,
            "cached": False
        }
    except Exception as e:
        logger.error(f"Doc RAG search error: {e}")
        observability_service.record_trace(TraceRecord(
            endpoint="doc-rag-search",
            raw_question=question,
            rewritten_question=effective_question,
            was_rewritten=was_rewritten,
            total_latency_ms=(time.time() - start_req_time) * 1000,
            status="error",
            error_message=str(e)
        ))
        raise HTTPException(status_code=500, detail="Internal server error generating RAG response.")


@router.post("/doc-rag-search/stream", summary="Real-time SSE token streaming for Documentation RAG")
async def doc_rag_search_stream(
    request: Request,
    question: str = Form(..., description="User question about documentation"),
    secretKey: str = Form(..., description="API secret key or admin secret"),
    chat_history: Optional[str] = Form(None, description="Optional JSON array of previous chat messages")
):
    """Dedicated endpoint for real-time SSE token streaming of Documentation RAG responses."""
    return await doc_rag_search(
        request=request,
        question=question,
        secretKey=secretKey,
        chat_history=chat_history,
        stream=True
    )


@router.post("/sync-documentation", dependencies=[Depends(verify_admin)])
async def sync_documentation(force: bool = Form(False)):
    """Admin endpoint to re-index documentation_categories into ChromaDB vector store."""
    try:
        result = await asyncio.to_thread(rag_service.sync_documentation_index, force=force)
        # Automatically invalidate cached documentation answers upon reindexing
        cache_service.invalidate_namespace("doc_rag")
        return result
    except Exception as e:
        logger.error(f"Error syncing documentation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync documentation: {e}")

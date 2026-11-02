"""
SurveyCXM Observability & Telemetry Router

Endpoints:
- GET  /api/observability/stats       (Query latency percentiles, hit rates, token spend)
- GET  /api/observability/traces      (Recent query execution traces)
- GET  /api/observability/cache       (Semantic cache status & metrics)
- POST /api/observability/cache/clear (Manually clear semantic cache)
- POST /api/observability/clear       (Clear telemetry traces)
"""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from config import settings
from services.cache_service import cache_service
from services.observability_service import observability_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/observability", tags=["Observability & Tracing"])


def _verify_auth(request: Request, secret_key: Optional[str] = None):
    """
    Verifies authentication via a single secretKey parameter.
    Also transparently checks request headers for backward compatibility.
    """
    key = (
        secret_key
        or request.headers.get("x-admin-secret")
        or request.headers.get("secretKey")
        or request.headers.get("x-secret-key")
    )
    if not key:
        raise HTTPException(status_code=401, detail="Unauthorized. Invalid or missing secret key.")

    clean_key = key.strip('"')
    if settings.api_secret_key and secrets.compare_digest(clean_key, settings.api_secret_key.strip('"')):
        return True
    if settings.admin_secret and secrets.compare_digest(clean_key, settings.admin_secret.strip('"')):
        return True

    raise HTTPException(status_code=401, detail="Unauthorized. Invalid or missing secret key.")


@router.get("/stats", summary="Query operational performance statistics and percentiles")
async def get_observability_stats(
    request: Request,
    secretKey: Optional[str] = Query(None, description="API secret key or admin secret")
):
    _verify_auth(request, secretKey)
    summary = observability_service.get_summary()
    cache_stats = cache_service.get_stats()
    return {
        "status": "success",
        "telemetry": summary,
        "cache": cache_stats
    }


@router.get("/traces", summary="Retrieve recent query execution traces")
async def get_observability_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    endpoint: Optional[str] = Query(None),
    secretKey: Optional[str] = Query(None, description="API secret key or admin secret")
):
    _verify_auth(request, secretKey)
    traces = observability_service.get_traces(limit=limit, endpoint=endpoint)
    return {
        "status": "success",
        "count": len(traces),
        "traces": traces
    }


@router.get("/cache", summary="Get semantic response cache metrics")
async def get_cache_stats(
    request: Request,
    secretKey: Optional[str] = Query(None, description="API secret key or admin secret")
):
    _verify_auth(request, secretKey)
    return {
        "status": "success",
        "cache": cache_service.get_stats()
    }


@router.post("/cache/clear", summary="Clear semantic cache entries")
async def clear_cache(
    request: Request,
    secretKey: Optional[str] = Query(None, description="API secret key or admin secret")
):
    _verify_auth(request, secretKey)
    cache_service.clear()
    return {"status": "success", "message": "Semantic cache cleared successfully."}


@router.post("/clear", summary="Clear observability trace buffer")
async def clear_traces(
    request: Request,
    secretKey: Optional[str] = Query(None, description="API secret key or admin secret")
):
    _verify_auth(request, secretKey)
    observability_service.clear()
    return {"status": "success", "message": "Observability trace buffer cleared."}


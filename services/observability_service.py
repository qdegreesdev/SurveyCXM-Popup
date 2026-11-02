"""
SurveyCXM Observability & Telemetry Service

Provides production-grade tracing, latency tracking, token spend estimation,
cache analytics, and query execution telemetry for Ask AI and Doc RAG subsystems.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Optional
import uuid

logger = logging.getLogger(__name__)


class TraceRecord:
    """Represents a single query execution lifecycle trace."""
    def __init__(
        self,
        endpoint: str,
        raw_question: str,
        client_id: Optional[int] = None,
        rewritten_question: Optional[str] = None,
        was_rewritten: bool = False,
        cache_hit: bool = False,
        cache_hit_type: Optional[str] = None,
        cache_similarity: float = 0.0,
        retrieval_ms: float = 0.0,
        llm_time_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        stream_mode: bool = False,
        tokens_prompt_est: int = 0,
        tokens_completion_est: int = 0,
        status: str = "success",
        error_message: Optional[str] = None
    ):
        self.trace_id = uuid.uuid4().hex[:12]
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.endpoint = endpoint
        self.client_id = client_id
        self.raw_question = raw_question
        self.rewritten_question = rewritten_question or raw_question
        self.was_rewritten = was_rewritten
        self.cache_hit = cache_hit
        self.cache_hit_type = cache_hit_type
        self.cache_similarity = round(float(cache_similarity or 0.0), 4)
        self.retrieval_ms = round(float(retrieval_ms or 0.0), 2)
        self.llm_time_ms = round(float(llm_time_ms or 0.0), 2)
        self.total_latency_ms = round(float(total_latency_ms or 0.0), 2)
        self.stream_mode = bool(stream_mode)
        self.tokens_prompt_est = int(tokens_prompt_est or 0)
        self.tokens_completion_est = int(tokens_completion_est or 0)
        self.total_tokens_est = int(self.tokens_prompt_est + self.tokens_completion_est)
        self.status = str(status)
        self.error_message = str(error_message) if error_message else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "endpoint": self.endpoint,
            "client_id": self.client_id,
            "raw_question": self.raw_question,
            "rewritten_question": self.rewritten_question,
            "was_rewritten": self.was_rewritten,
            "cache_hit": self.cache_hit,
            "cache_hit_type": self.cache_hit_type,
            "cache_similarity": float(self.cache_similarity),
            "retrieval_ms": float(self.retrieval_ms),
            "llm_time_ms": float(self.llm_time_ms),
            "total_latency_ms": float(self.total_latency_ms),
            "stream_mode": self.stream_mode,
            "tokens_prompt_est": int(self.tokens_prompt_est),
            "tokens_completion_est": int(self.tokens_completion_est),
            "total_tokens_est": int(self.total_tokens_est),
            "status": self.status,
            "error_message": self.error_message
        }


class ObservabilityService:
    """
    In-memory ring-buffer telemetry store for query traces and operational analytics.
    """
    def __init__(self, max_traces: int = 1000):
        self.max_traces = max_traces
        self._traces: deque[TraceRecord] = deque(maxlen=max_traces)
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_errors = 0
        self._total_tokens_spent = 0
        self._total_tokens_saved = 0

    def record_trace(self, trace: TraceRecord):
        """Records a new execution trace into the telemetry buffer."""
        with self._lock:
            self._traces.append(trace)
            self._total_requests += 1
            if trace.status != "success":
                self._total_errors += 1
            if trace.cache_hit:
                self._total_tokens_saved += trace.total_tokens_est or 500
            else:
                self._total_tokens_spent += trace.total_tokens_est

        log_level = logging.INFO if trace.status == "success" else logging.WARNING
        logger.log(
            log_level,
            f"📊 [TRACE {trace.trace_id}] endpoint={trace.endpoint} latency={trace.total_latency_ms}ms "
            f"cache_hit={trace.cache_hit} rewritten={trace.was_rewritten} status={trace.status}"
        )

    def get_summary(self) -> dict[str, Any]:
        """Calculates aggregated performance percentiles and metrics."""
        with self._lock:
            trace_list = list(self._traces)
            total = len(trace_list)

            if total == 0:
                return {
                    "total_requests_recorded": 0,
                    "active_traces_in_buffer": 0,
                    "cache_hit_rate_pct": 0.0,
                    "avg_latency_ms": 0.0,
                    "p50_latency_ms": 0.0,
                    "p95_latency_ms": 0.0,
                    "total_tokens_spent_est": self._total_tokens_spent,
                    "total_tokens_saved_est": self._total_tokens_saved,
                    "error_rate_pct": 0.0,
                    "endpoint_distribution": {},
                }

            latencies = sorted([t.total_latency_ms for t in trace_list])
            p50 = latencies[int(len(latencies) * 0.50)]
            p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
            avg_lat = sum(latencies) / total

            cache_hits = sum(1 for t in trace_list if t.cache_hit)
            rewritten_count = sum(1 for t in trace_list if t.was_rewritten)
            errors = sum(1 for t in trace_list if t.status != "success")

            endpoints: dict[str, int] = {}
            for t in trace_list:
                endpoints[t.endpoint] = endpoints.get(t.endpoint, 0) + 1

            return {
                "total_requests_recorded": self._total_requests,
                "active_traces_in_buffer": total,
                "cache_hits_in_buffer": cache_hits,
                "cache_hit_rate_pct": round((cache_hits / total) * 100.0, 2),
                "contextual_rewrites_in_buffer": rewritten_count,
                "error_rate_pct": round((errors / total) * 100.0, 2),
                "avg_latency_ms": round(avg_lat, 2),
                "p50_latency_ms": round(p50, 2),
                "p95_latency_ms": round(p95, 2),
                "total_tokens_spent_est": self._total_tokens_spent,
                "total_tokens_saved_est": self._total_tokens_saved,
                "endpoint_distribution": endpoints
            }

    def get_traces(self, limit: int = 50, endpoint: Optional[str] = None) -> list[dict[str, Any]]:
        """Returns the most recent execution traces."""
        with self._lock:
            filtered = list(self._traces)
            if endpoint:
                filtered = [t for t in filtered if t.endpoint == endpoint]
            # Return most recent first
            return [t.to_dict() for t in reversed(filtered[-limit:])]

    def clear(self):
        """Clears all traces in the buffer."""
        with self._lock:
            self._traces.clear()
            self._total_requests = 0
            self._total_errors = 0
            self._total_tokens_spent = 0
            self._total_tokens_saved = 0
            logger.info("Observability traces cleared.")


# Global singleton instance
observability_service = ObservabilityService()


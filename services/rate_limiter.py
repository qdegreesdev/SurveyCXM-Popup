import time
from collections import defaultdict
from fastapi import Request, HTTPException, status
from loguru import logger

class RateLimiter:
    """
    In-memory sliding window rate limiter per client IP address.
    Zero external dependencies, supports proxy headers (X-Forwarded-For / X-Real-IP).
    """
    def __init__(self):
        self._history = defaultdict(lambda: defaultdict(list))
        self._last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "127.0.0.1"

    def _cleanup_old_entries(self, now: float):
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        for endpoint in list(self._history.keys()):
            for ip in list(self._history[endpoint].keys()):
                self._history[endpoint][ip] = [
                    t for t in self._history[endpoint][ip] if now - t < 120
                ]
                if not self._history[endpoint][ip]:
                    del self._history[endpoint][ip]

    def check_rate_limit(self, request: Request, endpoint_key: str, max_requests: int, window_seconds: int = 60):
        now = time.time()
        self._cleanup_old_entries(now)

        client_ip = self._get_client_ip(request)
        ip_history = self._history[endpoint_key][client_ip]

        window_start = now - window_seconds
        valid_requests = [t for t in ip_history if t >= window_start]
        self._history[endpoint_key][client_ip] = valid_requests

        if len(valid_requests) >= max_requests:
            retry_after = int(window_seconds - (now - valid_requests[0]))
            retry_after = max(1, retry_after)
            logger.warning(
                f"Rate limit exceeded for IP {client_ip} on endpoint '{endpoint_key}'. "
                f"Count: {len(valid_requests)}/{max_requests} in {window_seconds}s."
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds} seconds allowed. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )

        self._history[endpoint_key][client_ip].append(now)

rate_limiter = RateLimiter()

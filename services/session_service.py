"""
SurveyCXM Server-Side Session History Service

Automatically maintains rolling conversational memory for client chat sessions
so the frontend does NOT need to manage or pass chat_history manually.
"""

import logging
import threading
import time
from typing import Any, Optional

from fastapi import Request

logger = logging.getLogger(__name__)


class SessionService:
    """
    Thread-safe in-memory session history manager with TTL expiration.
    Allows API callers to maintain multi-turn chat memory automatically.
    """
    def __init__(self, ttl_seconds: int = 1800, max_turns: int = 8):
        self.ttl = ttl_seconds
        self.max_turns = max_turns
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _extract_caller_identifier(self, request: Request, session_id: Optional[str] = None) -> str:
        """Extracts the caller identity: explicit session_id -> header -> IP."""
        if session_id and str(session_id).strip():
            return f"sess:{str(session_id).strip()}"

        hdr = request.headers.get("x-session-id") or request.headers.get("session-id")
        if hdr and hdr.strip():
            return f"sess:{hdr.strip()}"

        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        elif request.client and request.client.host:
            ip = request.client.host
        else:
            ip = "anonymous"

        return f"ip:{ip}"

    def resolve_session_key(
        self,
        request: Request,
        session_id: Optional[str] = None,
        client_id: Optional[Any] = None
    ) -> str:
        """
        Determines the unique caller session key:
        - If client_id is provided: scopes to client + caller (e.g. 'client:4:ip:1.2.3.4')
          so multiple users within the same tenant maintain isolated memory.
        - Otherwise: scopes directly to caller (e.g. 'ip:1.2.3.4' or 'sess:xyz').
        """
        caller_id = self._extract_caller_identifier(request, session_id)
        if client_id and str(client_id).strip():
            return f"client:{str(client_id).strip()}:{caller_id}"
        return caller_id

    def get_history(self, session_key: str) -> list[dict[str, str]]:
        """Retrieves recent conversation turns for this session if not expired."""
        now = time.time()
        with self._lock:
            sess = self._sessions.get(session_key)
            if sess:
                if now - sess["last_active"] <= self.ttl:
                    sess["last_active"] = now
                    return list(sess["history"])
                else:
                    self._sessions.pop(session_key, None)
        return []

    def add_turn(self, session_key: str, question: str, answer: str):
        """Records a completed user question and assistant answer in this session."""
        if not question or not answer:
            return

        # Strip HTML for cleaner history storage
        clean_ans = answer.strip()
        now = time.time()

        with self._lock:
            if session_key not in self._sessions:
                self._sessions[session_key] = {
                    "history": [],
                    "last_active": now
                }
            sess = self._sessions[session_key]
            sess["last_active"] = now
            sess["history"].append({"role": "user", "content": question.strip()})
            sess["history"].append({"role": "assistant", "content": clean_ans})

            # Keep sliding window of last N turns (user + assistant = 2 * max_turns)
            if len(sess["history"]) > self.max_turns * 2:
                sess["history"] = sess["history"][-self.max_turns * 2:]

            # Periodic cleanup if session table grows large
            if len(self._sessions) > 500:
                self._cleanup_expired_locked(now)

    def clear_session(self, session_key: str):
        """Clears session history for a specific caller."""
        with self._lock:
            self._sessions.pop(session_key, None)

    def _cleanup_expired_locked(self, now: float):
        """Removes sessions that have exceeded the TTL."""
        expired = [k for k, v in self._sessions.items() if now - v["last_active"] > self.ttl]
        for k in expired:
            self._sessions.pop(k, None)


# Global singleton instance
session_service = SessionService()


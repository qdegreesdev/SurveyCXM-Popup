"""
SurveyCXM Contextual Query Rewriter Service

Optimizes multi-turn follow-up queries by resolving conversational pronouns and references
(e.g., "How do I enable it?", "Tell me more about that", "Why did it drop?") into self-contained
search queries for precise Hybrid RAG and analytical metrics retrieval.
"""

import asyncio
import logging
import re
from typing import Optional

from openai import AsyncOpenAI, OpenAI
from config import settings

logger = logging.getLogger(__name__)

import json
import ast
from typing import Any

# Heuristic reference patterns that signal a contextual follow-up
CONVERSATIONAL_TRIGGERS = re.compile(
    r'\b(it|this|that|them|these|those|they|its|previous|above|former|latter|'
    r'again|first one|second one|third one|why|how to enable|how to setup|'
    r'how to configure|explain more|tell me more|more details|my name|who am i|'
    r'remember me|what is my)\b',
    re.IGNORECASE
)


PERSONAL_OR_CONVERSATIONAL_REGEX = re.compile(
    r'\b(my name|who am i|my email|call me|what is my name|remember me|who i am|my role|what is my role)\b',
    re.IGNORECASE
)


def is_conversational_query(question: str) -> bool:
    """Returns True if the query asks about personal identity or conversational state."""
    if not question:
        return False
    return bool(PERSONAL_OR_CONVERSATIONAL_REGEX.search(question))


def clean_and_parse_chat_history(raw_history: Any) -> list[dict[str, str]]:
    """
    Universally and robustly parses chat history from any client input:
    - Standard JSON string with double quotes: '[{"role": "user", "content": "..."}]'
    - Single-quoted string (Python-style): "[{'role': 'user', 'content': '...'}]"
    - Raw Python list of dicts: [{"role": "user", "content": "..."}]
    - Single dictionary object: {"role": "user", "content": "..."}
    - Plain string (e.g. "my name is jitesh"): converted to user turn
    - Alternative keys ('message', 'text', 'prompt', 'query', 'user' -> 'content')
    - Alternative role keys ('sender', 'author', 'type' -> 'role')
    """
    if not raw_history:
        return []

    parsed = None
    if isinstance(raw_history, list):
        parsed = raw_history
    elif isinstance(raw_history, dict):
        parsed = [raw_history]
    elif isinstance(raw_history, str):
        clean_str = raw_history.strip()
        if not clean_str:
            return []
        try:
            parsed = json.loads(clean_str)
        except Exception:
            try:
                parsed = ast.literal_eval(clean_str)
            except Exception:
                parsed = [{"role": "user", "content": clean_str}]

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        parsed = [{"role": "user", "content": str(parsed)}]

    normalized: list[dict[str, str]] = []
    for item in parsed:
        if isinstance(item, dict):
            content = (
                item.get("content")
                or item.get("message")
                or item.get("text")
                or item.get("query")
                or item.get("user")
                or item.get("prompt")
                or ""
            )
            role = item.get("role") or item.get("sender") or item.get("author") or "user"
            if role not in ["user", "assistant"]:
                role = "user"
            if content and str(content).strip():
                normalized.append({"role": role, "content": str(content).strip()})
        elif isinstance(item, str) and item.strip():
            normalized.append({"role": "user", "content": item.strip()})

    return normalized


def needs_rewriting(question: str, chat_history: Optional[list]) -> bool:
    """
    Fast heuristic pre-check (< 0.1 ms).
    Returns True only if chat history exists and question appears context-dependent.
    """
    if not chat_history or not isinstance(chat_history, list) or len(chat_history) == 0:
        return False

    clean_q = question.strip()

    # Direct personal identity queries should stay intact so the LLM directly reads user introduction
    if is_conversational_query(clean_q):
        return False
    words = clean_q.split()

    # Short follow-ups (<= 3 words, e.g. "Why?", "How so?", "Where?") are almost always context-dependent
    if len(words) <= 3:
        return True

    # Check for pronoun or anaphoric references
    if CONVERSATIONAL_TRIGGERS.search(clean_q):
        return True

    return False


def _build_rewriter_messages(question: str, chat_history: list) -> list[dict[str, str]]:
    """Formats recent conversation turns for the condenser prompt."""
    formatted_history = []
    # Take up to last 4 turns
    for msg in chat_history[-4:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            role = "User" if msg["role"] == "user" else "Assistant"
            content = str(msg["content"])
            # Strip HTML tags if assistant response contained HTML
            content = re.sub(r'<[^>]+>', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()
            formatted_history.append(f"{role}: {content[:300]}")

    history_str = "\n".join(formatted_history)

    system_prompt = (
        "You are an expert search query reformulation engine for SurveyCXM (a customer experience and survey platform).\n"
        "Your task is to rewrite a follow-up user question into a standalone, complete, and self-contained search query "
        "that resolves all pronouns (such as 'it', 'that', 'this', 'they') using the conversation context.\n\n"
        "Rules:\n"
        "1. Return ONLY the rewritten question as plain text. Do not add quotes, markdown, greetings, or explanations.\n"
        "2. Do NOT answer the question. Only reformulate it.\n"
        "3. Preserve the user's core intent while adding necessary platform feature or metric context from the prior turns.\n"
        "4. If the question is already fully self-contained and clear, return it unchanged."
    )

    user_prompt = (
        f"Conversation History:\n{history_str}\n\n"
        f"Follow-up Question: {question}\n\n"
        f"Standalone Rewritten Query:"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


async def rewrite_query_async(question: str, chat_history: Optional[list]) -> tuple[str, bool]:
    """
    Asynchronously rewrites a contextual query into a standalone query.
    Returns (effective_question, was_rewritten).
    """
    if not settings.openai_api_key or not needs_rewriting(question, chat_history):
        return question, False

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages = _build_rewriter_messages(question, chat_history)

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.0,
            max_tokens=60,
        )

        rewritten = response.choices[0].message.content.strip().strip('"').strip("'")
        if rewritten and len(rewritten) > 3 and rewritten.lower() != question.lower():
            logger.info(f"🔄 Contextual query rewritten: '{question}' -> '{rewritten}'")
            return rewritten, True

        return question, False
    except Exception as e:
        logger.warning(f"Query rewriter error: {e}. Using original question.")
        return question, False


def rewrite_query_sync(question: str, chat_history: Optional[list]) -> tuple[str, bool]:
    """
    Synchronously rewrites a contextual query into a standalone query.
    Returns (effective_question, was_rewritten).
    """
    if not settings.openai_api_key or not needs_rewriting(question, chat_history):
        return question, False

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        messages = _build_rewriter_messages(question, chat_history)

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.0,
            max_tokens=60,
        )

        rewritten = response.choices[0].message.content.strip().strip('"').strip("'")
        if rewritten and len(rewritten) > 3 and rewritten.lower() != question.lower():
            logger.info(f"🔄 Contextual query rewritten: '{question}' -> '{rewritten}'")
            return rewritten, True

        return question, False
    except Exception as e:
        logger.warning(f"Query rewriter sync error: {e}. Using original question.")
        return question, False


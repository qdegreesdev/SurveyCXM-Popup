"""
Comprehensive Edge-Case & Logic Verification Test Suite
Tests every edge case, guardrail, prompt rule, and validation check across SurveyCXM AI.
"""

import os
import sys
import json
import time

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 encoding on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from main import app
from config import settings
from services.rate_limiter import rate_limiter

client = TestClient(app)

results_matrix = []

def record(category: str, case_name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results_matrix.append((category, case_name, status, detail))
    symbol = "[OK]" if passed else "[X]"
    print(f"  {symbol} [{status}] {case_name}" + (f" -> {detail}" if detail else ""))
    assert passed, f"Failed: {case_name} ({detail})"


def test_rag_security_and_auth():
    print("\n--- 1. RAG SECURITY & AUTHENTICATION ---")
    rate_limiter._history.clear()

    # 1.1 Invalid secretKey rejected
    res = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": "bad_key"})
    record("RAG Auth", "Reject invalid secretKey with 401", res.status_code == 401, f"HTTP {res.status_code}")

    # 1.2 Empty secretKey rejected
    res = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": ""})
    record("RAG Auth", "Reject missing/empty secretKey with 401/422", res.status_code in [401, 422], f"HTTP {res.status_code}")

    # 1.3 Valid API secret key accepted
    res = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": settings.api_secret_key})
    record("RAG Auth", "Accept valid API secret key with 200", res.status_code == 200, f"HTTP {res.status_code}")

    # 1.4 Admin secret accepted
    res = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": settings.admin_secret})
    record("RAG Auth", "Accept admin secret key with 200", res.status_code == 200, f"HTTP {res.status_code}")


def test_rag_input_validation():
    print("\n--- 2. RAG INPUT VALIDATION ---")
    rate_limiter._history.clear()

    # 2.1 Empty question string
    res = client.post("/api/doc-rag-search", data={"question": "", "secretKey": settings.api_secret_key})
    record("Validation", "Reject empty question string with 400/422", res.status_code in [400, 422], f"HTTP {res.status_code}")

    # 2.2 Whitespace-only question
    res = client.post("/api/doc-rag-search", data={"question": "     ", "secretKey": settings.api_secret_key})
    record("Validation", "Reject whitespace-only question with 400", res.status_code == 400, res.json().get("detail", ""))

    # 2.3 Overlong question exceeding max_question_length
    overlong = "A" * (settings.max_question_length + 25)
    res = client.post("/api/doc-rag-search", data={"question": overlong, "secretKey": settings.api_secret_key})
    record("Validation", "Reject overlong question (>500 chars) with 400", res.status_code == 400, res.json().get("detail", ""))

    # 2.4 Malformed chat_history JSON (should not crash, fallback gracefully)
    res = client.post("/api/doc-rag-search", data={
        "question": "Hello",
        "secretKey": settings.api_secret_key,
        "chat_history": "{bad_json: True}"
    })
    record("Validation", "Handle malformed chat_history JSON safely with 200", res.status_code == 200, "Safely handled invalid JSON")

    # 2.5 Non-list chat_history JSON
    res = client.post("/api/doc-rag-search", data={
        "question": "Hello",
        "secretKey": settings.api_secret_key,
        "chat_history": json.dumps({"role": "user", "content": "not a list"})
    })
    record("Validation", "Handle non-list chat_history safely with 200", res.status_code == 200, "Safely handled non-list JSON")


def test_rag_endpoint_contract():
    print("\n--- 3. RAG ENDPOINT CONTRACT & RESPONSE SCHEMA ---")
    rate_limiter._history.clear()

    path = "/api/doc-rag-search"
    res = client.post(path, data={"question": "Hello", "secretKey": settings.api_secret_key})
    data = res.json() if res.status_code == 200 else {}
    is_valid = res.status_code == 200 and "answer" in data and "sources" not in data
    record("RAG Contract", f"Endpoint {path} returns HTTP 200 with clean answer payload", is_valid, f"Status: {res.status_code}")


def test_rag_prompt_logic_and_edge_cases():
    print("\n--- 4. RAG PROMPT LOGIC & EDGE CASES ---")
    rate_limiter._history.clear()

    # 4.1 Standalone Greeting
    res_greet = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": settings.api_secret_key})
    answer_greet = res_greet.json().get("answer", "")
    expected_greet = "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>"
    record("Prompt Logic", "Greeting returns exact short welcome message", answer_greet == expected_greet, answer_greet)

    # 4.2 Out-of-Scope Query (Chocolate cake recipe)
    res_scope = client.post("/api/doc-rag-search", data={"question": "Can you give me a recipe for baking chocolate cake?", "secretKey": settings.api_secret_key})
    answer_scope = res_scope.json().get("answer", "")
    expected_scope = "<p>I cannot assist with topics outside of SurveyCXM.</p>"
    record("Prompt Logic", "Out-of-scope query rejected cleanly", expected_scope in answer_scope, answer_scope)

    # 4.3 Out-of-Scope Query (Weather in London)
    res_weather = client.post("/api/doc-rag-search", data={"question": "What is the weather in London right now?", "secretKey": settings.api_secret_key})
    answer_weather = res_weather.json().get("answer", "")
    record("Prompt Logic", "General weather query rejected cleanly", expected_scope in answer_weather, answer_weather)

    # 4.4 SurveyCXM query lacking documentation in knowledge base
    res_missing = client.post("/api/doc-rag-search", data={"question": "How do I configure SurveyCXM with SAP Ariba directly?", "secretKey": settings.api_secret_key})
    answer_missing = res_missing.json().get("answer", "")
    expected_missing = "<p>No documentation found for this feature. Please contact your administrator.</p>"
    record("Prompt Logic", "SurveyCXM query lacking docs returns short fallback", expected_missing in answer_missing, answer_missing)

    # 4.5 Valid SurveyCXM query with matching documentation
    res_valid = client.post("/api/doc-rag-search", data={"question": "How do I create a survey from scratch in SurveyCXM?", "secretKey": settings.api_secret_key})
    data_valid = res_valid.json()
    answer_valid = data_valid.get("answer", "")
    has_html_structure = "<ol>" in answer_valid or "<ul>" in answer_valid or "<p>" in answer_valid
    is_valid_answer = has_html_structure and len(answer_valid) > 50
    record("Prompt Logic", "Valid how-to question returns structured HTML steps", is_valid_answer, f"Length: {len(answer_valid)}")


def test_rag_rate_limiting():
    print("\n--- 5. RAG SLIDING-WINDOW RATE LIMITING ---")
    rate_limiter._history.clear()

    limit = settings.rate_limit_doc_rag_search
    # Exhaust allowed requests
    for i in range(limit):
        client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": settings.api_secret_key})

    # The (limit + 1)-th call must return 429
    res_exceeded = client.post("/api/doc-rag-search", data={"question": "Hello", "secretKey": settings.api_secret_key})
    record("Rate Limiting", f"Trigger HTTP 429 when exceeding limit of {limit} reqs/min", res_exceeded.status_code == 429, f"HTTP {res_exceeded.status_code}")
    rate_limiter._history.clear()


def test_admin_documentation_sync():
    print("\n--- 6. ADMIN SYNC DOCUMENTATION ---")

    # 6.1 Unauthorized sync call
    res_unauth = client.post("/api/sync-documentation", headers={"x-admin-secret": "wrong"})
    record("Admin Sync", "Reject /api/sync-documentation with 401 on invalid admin secret", res_unauth.status_code == 401, f"HTTP {res_unauth.status_code}")

    # 6.2 Authorized sync call
    res_auth = client.post("/api/sync-documentation", headers={"x-admin-secret": settings.admin_secret})
    record("Admin Sync", "Accept /api/sync-documentation with 200 on valid admin secret", res_auth.status_code == 200, f"Status: {res_auth.status_code}")


def test_ask_ai_edge_cases():
    print("\n--- 7. ASK-AI CX METRICS EDGE CASES ---")
    rate_limiter._history.clear()

    # 7.1 Invalid client ID <= 0
    res = client.post("/api/ask-ai", data={
        "client_id": 0,
        "user_last_login_date": "01/10/2026",
        "user_current_login_date": "10/10/2026",
        "question": "What is our NPS?",
        "secretKey": settings.api_secret_key
    })
    record("Ask AI", "Reject client_id <= 0 with 400", res.status_code == 400, res.json().get("detail", ""))

    # 7.2 Inverted dates (last_login in the future)
    res = client.post("/api/ask-ai", data={
        "client_id": 1,
        "user_last_login_date": "20/10/2026",
        "user_current_login_date": "10/10/2026",
        "question": "What is our NPS?",
        "secretKey": settings.api_secret_key
    })
    record("Ask AI", "Reject last_login in the future with 400", res.status_code == 400, res.json().get("detail", ""))

    # 7.3 Invalid secret key
    res = client.post("/api/ask-ai", data={
        "client_id": 1,
        "user_last_login_date": "01/10/2026",
        "user_current_login_date": "10/10/2026",
        "question": "What is our NPS?",
        "secretKey": "bad_key"
    })
    record("Ask AI", "Reject invalid secretKey with 401", res.status_code == 401, f"HTTP {res.status_code}")


def test_health_endpoint():
    print("\n--- 8. HEALTH ENDPOINT (DATABASE & RAG) ---")
    res = client.get("/api/health")
    data = res.json() if res.status_code == 200 else {}
    has_db = "database" in data
    has_rag = "rag" in data and "status" in data.get("rag", {}) and "total_chunks" in data.get("rag", {})
    record("Health API", "Health returns HTTP 200 with database and RAG status", res.status_code == 200 and has_db and has_rag, f"RAG Status: {data.get('rag', {}).get('status')}, Chunks: {data.get('rag', {}).get('total_chunks')}")


def run_all():
    print("=" * 75)
    print("      SURVEYCXM COMPLETE EDGE-CASE & UNIT TEST RUNNER")
    print("=" * 75)

    test_rag_security_and_auth()
    test_rag_input_validation()
    test_rag_endpoint_contract()
    test_rag_prompt_logic_and_edge_cases()
    test_rag_rate_limiting()
    test_admin_documentation_sync()
    test_ask_ai_edge_cases()
    test_health_endpoint()

    print("\n" + "=" * 75)
    print("                      TEST RESULTS SUMMARY")
    print("=" * 75)
    passed_count = sum(1 for _, _, status, _ in results_matrix if status == "PASS")
    total_count = len(results_matrix)

    print(f"\nTOTAL TESTS EXECUTED : {total_count}")
    print(f"PASSED               : {passed_count}")
    print(f"FAILED               : {total_count - passed_count}")

    if passed_count == total_count:
        print("\n🎉 ALL LOGIC AND EDGE-CASE UNIT TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 75)


if __name__ == "__main__":
    run_all()

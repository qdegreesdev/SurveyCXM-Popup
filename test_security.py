import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app
from config import settings
from services.rate_limiter import rate_limiter

client = TestClient(app)

def test_security_headers():
    print("Testing security headers...")
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    print("  -> PASSED")

def test_audio_path_traversal_prevention():
    print("Testing path traversal prevention on /audio/{filename}...")
    response = client.get("/api/audio/../.env")
    assert response.status_code in [400, 404]

    response = client.get("/api/audio/%2e%2e%2f.env")
    assert response.status_code in [400, 404]

    response = client.get("/api/audio/test.txt")
    assert response.status_code == 400
    print("  -> PASSED")

def test_ask_ai_unauthorized():
    print("Testing /ask-ai invalid secret key rejection...")
    response = client.post("/api/ask-ai", data={
        "client_id": 1,
        "user_last_login_date": "2026-08-01",
        "user_current_login_date": "2026-08-24",
        "question": "What is the NPS?",
        "secretKey": "wrong_secret"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"
    print("  -> PASSED")

def test_ask_ai_invalid_client_id():
    print("Testing /ask-ai invalid client_id validation...")
    response = client.post("/api/ask-ai", data={
        "client_id": -5,
        "user_last_login_date": "2026-08-01",
        "user_current_login_date": "2026-08-24",
        "question": "What is the NPS?",
        "secretKey": settings.api_secret_key
    })
    assert response.status_code == 400
    assert "Invalid client ID" in response.json()["detail"]
    print("  -> PASSED")

def test_ask_ai_overlong_question():
    print("Testing /ask-ai overlong question rejection...")
    long_question = "A" * (settings.max_question_length + 10)
    response = client.post("/api/ask-ai", data={
        "client_id": 1,
        "user_last_login_date": "2026-08-01",
        "user_current_login_date": "2026-08-24",
        "question": long_question,
        "secretKey": settings.api_secret_key
    })
    assert response.status_code == 400
    assert "exceeds maximum length" in response.json()["detail"]
    print("  -> PASSED")

def test_login_popup_summary_unauthorized():
    print("Testing /login-popup-summary invalid secret key rejection...")
    response = client.post("/api/login-popup-summary", data={
        "client_id": 1,
        "user_last_login_date": "2026-08-01",
        "user_current_login_date": "2026-08-24",
        "secretKey": "invalid_key"
    })
    assert response.status_code == 401
    print("  -> PASSED")

def test_survey_review_suggestion_unauthorized():
    print("Testing /survey_review_suggestion invalid secret key rejection...")
    response = client.post("/api/survey_review_suggestion", data={
        "secretKey": "invalid_key",
        "survey_summary": '[{"sequence": 1, "question": "Q1", "answer": "A1"}]'
    })
    assert response.status_code == 401
    print("  -> PASSED")

def test_survey_review_suggestion_invalid_payload():
    print("Testing /survey_review_suggestion invalid payload validation...")
    response = client.post("/api/survey_review_suggestion", data={
        "secretKey": settings.api_secret_key,
        "survey_summary": '{"not": "a list"}'
    })
    assert response.status_code == 400
    assert "must be a JSON list" in response.json()["detail"]

    response = client.post("/api/survey_review_suggestion", data={
        "secretKey": settings.api_secret_key,
        "survey_summary": '[]'
    })
    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"]
    print("  -> PASSED")

def test_admin_logs_unauthorized():
    print("Testing /logs unauthorized rejection...")
    response = client.get("/api/logs")
    assert response.status_code == 401

    response = client.get("/api/logs", headers={"x-admin-secret": "wrong_admin_secret"})
    assert response.status_code == 401
    print("  -> PASSED")

def test_admin_logs_authorized():
    print("Testing /logs authorized access...")
    response = client.get("/api/logs?lines=5", headers={"x-admin-secret": settings.admin_secret})
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    print("  -> PASSED")

def test_admin_clear_logs():
    print("Testing /clear-logs authorized execution...")
    # Unauthorized check
    res_unauth = client.post("/api/clear-logs")
    assert res_unauth.status_code == 401

    # Authorized clear
    res_auth = client.post("/api/clear-logs", headers={"x-admin-secret": settings.admin_secret})
    assert res_auth.status_code == 200
    assert res_auth.json().get("status") == "success"
    print("  -> PASSED")

def test_admin_clear_pycache():
    print("Testing /clear-pycache authorized execution...")
    res_unauth = client.post("/api/clear-pycache")
    assert res_unauth.status_code == 401

    res_auth = client.post("/api/clear-pycache", headers={"x-admin-secret": settings.admin_secret})
    assert res_auth.status_code == 200
    assert res_auth.json().get("status") == "success"
    print("  -> PASSED")

def test_admin_clear_cache():
    print("Testing /clear-cache authorized execution...")
    res_unauth = client.post("/api/clear-cache")
    assert res_unauth.status_code == 401

    res_auth = client.post("/api/clear-cache", headers={"x-admin-secret": settings.admin_secret})
    assert res_auth.status_code == 200
    assert res_auth.json().get("status") == "success"
    print("  -> PASSED")

def test_protected_docs():
    print("Testing /docs basic auth protection...")
    # Without credentials -> 401 Unauthorized
    response = client.get("/docs")
    assert response.status_code == 401

    # With valid basic auth -> 200 OK
    response = client.get("/docs", auth=("admin", settings.admin_secret))
    assert response.status_code == 200
    print("  -> PASSED")

def test_rate_limiting():
    print("Testing API rate limiting (429 Too Many Requests)...")
    from services.rate_limiter import rate_limiter
    rate_limiter._history.clear()
    orig = settings.use_mock_data
    settings.use_mock_data = True
    try:
        # Exceed rate limit for ask_ai (limit: 15)
        for _ in range(settings.rate_limit_ask_ai):
            res = client.post("/api/ask-ai", data={
                "client_id": 1,
                "user_last_login_date": "2026-08-01",
                "user_current_login_date": "2026-08-24",
                "question": "NPS?",
                "secretKey": settings.api_secret_key
            })

        # The (limit + 1)-th call should return 429 Too Many Requests
        exceeded_res = client.post("/api/ask-ai", data={
            "client_id": 1,
            "user_last_login_date": "2026-08-01",
            "user_current_login_date": "2026-08-24",
            "question": "NPS?",
            "secretKey": settings.api_secret_key
        })
        assert exceeded_res.status_code == 429
        assert "Rate limit exceeded" in exceeded_res.json()["detail"]
    finally:
        settings.use_mock_data = orig
        rate_limiter._history.clear()
    print("  -> PASSED")

def test_doc_rag_search_rate_limiting():
    print("Testing /doc-rag-search rate limiting...")
    rate_limiter._history.clear()

    # Exhaust the rate limit
    for _ in range(settings.rate_limit_doc_rag_search):
        client.post("/api/doc-rag-search", data={
            "question": "Hello",
            "secretKey": settings.api_secret_key
        })

    # The (limit + 1)-th call should return 429 Too Many Requests
    exceeded_res = client.post("/api/doc-rag-search", data={
        "question": "Hello",
        "secretKey": settings.api_secret_key
    })
    assert exceeded_res.status_code == 429
    assert "Rate limit exceeded" in exceeded_res.json()["detail"]
    rate_limiter._history.clear()
    print("  -> PASSED")

def test_doc_rag_search_unauthorized():
    print("Testing /doc-rag-search unauthorized rejection...")
    res = client.post("/api/doc-rag-search", data={
        "question": "How do I create a survey?",
        "secretKey": "wrong_secret"
    })
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"
    print("  -> PASSED")

def test_doc_rag_search_empty_question():
    print("Testing /doc-rag-search empty question validation...")
    res = client.post("/api/doc-rag-search", data={
        "question": "   ",
        "secretKey": settings.api_secret_key
    })
    assert res.status_code == 400
    assert "Question cannot be empty" in res.json()["detail"]
    print("  -> PASSED")

def test_doc_rag_search_overlong_question():
    print("Testing /doc-rag-search overlong question validation...")
    long_q = "X" * (settings.max_question_length + 20)
    res = client.post("/api/doc-rag-search", data={
        "question": long_q,
        "secretKey": settings.api_secret_key
    })
    assert res.status_code == 400
    assert "exceeds maximum length" in res.json()["detail"]
    print("  -> PASSED")

def test_doc_rag_search_success():
    print("Testing /doc-rag-search valid response...")
    res = client.post("/api/doc-rag-search", data={
        "question": "Hello",
        "secretKey": settings.api_secret_key
    })
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    print("  -> PASSED")

def run_all_tests():
    print("\n--- RUNNING SECURITY VERIFICATION TESTS ---\n")
    test_security_headers()
    test_audio_path_traversal_prevention()
    test_ask_ai_unauthorized()
    test_ask_ai_invalid_client_id()
    test_ask_ai_overlong_question()
    test_login_popup_summary_unauthorized()
    test_survey_review_suggestion_unauthorized()
    test_survey_review_suggestion_invalid_payload()
    test_admin_logs_unauthorized()
    test_admin_logs_authorized()
    test_admin_clear_logs()
    test_admin_clear_pycache()
    test_admin_clear_cache()
    test_protected_docs()
    test_rate_limiting()
    test_doc_rag_search_rate_limiting()
    test_doc_rag_search_unauthorized()
    test_doc_rag_search_empty_question()
    test_doc_rag_search_overlong_question()
    test_doc_rag_search_success()
    print("\n[SUCCESS] ALL SECURITY TESTS PASSED SUCCESSFULLY!\n")

if __name__ == "__main__":
    run_all_tests()

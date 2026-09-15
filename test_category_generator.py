from fastapi.testclient import TestClient
from main import app
from config import settings

client = TestClient(app)

def test_generate_categories_success():
    payload = {
        "client_id": 1,
        "survey_id": 10,
        "industry_name": "Healthcare & Medical",
        "secretKey": settings.api_secret_key
    }
    response = client.post("/api/generate-categories", data=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["client_id"] == 1
    assert data["survey_id"] == 10
    assert data["industry_name"] == "Healthcare & Medical"
    assert len(data["categories"]) == 5

def test_generate_categories_custom_counts():
    payload = {
        "client_id": 1,
        "survey_id": 10,
        "industry_name": "Retail & Supermarkets",
        "secretKey": settings.api_secret_key,
        "category_creation_count": 4,
        "subcategory_creation_count": 2
    }
    response = client.post("/api/generate-categories", data=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["category_creation_count"] == 4
    assert data["subcategory_creation_count"] == 2
    assert len(data["categories"]) == 4
    for cat in data["categories"]:
        assert len(cat["sub_categories"]) == 2

def test_generate_categories_invalid_secret_key():
    payload = {
        "client_id": 1,
        "survey_id": 10,
        "industry_name": "Healthcare",
        "secretKey": "wrong_secret"
    }
    response = client.post("/api/generate-categories", data=payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid secret key"

def test_generate_categories_invalid_client_id():
    payload = {
        "client_id": -5,
        "survey_id": 10,
        "industry_name": "Healthcare",
        "secretKey": settings.api_secret_key
    }
    response = client.post("/api/generate-categories", data=payload)
    assert response.status_code == 400
    assert "client_id must be a valid positive integer" in response.json()["detail"]

def test_generate_categories_invalid_industry_name():
    payload = {
        "client_id": 1,
        "survey_id": 10,
        "industry_name": "a", # Less than 2 chars
        "secretKey": settings.api_secret_key
    }
    response = client.post("/api/generate-categories", data=payload)
    assert response.status_code == 400
    assert "Invalid industry_name" in response.json()["detail"]

if __name__ == "__main__":
    test_generate_categories_success()
    test_generate_categories_custom_counts()
    test_generate_categories_invalid_secret_key()
    test_generate_categories_invalid_client_id()
    test_generate_categories_invalid_industry_name()
    print("All tests passed!")

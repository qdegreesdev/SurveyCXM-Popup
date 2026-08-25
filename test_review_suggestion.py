import os
import sys
import json
from fastapi.testclient import TestClient

# Add current dir to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app

client = TestClient(app)

def run_test():
    print("Testing /api/survey_review_suggestion...")
    
    # Test 1: Basic survey without explicit NPS score
    survey_data = [
        {
            "sequence": 1,
            "question": "How satisfied are you with our service?",
            "answer": "Very satisfied, the team was helpful."
        },
        {
            "sequence": 2,
            "question": "What could we improve?",
            "answer": "The response time could be a bit faster on weekends."
        }
    ]
    
    form_data = {
        "secretKey": "my_secret_123",
        "survey_summary": json.dumps(survey_data)
    }
    
    response = client.post("/api/survey_review_suggestion", data=form_data)
    print(f"Status: {response.status_code}")
    res_json = response.json()
    assert response.status_code == 200
    assert len(res_json["suggestions"]) == 3
    print("Default Test (3 suggestions returned): PASSED")

    # Test 2: Promoter NPS (Score: 10)
    form_data_promoter = {
        "secretKey": "my_secret_123",
        "survey_summary": json.dumps(survey_data),
        "nps_score": 10
    }
    res_promoter = client.post("/api/survey_review_suggestion", data=form_data_promoter)
    assert res_promoter.status_code == 200
    assert len(res_promoter.json()["suggestions"]) == 3
    print("Promoter NPS Test (Score 10): PASSED")
    print(f"  -> Suggestions: {res_promoter.json()['suggestions']}")

    # Test 3: Passive NPS (Score: 7)
    form_data_passive = {
        "secretKey": "my_secret_123",
        "survey_summary": json.dumps(survey_data),
        "nps_score": 7
    }
    res_passive = client.post("/api/survey_review_suggestion", data=form_data_passive)
    assert res_passive.status_code == 200
    assert len(res_passive.json()["suggestions"]) == 3
    print("Passive NPS Test (Score 7): PASSED")
    print(f"  -> Suggestions: {res_passive.json()['suggestions']}")

    # Test 4: Detractor NPS (Score: 3)
    form_data_detractor = {
        "secretKey": "my_secret_123",
        "survey_summary": json.dumps(survey_data),
        "nps_score": 3
    }
    res_detractor = client.post("/api/survey_review_suggestion", data=form_data_detractor)
    assert res_detractor.status_code == 200
    assert len(res_detractor.json()["suggestions"]) == 3
    print("Detractor NPS Test (Score 3): PASSED")
    print(f"  -> Suggestions: {res_detractor.json()['suggestions']}")

    # Test 5: Embedded NPS question in survey_summary
    survey_data_with_nps = [
        {
            "sequence": 1,
            "question": "On a scale of 0-10, how likely are you to recommend us? (NPS)",
            "answer": "9"
        },
        {
            "sequence": 2,
            "question": "Feedback",
            "answer": "Outstanding customer support."
        }
    ]
    res_embedded = client.post("/api/survey_review_suggestion", data={
        "secretKey": "my_secret_123",
        "survey_summary": json.dumps(survey_data_with_nps)
    })
    assert res_embedded.status_code == 200
    assert len(res_embedded.json()["suggestions"]) == 3
    print("Embedded NPS Question Test (Score 9): PASSED")
    print(f"  -> Suggestions: {res_embedded.json()['suggestions']}")

if __name__ == "__main__":
    run_test()

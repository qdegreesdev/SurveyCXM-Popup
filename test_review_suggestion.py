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
    print("--- ACTUAL RAW API RESPONSE ---")
    print(response.text)
    print("-------------------------------")

if __name__ == "__main__":
    run_test()

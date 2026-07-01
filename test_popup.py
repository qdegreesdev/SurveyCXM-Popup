from fastapi.testclient import TestClient
import sys
from main import app

client = TestClient(app)

print("--- Testing /api/login-popup-summary ---")
response = client.post(
    "/api/login-popup-summary",
    data={
        "client_id": 1,
        "user_last_login_date": "28/05/2026",
        "user_current_login_date": "04/06/2026",
        "secretKey": "my_secret_123"
    }
)

if response.status_code == 200:
    data = response.json()
    print("SUCCESS! Output saved to test_output.json")
    import json
    with open("test_output.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
else:
    print(f"FAILED with status {response.status_code}")
    print(response.text)

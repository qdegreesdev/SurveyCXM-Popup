import os
import sys
from fastapi.testclient import TestClient

# Add current dir to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app

client = TestClient(app)

import time

def run_tests():
    print("Testing /api/health...")
    response = client.get("/api/health")
    print(f"Health Status: {response.status_code}")
    print(f"Health Response: {response.json()}\n")
    
    print("\n--- Testing Invalid API Key ---")
    form_data_invalid = {
        "client_id": "13",
        "user_last_login_date": "2023-10-01",
        "user_current_login_date": "2023-10-10",
        "secretKey": "wrong_secret"
    }
    response_invalid = client.post("/api/login-popup-summary", data=form_data_invalid)
    print(f"Invalid API Key Status: {response_invalid.status_code}")
    if response_invalid.status_code == 401:
        print("  [SUCCESS] API correctly rejected invalid secretKey (401).")
    else:
        print(f"  [FAILED] Expected 401, got {response_invalid.status_code}. Response: {response_invalid.text}")
    print("-----------------------------------------\n")

    print("Testing /api/login-popup-summary...")
    form_data = {
        "client_id": "13",
        "user_last_login_date": "2023-10-01",
        "user_current_login_date": "2023-10-10",
        "secretKey": "my_secret_123"
    }
    start_time = time.time()
    response = client.post("/api/login-popup-summary", data=form_data)
    end_time = time.time()
    latency_ms = (end_time - start_time) * 1000
    print(f"Popup Summary Status: {response.status_code}")
    print(f"Latency: {latency_ms:.2f} ms")
    
    if response.status_code == 200:
        data = response.json()
        print("Success! JSON Response snippet:")
        print(f"  greeting: {data.get('greeting')}")
        print(f"  ai_summary_audio_url: {data.get('ai_summary_audio_url')}")
        print(f"  voc_audio_url: {data.get('voc_audio_url')}")
        print(f"  is_data_found: {data.get('is_data_found')}")
        
        # Verify base_url logic from .env is working
        audio_url = data.get('ai_summary_audio_url')
        if audio_url and "cxm-ai-popup.qdegrees.com" in audio_url:
            print("  [SUCCESS] BASE_URL override from .env is working correctly!")
        else:
            print(f"  [WARNING] BASE_URL override failed. URL is: {audio_url}")

        if audio_url:
            filename = audio_url.split('/')[-1]
            print(f"\nFetching audio file: {filename}")
            audio_response = client.get(f"/api/audio/{filename}")
            print(f"Audio Fetch Status: {audio_response.status_code}")
            if audio_response.status_code == 200:
                print(f"  [SUCCESS] Audio Fetch Success! File length: {len(audio_response.content)} bytes")
            else:
                print(f"  [FAILED] Audio Fetch Failed! {audio_response.text}")
    else:
        print(f"  [FAILED] Failed! Error: {response.text}")

    print("\n-----------------------------------------")
    print("Testing /api/ask-ai with Invalid API Key...")
    form_data_ask_invalid = {
        "client_id": "13",
        "user_last_login_date": "2023-10-01",
        "user_current_login_date": "2023-10-10",
        "question": "What is the top issue?",
        "secretKey": "wrong_secret"
    }
    response_ask_invalid = client.post("/api/ask-ai", data=form_data_ask_invalid)
    print(f"Invalid API Key Status: {response_ask_invalid.status_code}")
    if response_ask_invalid.status_code == 401:
        print("  [SUCCESS] Ask-AI correctly rejected invalid secretKey (401).")
    else:
        print(f"  [FAILED] Expected 401, got {response_ask_invalid.status_code}. Response: {response_ask_invalid.text}")
    print("-----------------------------------------\n")

    print("Testing /api/ask-ai...")
    form_data_ask = {
        "client_id": "13",
        "user_last_login_date": "2023-10-01",
        "user_current_login_date": "2023-10-10",
        "question": "What is the top issue?",
        "secretKey": "my_secret_123"
    }
    start_time_ask = time.time()
    response_ask = client.post("/api/ask-ai", data=form_data_ask)
    end_time_ask = time.time()
    latency_ask_ms = (end_time_ask - start_time_ask) * 1000
    print(f"Ask-AI Status: {response_ask.status_code}")
    print(f"Latency: {latency_ask_ms:.2f} ms")
    if response_ask.status_code == 200:
        print("  [SUCCESS] Ask-AI Success!")
        print(f"  Answer Snippet: {response_ask.json().get('answer')[:100]}...")
    else:
        print(f"  [FAILED] Ask-AI Failed! Error: {response_ask.text}")

if __name__ == "__main__":
    run_tests()

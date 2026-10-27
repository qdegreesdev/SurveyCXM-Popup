# SurveyCXM Backend Deployment Guide

Follow these steps to deploy the SurveyCXM FastAPI backend.

---

## 1. Project Setup

Navigate to your deployment directory and create a virtual environment:
```bash
cd /path/to/SurveyCXM_AI_Popup
python3 -m venv venv
source venv/bin/activate
```

Install the required dependencies:
```bash
pip install -r requirements.txt
```

---

## 2. Environment Configuration

Ensure a `.env` file is present in the project root with the appropriate credentials:
```env
# OpenAI
OPENAI_API_KEY=sk-proj-your-openai-key
OPENAI_MODEL=gpt-4o-mini

# MySQL Database
SURVEY_DB_HOST=188.241.187.49
SURVEY_DB_PORT=3306
SURVEY_DB_NAME=surveycx_demo
SURVEY_DB_USER=your_db_user
SURVEY_DB_PASSWORD=your_db_password

# Security & Secrets
API_SECRET_KEY=your_api_secret_key
ADMIN_SECRET=your_admin_secret
```

---

## 3. Run the Application

Start the server using `uvicorn`. For a live deployment, use the `--workers` flag to handle multiple requests concurrently:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

*(Note: To keep it running in the background, you can run this command inside a `tmux` session, systemd service, or use `nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 > app.log 2>&1 &`)*

---

## 4. Verification & Sync

1. **Verify Health:**
   ```bash
   curl http://localhost:8000/api/health
   ```

2. **Sync Documentation Vector Index:**
   ```bash
   curl -X POST http://localhost:8000/api/sync-documentation \
     -H "x-admin-secret: your_admin_secret" \
     -d "force=true"
   ```

---

## 5. View Logs

The application logs are saved locally and rotated automatically:
```bash
tail -f app.log
```

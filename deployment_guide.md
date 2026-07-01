# SurveyCXM Backend Deployment Guide

Follow these steps to deploy the SurveyCXM FastAPI backend.

## 1. Project Setup

Navigate to your deployment directory and create a virtual environment:
```bash
cd /path/to/surveycxm-backend
python3 -m venv venv
source venv/bin/activate
```

Install the required dependencies:
```bash
pip install -r requirements.txt
```

## 2. Run the Application

Start the server using `uvicorn`. For a live deployment, use the `--workers` flag to handle multiple requests at once:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

*(Note: To keep it running in the background, you can run this command inside a `tmux` session, or use `nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 &`)*

## 3. View Logs

The application logs are saved locally:
```bash
tail -f app.log
```

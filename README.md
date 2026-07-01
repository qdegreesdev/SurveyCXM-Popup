# 📡 SurveyCXM — Login Intelligence Popup

A full-stack AI-powered login popup system that greets users with a **personalized summary**, shows **live NPS analytics** from their database, and lets them **ask AI any question** about their CX data — all scoped to the window between their last login and their current login.

---

## 📁 Project Structure

```
New_popup/
├── backend/                  # FastAPI Python backend
│   ├── main.py               # App entrypoint, CORS, startup hooks
│   ├── config.py             # Settings from .env (DB, OpenAI, flags)
│   ├── database.py           # MySQL connection + all query methods
│   ├── requirements.txt      # Python dependencies
│   ├── .env                  # Environment variables (secrets)
│   ├── routes/
│   │   └── popup.py          # All API endpoints
│   └── services/
│       ├── ai_service.py     # OpenAI summary + Ask AI logic
│       ├── mock_data.py      # Fallback data when DB is unavailable
│       ├── nps_service.py    # NPS calculation helpers
│       ├── demographic_service.py  # Region/State/City breakdown
│       └── freetext_service.py     # Voice-of-customer text parsing
│
├── frontend/                 # React + Vite frontend
│   └── src/
│       ├── App.jsx           # Main app with config form
│       └── components/
│           ├── PopupModal.jsx        # Main modal container with tabs
│           ├── AISummaryCard.jsx     # AI summary + Ask AI feature
│           ├── NPSScoreCard.jsx      # NPS score display
│           ├── DemographicBreakdown.jsx  # Region/State/City NPS
│           ├── CriticalIssues.jsx    # Voice of Customer alerts
│           ├── SurveyComparison.jsx  # Survey-level NPS comparison
│           └── LoadingSkeleton.jsx   # Loading state UI
│
└── test_api.py               # API test runner script
```

---

## ⚙️ Environment Setup

### 1. Backend — Python Virtual Environment

Navigate to the backend folder and set up a virtual environment:

```powershell
cd backend

# Create virtual environment
python -m venv venv

# Activate it (Windows PowerShell)
.\venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

### 2. Configure `.env` File

Edit `backend/.env` with your credentials:

```env
# OpenAI (required for AI Summary and Ask AI)
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_MODEL=gpt-3.5-turbo

# MySQL Database
SURVEY_DB_HOST=your-db-host
SURVEY_DB_PORT=3306
SURVEY_DB_NAME=surveycx_demo
SURVEY_DB_USER=your-db-user
SURVEY_DB_PASSWORD=your-db-password

# Set to true to force mock/demo data (useful for testing without DB)
USE_MOCK_DATA=false
```

### 3. Start the Backend Server

```powershell
# Make sure virtual environment is active first
.\venv\Scripts\activate

# Start the server (auto-reloads on code changes)
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server will:
- Start on `http://127.0.0.1:8000`
- **Automatically open** your browser to `http://127.0.0.1:8000/docs` (Swagger UI)
- Pre-warm the database connection on startup
- Log `✅ Database pre-warmed` or `⚠️ Running without DB — mock data mode active`

### 4. Start the Frontend

Open a **second terminal** and run:

```powershell
cd frontend
npm install       # first time only
npm run dev
```

Frontend runs at `http://localhost:5173`

---

## 🌐 API Endpoints

**Base URL:** `http://localhost:8000`  
**Interactive Docs:** `http://localhost:8000/docs`

---


### `POST /api/login-popup-summary`

**The dedicated popup greeting endpoint.** Accepts Form Data and returns a personalized greeting with a pre-formatted HTML AI summary.

**Content-Type:** `application/x-www-form-urlencoded`

**Form Data Parameters:**

| Parameter | Type | Format | Required |
|-----------|------|--------|----------|
| `client_id` | integer | — | ✅ |
| `user_last_login_date` | string | `DD/MM/YYYY` | ✅ |
| `user_current_login_date` | string | `DD/MM/YYYY` | ✅ |
| `secretKey` | string | — | ✅ |

**Example Request (JavaScript Fetch):**
```javascript
const formData = new URLSearchParams();
formData.append('client_id', '1');
formData.append('user_last_login_date', '01/06/2026');
formData.append('user_current_login_date', '03/06/2026');
formData.append('secretKey', 'my_secret_123');

const res = await fetch('http://localhost:8000/api/login-popup-summary', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: formData.toString()
});
const data = await res.json();
```

**Response:**
```json
{
  "greeting": "Good afternoon Sunil",
  "ai_summary": "<p>Since your last login on <strong>Jun 01, 2026 12:00 AM</strong>, your overall NPS has declined by <strong>100.0 pts</strong>, now at <strong>-100.0</strong>. <strong>West</strong> (Zone) is your strongest area...</p>"
}
```

> **Notes:**
> - `greeting` uses **real-time server clock** — not the dates you pass in. You will get "Good morning / afternoon / evening" based on the actual time of the API call.
> - `ai_summary` returns pre-formatted HTML with `<p>` and `<strong>` tags for direct frontend rendering.
> - User name is fetched dynamically from the `users` table using `client_id`.

---

### `POST /api/ask-ai`

**The AI question-answering endpoint.** Accepts a free-text question and answers it using the user's live CX data as context.

**Content-Type:** `application/x-www-form-urlencoded`

**Form Data Parameters:**

| Parameter | Type | Format | Required |
|-----------|------|--------|----------|
| `client_id` | integer | — | ✅ |
| `user_last_login_date` | string | `DD/MM/YYYY` | ✅ |
| `user_current_login_date` | string | `DD/MM/YYYY` | ✅ |
| `question` | string | Free text | ✅ |
| `secretKey` | string | — | ✅ |

**Example Request (cURL):**
```bash
curl -X POST http://localhost:8000/api/ask-ai \
  -d "client_id=1&user_last_login_date=01/06/2026&user_current_login_date=03/06/2026&question=What is the biggest problem?&secretKey=my_secret_123"
```

**Example Request (PowerShell):**
```powershell
$body = "client_id=1&user_last_login_date=01/06/2026&user_current_login_date=03/06/2026&question=What+is+the+biggest+problem?&secretKey=my_secret_123"
Invoke-RestMethod -Uri "http://localhost:8000/api/ask-ai" -Method Post -Body $body -ContentType "application/x-www-form-urlencoded"
```

**Response:**
```json
{
  "answer": "The top customer concern is Foreclosure Issues (Count: 3, High Severity). Here are recommended actions:\n1. Investigate root causes...\n2. Enhance communication..."
}
```

> **The AI can answer any question**, including:
> - Data-specific questions ("Which region declined the most?")
> - Action-oriented questions ("What should I do about churn?")
> - Comparative questions ("How does our NPS compare to industry standards?")
> - Custom drill-down questions ("Break down NPS by city")

---

### `GET /api/health`

Health check — verifies the database connection is alive.

```
GET http://localhost:8000/api/health
```

**Response:**
```json
{ "connected": true, "db": "surveycx_demo", "host": "188.241.187.49" }
```

---

## 🧠 System Logic & Architecture

### How the Date Window Works

Every API call is scoped to a **date window** between `last_login_date` and `current_login_date`. The system:

1. Queries the database for survey responses **only in this window** (current period)
2. Also queries the **equal-length window before** last login (previous period)
3. Calculates **delta / change** between the two periods for NPS, demographics, and issues

This is why the AI can say *"Since your last login, NPS improved by 6.3 points"* — it always compares apples to apples.

---

### How Surveys Are Resolved

Each `client_id` maps to one or more surveys in the database. The system:

1. Queries the `survey_client_mappings` (or equivalent) table to get all `survey_ids` for the client
2. For each survey, reads data from `survey_responses_{id}` table
3. **Aggregates** results across all surveys for a unified view
4. Gracefully **skips missing tables** — if `survey_responses_9` doesn't exist, it logs a warning and continues

---

### How the AI Summary Works

The `generate_ai_summary` function:

1. Builds a structured context string with NPS data, top gainers/decliners, survey changes, and critical issues
2. Sends to **OpenAI GPT** with a strict instruction to start with: *"Since your last login on [Date]..."*
3. Returns both a `summary` paragraph and `key_points` bullet list
4. For `/login-popup-summary`, the `html_format=True` flag wraps key metrics in `<strong>` tags

**Fallback:** If OpenAI is unavailable or the API key is invalid, a **rule-based fallback** summary is generated directly from the data without any AI call.

---

### How Ask AI Works

The `answer_user_question` function:

1. Builds a rich context string containing:
   - Full NPS overview (current, previous, delta, promoter/passive/detractor %)
   - All demographics (Region, State, City) with previous NPS and trends
   - Top improving and declining areas (pre-sorted)
   - Critical issues with verbatim customer quotes and churn signal counts
2. Sends the context as a **system prompt** and the user's question as a **user message** to OpenAI
3. The AI acts as a "CX data analyst" — it gives drill-down answers with bullet points and specific numbers
4. `max_tokens=500` ensures full, uncut answers even for complex questions

---

### Resilience & Fallback

The system is designed to **never crash the frontend**:

| Scenario | Behaviour |
|----------|-----------|
| DB not connected | Falls back to mock/demo data automatically |
| Missing survey table | Logs warning, skips that survey, continues with others |
| OpenAI key missing | Returns rule-based summary from data |
| OpenAI API error | Returns graceful error message |
| `USE_MOCK_DATA=true` in `.env` | Forces demo data regardless of DB state |

---

## 🧪 Running Tests

A test script is included at the project root:

```powershell
# Activate virtual environment first
cd backend
.\venv\Scripts\activate
cd ..

# Run all API tests
python test_api.py
```

**Tests covered:**
1. `GET /api/popup-data` — popup data dynamic check
2. `POST /api/login-popup-summary` — greeting + HTML summary
3. `POST /api/ask-ai` — free-text question answering

---

## 🖥️ Frontend Integration Guide

### Using the Popup Summary API

```javascript
async function fetchPopupSummary(clientId, lastLoginDate, currentLoginDate) {
  const formData = new URLSearchParams({
    client_id: clientId,
    user_last_login_date: lastLoginDate,     // format: "DD/MM/YYYY"
    user_current_login_date: currentLoginDate // format: "DD/MM/YYYY"
  });

  const res = await fetch('http://localhost:8000/api/login-popup-summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData.toString()
  });

  const { greeting, ai_summary } = await res.json();

  // Render greeting as plain text
  document.getElementById('greeting').textContent = greeting;

  // Render AI summary as HTML (it contains <p> and <strong> tags)
  document.getElementById('ai-summary').innerHTML = ai_summary;
}
```

### Using the Ask AI API

```javascript
async function askAI(clientId, lastLogin, currentLogin, question) {
  const formData = new URLSearchParams({
    client_id: clientId,
    user_last_login_date: lastLogin,
    user_current_login_date: currentLogin,
    question: question
  });

  const res = await fetch('http://localhost:8000/api/ask-ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData.toString()
  });

  const { answer } = await res.json();
  return answer; // Plain text with bullet points
}
```

### Suggested Drill-Down Questions

These 5 questions are pre-tested and give excellent detailed answers:

| # | Question |
|---|----------|
| 1 | *Which region had the biggest NPS change since my last login?* |
| 2 | *Which area is showing the most decline and needs immediate attention?* |
| 3 | *What is the top customer concern I should act on right now?* |
| 4 | *What drove the NPS improvement (or decline) this period?* |
| 5 | *How many churn intent signals were detected and where are they coming from?* |

---

## 🔧 Troubleshooting

### `Could not import module "main"` on uvicorn start
**Cause:** You are running uvicorn from the wrong directory.  
**Fix:** Always run from inside the `backend/` folder:
```powershell
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### `Form data requires "python-multipart"` error
**Fix:** Install the missing package:
```powershell
pip install python-multipart
```
Or reinstall all requirements: `pip install -r requirements.txt`

### `⚠️ Running without DB — mock data mode active`
**Cause:** DB credentials are wrong or the server is unreachable.  
**Fix:** Check `SURVEY_DB_HOST`, `SURVEY_DB_USER`, `SURVEY_DB_PASSWORD` in your `.env` file.  
Visit `http://localhost:8000/api/health` to see the exact connection error.

### AI gives generic answers / no OpenAI responses
**Cause:** `OPENAI_API_KEY` is missing or invalid.  
**Fix:** Add your valid key to `.env`:
```env
OPENAI_API_KEY=sk-proj-...your-key...
```

### `Query error: Table 'survey_responses_9' doesn't exist`
**Cause:** The client is mapped to surveys whose response tables haven't been created yet.  
**Impact:** None — the system automatically skips missing tables and uses available data.

---

## 📦 Dependencies

### Backend (`requirements.txt`)
| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework for the API |
| `uvicorn` | ASGI server to run FastAPI |
| `python-multipart` | Parses Form Data in POST requests |
| `pymysql` | MySQL database driver |
| `sqlalchemy` | ORM and query builder |
| `openai` | OpenAI GPT API client |
| `pydantic-settings` | Config management from `.env` |
| `python-dotenv` | Loads `.env` file |
| `loguru` | Structured logging |
| `pandas` | Data aggregation helpers |
| `cryptography` | Secure DB connection |

### Frontend
| Package | Purpose |
|---------|---------|
| `react` | UI framework |
| `vite` | Dev server and bundler |

---

## 👨‍💻 Development Notes

- All dates passed to APIs must be in **`DD/MM/YYYY`** format
- The greeting (`Good morning/afternoon/evening`) is based on the **actual server time at the moment of the API call**, not the dates you pass in
- The `is_mock` field in `/api/popup-data` response tells you if real or fallback data is being returned
- Hot-reload is enabled by default — any change to `.py` files will automatically restart the server

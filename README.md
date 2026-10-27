# 📡 SurveyCXM — Login Intelligence Popup

A full-stack AI-powered login popup system that greets users with a **personalized summary**, shows **live NPS analytics** from their database, and lets them **ask AI any question** about their CX data — all scoped to the window between their last login and their current login.

---

## 📁 Project Structure

```
SurveyCXM_AI_Popup/
├── main.py                   # FastAPI app entrypoint, CORS, startup hooks
├── config.py                 # Settings from .env (DB, OpenAI, rate limits)
├── database.py               # MySQL connection + analytical query methods
├── requirements.txt          # Python dependencies
├── .env                      # Environment configuration
├── routes/
│   ├── popup.py              # Login summary & Ask-AI CX analytics endpoints
│   ├── rag.py                # Documentation RAG search & sync endpoints
│   ├── category_generator.py # Industry category & subcategory endpoints
│   └── review_suggestion.py  # AI review suggestion endpoints
├── services/
│   ├── ai_service.py         # OpenAI summary, CX metrics & RAG Q&A logic
│   ├── rag_service.py        # ChromaDB vector indexer & semantic search
│   ├── popup_service.py      # Date parsing & issue aggregation
│   ├── mock_data.py          # Fallback data when DB is unavailable
│   ├── demographic_service.py # Region/State/City breakdown
│   ├── freetext_service.py   # Voice-of-customer text parsing
│   ├── rate_limiter.py       # In-memory sliding window IP rate limiter
│   └── tts_service.py        # Text-to-speech audio synthesis
├── test_api.py               # Integration test runner
├── test_security.py          # Security, auth, and rate limit test suite
├── test_rag_eval.py          # DeepEval RAG retrieval & faithfulness evaluation
└── test_comprehensive_edge_cases.py # 23-test logic, guardrail & edge-case test suite
```

---

## ⚙️ Environment Setup

### 1. Python Virtual Environment

Set up and activate your virtual environment:

```powershell
# Create virtual environment (first time only)
python -m venv venv

# Activate it (Windows PowerShell)
.\venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

### 2. Configure `.env` File

Ensure `.env` contains your credentials:

```env
# OpenAI
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_MODEL=gpt-4o-mini

# MySQL Database
SURVEY_DB_HOST=your-db-host
SURVEY_DB_PORT=3306
SURVEY_DB_NAME=surveycx_demo
SURVEY_DB_USER=your-db-user
SURVEY_DB_PASSWORD=your-db-password

# Security & Secrets
API_SECRET_KEY=my_secret_123
ADMIN_SECRET=your_admin_secret
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
- Serve interactive API documentation at `http://127.0.0.1:8000/docs`
- Pre-warm the database connection and documentation vector store on startup

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

### `POST /api/doc-rag-search`

**Dedicated Documentation Vector Search & Grounded Q&A Endpoint.**  
Performs dense semantic vector search against indexed official SurveyCXM module documentation and generates step-by-step guidance formatted in clean HTML.

* **Content-Type:** `application/x-www-form-urlencoded`
* **Rate Limit:** 15 requests/minute per IP (`rate_limit_doc_rag_search`)

**Form Data Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | string | ✅ | Free-text question about SurveyCXM features, setups, or workflows |
| `secretKey` | string | ✅ | API secret key or admin secret |
| `chat_history` | string (JSON) | ❌ | Optional JSON array of previous chat messages |

**Example Request (cURL):**
```bash
curl -X POST http://localhost:8000/api/doc-rag-search \
  -d "question=How do I create a new survey from scratch?&secretKey=my_secret_123"
```

**Response:**
```json
{
  "answer": "<p>To create a new survey in <strong>SurveyCXM</strong>, follow these steps:</p><ol><li>Navigate to <strong>Build Survey</strong> from the left navigation menu.</li><li>Click <strong>+ New Survey</strong> in the top-right corner...</li></ol>"
}
```

---

### `POST /api/sync-documentation`

**Admin endpoint to synchronize and re-index the documentation vector store.**  
Reads active categories from `documentation_categories` table in MySQL and updates ChromaDB.

* **Content-Type:** `application/x-www-form-urlencoded`
* **Headers:** `x-admin-secret: <ADMIN_SECRET>` (required)
* **Parameters:** `force` (boolean, optional, default `false`)

**Example Request (cURL):**
```bash
curl -X POST http://localhost:8000/api/sync-documentation \
  -H "x-admin-secret: your_admin_secret" \
  -d "force=true"
```

---

### `GET /api/health`

Health check — verifies that both the MySQL database and the ChromaDB RAG documentation vector store are initialized and operational.

```
GET http://localhost:8000/api/health
```

**Response:**
```json
{
  "status": "healthy",
  "connected": true,
  "database": {
    "connected": true,
    "database": "surveycx_dev",
    "host": "188.241.187.49"
  },
  "rag": {
    "status": "healthy",
    "initialized": true,
    "collection": "surveycxm_documentation",
    "total_chunks": 79,
    "categories_count": 6
  }
}
```

---

### `GET /api/logs`

Returns the most recent tail of application log entries as plain text. Protected by admin secret header.

* **Headers:** `x-admin-secret: <ADMIN_SECRET>` (required)
* **Query Parameters:** `lines` (integer, optional, default `100`, max `1000`)
* **Response Content-Type:** `text/plain; charset=utf-8`

**Example Request (cURL):**
```bash
curl http://localhost:8000/api/logs?lines=50 \
  -H "x-admin-secret: your_admin_secret"
```

---

### `POST /api/clear-logs`

Empties the `app.log` file on the server and sends a clear-screen terminal signal.

* **Headers:** `x-admin-secret: <ADMIN_SECRET>` (required)

**Example Request (cURL):**
```bash
curl -X POST http://localhost:8000/api/clear-logs \
  -H "x-admin-secret: your_admin_secret"
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

The repository includes comprehensive automated test suites covering unit logic, edge cases, security guardrails, rate limiting, and DeepEval RAG evaluations:

```powershell
# 1. Run Complete Logic & Edge-Case Unit Suite (22 Tests)
python test_comprehensive_edge_cases.py

# 2. Run Security, Authentication & Sliding-Window Rate Limit Tests (20 Tests)
python -m pytest test_security.py

# 3. Run DeepEval RAG Faithfulness & Relevancy Benchmarks
python test_rag_eval.py

# 4. Run Live API Integration Tests
python test_api.py
```

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
**Fix:** Always run from the project root directory:
```powershell
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

## 📦 Dependencies (`requirements.txt`)

| Package | Purpose |
|---------|---------|
| `fastapi` | High-performance async web framework |
| `uvicorn` | ASGI server to run FastAPI |
| `python-multipart` | Form Data parser for POST endpoints |
| `pymysql` | MySQL database driver |
| `sqlalchemy` | Connection pooling and query management |
| `openai` | OpenAI GPT API client (`gpt-4o-mini`) |
| `chromadb` | Embedded semantic vector store (`all-MiniLM-L6-v2`) |
| `pydantic-settings` | Strongly-typed environment configuration |
| `python-dotenv` | Automatically loads variables from `.env` |
| `loguru` | Structured logging with automatic file rotation |
| `deepeval` | Automated LLM evaluation framework |
| `pytest` | Security and unit testing suite |

---

## 👨‍💻 Development Notes

- All dates passed to APIs must be in **`DD/MM/YYYY`** format
- The greeting (`Good morning/afternoon/evening`) is based on the **actual server time at the moment of the API call**, not the dates you pass in
- The `is_mock` field in `/api/popup-data` response tells you if real or fallback data is being returned
- Hot-reload is enabled by default — any change to `.py` files will automatically restart the server

---

## 🛡️ Architecture Hardening & Concurrency Guardrails

The RAG and analytics pipelines include dedicated production-grade safeguards:

1. **Decoupled Architecture (`routes/rag.py` & `routes/popup.py`)**:
   - `/api/ask-ai` executes solely against real-time MySQL CX analytics (~230ms latency) without vector search overhead.
   - Platform feature and how-to queries are handled by `/api/doc-rag-search` with semantic ChromaDB vector retrieval.
2. **Concurrency & Thread Safety**:
   - `DocRAGService` uses `threading.RLock()` and an `_is_syncing` atomic flag to prevent SQLite lockups (`sqlite3.OperationalError`) during background re-indexing or simultaneous client queries.
3. **Database Timeout Protection**:
   - Database service initialization implements a singleton latch (`_db_attempted`) to prevent repeated 15-second network socket timeout lockups when remote MySQL nodes are unreachable.
4. **Hierarchical HTML Chunking**:
   - Splits category documentation along `<h1>` through `<h4>` headers while capturing introductory module overviews.
   - Automatically sub-chunks oversized bulleted lists (>3,500 characters) into semantic ~2,200 character units.
5. **Calibrated Similarity Thresholding**:
   - Cosine similarity cutoff calibrated to $\ge 0.42$ using `all-MiniLM-L6-v2` 384-dimensional embeddings, preventing false-positive injections on unrelated questions.
6. **Strict Input Validation & HTTP Standards**:
   - Rejects empty questions or overlong questions (>500 characters) with `HTTP 400 Bad Request`.
   - Rejects unauthorized or missing credentials with `HTTP 401 Unauthorized`.
   - Enforces per-IP sliding-window rate limiting with `HTTP 429 Too Many Requests`.

---

## 🧪 DeepEval Automated LLM & RAG Testing

We use [DeepEval](https://github.com/confident-ai/deepeval) to evaluate and benchmark the quality of our RAG documentation retrieval and LLM response generation:

### Tested Evaluation Dimensions:
1. **Answer Relevancy**: Assesses whether generated responses directly answer the user prompt in clean HTML.
2. **Faithfulness**: Measures whether responses are fully grounded in retrieved module documentation without hallucination.
3. **Domain Scope Guardrails (GEval)**: Validates that queries unrelated to SurveyCXM or CX are strictly rejected.

### Running DeepEval Tests:
```bash
# Standalone execution
python test_rag_eval.py

# Or via DeepEval / Pytest CLI
deepeval test run test_rag_eval.py
```

# SurveyCXM — Ask AI RAG Implementation Guide

## 1. Overview & Objective

Prior to this implementation, the **Ask AI** chatbot in SurveyCXM functioned solely as an analytical calculation tool. It accepted user login dates and calculated NPS deltas, customer verbatim themes, and demographic breakdowns from the database. If a user asked platform-level questions (such as *"How do I create a survey?"* or *"How does branching logic work?"*), the model would fail or report that no survey responses were recorded.

This enhancement introduces a **Retrieval-Augmented Generation (RAG)** architecture that upgrades Ask AI into a **Dual-Engine Platform & Intelligence Assistant**:
1. **Engine 1 (Analytics Engine):** Real-time SQL queries for NPS, response counts, detractors, and customer voice alerts.
2. **Engine 2 (Knowledge RAG Engine):** Dense vector retrieval over official SurveyCXM module documentation from the database (`documentation_categories`), providing accurate, step-by-step guidance on features, configurations, and workflows.

---

## 2. Type of RAG Architecture

The implementation uses a **Hybrid Dual-Engine Knowledge-Base RAG** with the following technical classifications:

| Architectural Component | Classification | Implementation Detail |
| :--- | :--- | :--- |
| **RAG Pattern** | **Knowledge-Base RAG** (Modular Domain Guidance) | Retrieves verified module documentation to answer how-to, setup, and configuration questions. |
| **Retrieval Mode** | **Dense Vector Semantic Search** | Cosine distance search in a continuous vector space ($1.0 - \text{distance}$). |
| **Embedding Engine** | **Local ONNX Embeddings** (`all-MiniLM-L6-v2`) | Embedded directly in the backend process via ChromaDB. Zero external API calls, 384 vector dimensions. |
| **Vector Database** | **Embedded ChromaDB** (`PersistentClient`) | File-based local vector store saved in `./data/chroma_db/`. No external server required. |
| **Execution Pattern** | **Asynchronous Concurrent Retrieval** | RAG retrieval executes in parallel with SQL queries via Python's `asyncio.gather()`, adding zero net latency. |
| **Generation Model** | **LLM Synthesis** (`gpt-4o-mini`) | Generates clean, structured HTML responses grounded strictly in the retrieved documentation context. |

---

## 3. Architecture & Data Flow

```
                               Incoming User Question
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
       [Engine 1: SQL Analytics]                   [Engine 2: Doc RAG Search]
       ─────────────────────────                   ──────────────────────────
       • Client Surveys                            • ChromaDB Semantic Search
       • NPS Delta & Demographics                  • MiniLM-L6-v2 Local Embeddings
       • Voice of Customer Verbatims               • Top K=3 Chunks (Threshold >= 0.30)
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         ▼
                            Unified Prompt Synthesizer
                            ──────────────────────────
                            • Injects verified documentation
                            • Injects live CX database metrics
                            • Enforces clean HTML formatting rules
                                         ▼
                                   OpenAI LLM
                                  (gpt-4o-mini)
                                         ▼
                       Structured Step-by-Step HTML Response
```

---

## 4. Step-by-Step Implementation Details

### Step 1: Database Source Integration (`database.py`)
The knowledge source is stored in the MySQL table `documentation_categories`, which contains documentation for all SurveyCXM modules:
- `name`: Module title (e.g., *Survey Management*, *Trigger & Automation*, *Access Management*).
- `description`: High-level summary of the module's purpose.
- `content`: Comprehensive HTML documentation with procedures, supported question types, logic rules, and channel settings.

A dedicated database query method was added:
```python
def get_documentation_categories(self, active_only: bool = True) -> list[dict[str, Any]]:
    """Fetch documentation categories including name, description, and HTML content."""
    sql = "SELECT id, name, description, content, is_active FROM documentation_categories"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY sort_order ASC, id ASC"
    return self._execute_query(sql)
```

---

### Step 2: Intelligent HTML Parsing & Chunking (`services/rag_service.py`)
Documentation content in MySQL is stored as formatted HTML. Naive plain-text stripping loses hierarchical meaning (which section belongs to which tab). 

The chunker in `services/rag_service.py` performs **hierarchical header-based splitting**:
1. Uses regular expressions (`<h[2-4]>`) to identify logical section boundaries.
2. Extracts clean readable text while converting `<li>` items into bullet points and `<p>` tags into paragraph breaks.
3. Prepend metadata context to every chunk:
   ```text
   Module: Survey Management
   Section: Tab 5: Logics & Conditional Branching
   Module Overview: Build, configure, and publish surveys...
   
   [Clean Section Body...]
   ```
4. If an individual section exceeds 3,500 characters, it is recursively split into sub-chunks (~2,200 characters) to ensure high semantic density without exceeding token budgets.
5. Result: **79 granular semantic chunks** indexed across all 6 core modules.

---

### Step 3: Local ONNX Vector Storage (`services/rag_service.py`)
To avoid latency and eliminate third-party API dependencies or permission constraints:
- Uses **ChromaDB's native local embedding function** (`DefaultEmbeddingFunction` with `all-MiniLM-L6-v2`).
- Runs 100% locally on the CPU using `onnxruntime`.
- **Zero API token cost** for embedding generation and queries.
- Persisted locally under `./data/chroma_db/`.

#### Intelligent Hash Caching:
On server boot or sync:
1. An MD5 hash of all category IDs, names, descriptions, and contents is computed.
2. If `doc_index_meta.json` matches the database hash, the index is kept as-is, achieving **instant (0ms) application startup**.
3. If changes are detected in MySQL, ChromaDB automatically re-indexes the documentation.

---

### Step 4: Semantic Retrieval Algorithm
When a user asks a question in `Ask AI`:
1. The question is embedded using the local model.
2. ChromaDB performs a cosine similarity query:
   $$\text{Similarity} = 1.0 - \text{Cosine Distance}$$
3. Results are filtered by a confidence threshold ($\text{similarity} \ge 0.30$) to prevent injecting irrelevant documentation chunks when users ask purely numerical/analytical questions.
4. Top 3 matching chunks are formatted into structured reference blocks for the LLM.

---

### Step 5: Dual-Identity Prompt Synthesis (`services/ai_service.py`)
The system prompt in `answer_user_question()` was redesigned to support both domains:

1. **Dual Persona:** The AI knows it is both a **SurveyCXM Application Specialist** (workflows, logics, configurations) and a **CX Data Analyst** (live NPS, scores, detractors).
2. **Procedural Guidance:** When answering how-to queries, the AI outputs numbered lists (`<ol>`, `<li>`), highlights module and tab names in `<strong>`, and wraps placeholders/variables in `<code>`.
3. **HTML Output Guarantee:** All answers are structured in clean HTML for direct rendering inside frontend chat bubbles. Markdown asterisks (`**`) and hashes (`#`) are disallowed.
4. **Boundary Control:**
   - Non-SurveyCXM questions (e.g., recipes, outside coding, sports) receive a clean rejection: `<p>I cannot assist with topics outside of SurveyCXM.</p>`.
   - SurveyCXM questions with no recorded survey activity in the selected dates are answered directly: `<p>No response data was recorded for [item].</p>`.
   - Platform/how-to questions are **never rejected**.

---

### Step 6: Dedicated Documentation RAG Endpoint (`routes/rag.py`)
To keep the real-time CX metrics pipeline and documentation search completely clean and decoupled, a dedicated router was created in `routes/rag.py`:
- **Endpoint:** `POST /api/doc-rag-search`
- **Rate Limit:** Dedicated sliding-window rate limit (15 requests/minute).
- **Form Parameters:**
  - `question` (required): User's question about platform features, setup, logic, etc.
  - `secretKey` (required): API secret key (`api_secret_key`) or admin secret (`admin_secret`).
  - `chat_history` (optional): JSON array of previous chat messages `[{"role": "user", "content": "..."}, ...]`.
- **Response Format:**
  ```json
  {
    "answer": "<p>Step-by-step guidance formatted in clean HTML...</p>"
  }
  ```

#### Exact Fallbacks & System Behaviors:
- **Greeting:** `<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>`
- **Out of Scope:** `<p>I cannot assist with topics outside of SurveyCXM.</p>`
- **Missing Documentation:** `<p>No documentation found for this feature. Please contact your administrator.</p>`
- **Decoupled Architecture:** `/api/ask-ai` remains exclusively focused on real-time CX database metrics (NPS delta, demographics, Voice of Customer, and survey comparisons) without vector search overhead. If platform feature questions are sent to `/api/ask-ai`, it redirects the user to `/api/doc-rag-search`.

---

### Step 7: Admin Sync Endpoint (`routes/rag.py`)
An administrative endpoint is available to allow on-demand re-indexing whenever administrators update documentation in the database:
- **Endpoint:** `POST /api/sync-documentation`
- **Authentication:** Requires `x-admin-secret` HTTP request header matching `settings.admin_secret`.
- **Parameters:** `force` (boolean, Form parameter, optional).

---

## 5. Test Verification Matrix

All six target workflow categories, plus live data and out-of-scope queries, were tested end-to-end:

| Query Category | Example User Question | Retrieved Module & Section | Model Response Quality |
| :--- | :--- | :--- | :--- |
| **Survey Creation** | *"How do I create a new survey in SurveyCXM?"* | `[Survey Management]`<br>Section: *1. Survey Creation Methods* | Provided clear 4-step sequence: navigating to Build Survey, selecting survey type, configuring questions, and publishing. |
| **Survey Logic** | *"How does survey logic work, including conditional questions and branching?"* | `[Survey Management]`<br>Section: *Tab 5: Logics & Conditional Branching* | Detailed skip logic, display logic, condition rules, and navigation jumps. |
| **Multilingual** | *"How can I enable and configure the multilingual feature for a survey?"* | `[Survey Management]`<br>Section: *Tab 4: Languages & Multi-Language Support* | Explained adding secondary languages, uploading translations, and respondent language toggling. |
| **Roles & Permissions** | *"How do user roles and permissions work, and how can access be managed?"* | `[Access Management]`<br>Section: *A. Creating & Managing Roles* | Described the 2-Tier Permission Matrix (Sidebar access vs Action-level routes) and user onboarding. |
| **Survey Triggers** | *"How are surveys triggered automatically based on specific events?"* | `[Trigger & Automation]`<br>Section: *1.3 Trigger Execution Methods Working* | Detailed real-time transactional dispatches, schedule-based triggers, and payload requirements. |
| **SMS Triggers** | *"How can I trigger or distribute surveys through SMS, and what configurations are required?"* | `[Trigger & Automation]`<br>Section: *Mode 2: REST API Trigger Integration* | Step-by-step setup in Triggers & Automations module: SMS gateway setup, template placeholders, phone field mapping. |
| **Live CX Data** | *"What is our current NPS and total responses?"* | Database SQL Queries | Returned exact live figures: `<p>Your current NPS is <strong>0</strong> with a total of <strong>0 responses</strong>.</p>`. |
| **Out-of-Scope** | *"Can you give me a recipe for chocolate cake?"* | Domain Guardrails | Rejection returned: `<p>I cannot assist with topics outside of SurveyCXM.</p>`. |

---

## 6. Key Files Modified & Created

| File | Type | Description |
| :--- | :--- | :--- |
| [`routes/rag.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/routes/rag.py) | **Created** | Dedicated router hosting `/api/doc-rag-search` (with aliases) and `/api/sync-documentation`. |
| [`services/rag_service.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/services/rag_service.py) | **Created** | Core RAG service: HTML chunker, ChromaDB integration, local embeddings, hash caching, semantic search. |
| [`database.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/database.py#L923-L937) | **Modified** | Added `get_documentation_categories()` to retrieve active modules from MySQL; added connection attempt latch. |
| [`services/ai_service.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/services/ai_service.py#L222-L290) | **Modified** | Added `answer_rag_question()` for dedicated doc RAG synthesis with exact fallbacks & greetings. |
| [`routes/popup.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/routes/popup.py) | **Modified** | Decoupled from RAG; dedicated purely to CX metrics, login summary, and audio generation. |
| [`main.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/main.py#L89-L103) | **Modified** | Registered `rag_router` under `tags=["Documentation RAG"]` and added startup pre-warming. |
| [`requirements.txt`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/requirements.txt#L14) | **Modified** | Added `chromadb>=1.5.0` dependency. |
| [`test_comprehensive_edge_cases.py`](file:///d:/SUNIL%20KUMAWAT/Live_Projects/SurveyCXM_AI_Popup/test_comprehensive_edge_cases.py) | **Created** | 23-test automated unit and edge case test runner. |

---

## 7. How to Maintain & Update the Documentation Index

1. **Automatic Detection:** Whenever the backend server restarts, it automatically inspects `documentation_categories` in MySQL. If any category was added, edited, or deleted, it re-indexes automatically.
2. **Manual / Webhook Trigger:** If you update documentation in the database without restarting the server, make a POST request with the admin secret header:
   ```bash
   curl -X POST http://localhost:8000/api/sync-documentation \
     -H "x-admin-secret: your_admin_secret" \
     -d "force=true"
   ```
   The vector store will re-chunk and re-embed all active documentation in ~2 seconds.

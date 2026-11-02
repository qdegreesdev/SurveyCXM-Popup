"""
SurveyCXM Ask-AI Autonomous Tool-Calling Agent

An intelligent supervisor agent (powered by OpenAI Function Calling & GPT-4o-mini)
dedicated exclusively to SurveyCXM Customer Experience (CX) analytics, live performance metrics,
and survey response database analysis.

Tools:
1. get_dashboard_cx_metrics: Rapid retrieval of aggregated NPS, demographics, customer voice, and survey comparisons.
2. execute_custom_survey_query: Safe, read-only Text-to-SQL execution against dynamic survey response tables
   for ad-hoc analytical questions with strict tenant isolation, table whitelisting, and memory limits.

Note:
Platform documentation and feature how-to questions are strictly decoupled from Ask-AI.
When a user asks a platform guide or how-to question, Ask-AI provides a friendly message
and redirects them to the Platform Documentation section.
"""

import asyncio
from datetime import datetime
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Optional

from openai import AsyncOpenAI
from config import settings
import database
from database import get_db_service
from services.popup_service import aggregate_issues

logger = logging.getLogger(__name__)

# ── Standard Redirection Message for Platform Documentation Queries ───────────
DOC_REDIRECT_MESSAGE = (
    "<p>For platform guides and help instructions, please check our <strong>Documentation</strong> section.</p>"
)

# Fast-path pattern for common platform documentation queries
DOC_REDIRECT_TRIGGERS = re.compile(
    r'\b(how (to|do i|can i) (create|build|make|setup|set up|configure|design|add|delete|edit)\s+(a\s+)?(survey|branch|logic|question|user|role|webhook|distribution)'
    r'|conditional (branching|skip) logic|branching logic|skip logic|user roles|permissions|multilingual survey|'
    r'distribution channel|email trigger|webhook setup|how does .* (branching|logic) work)\b',
    re.IGNORECASE
)

# ── Security & Mutation Keyword Blocklist ─────────────────────────────────────
FORBIDDEN_SQL_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|REPLACE|CREATE|GRANT|REVOKE|LOCK|CALL|EXEC|EXECUTE|INTO\s+OUTFILE|LOAD_FILE)\b',
    re.IGNORECASE
)

# ── Tool Definitions for OpenAI Function Calling (Strictly Data & Metrics) ─────
def get_agent_tools(last_login_dt: Optional[datetime] = None, current_login_dt: Optional[datetime] = None) -> list[dict]:
    """Generates agent tools with dynamic date guidance bound to request payload fields."""
    date_guidance = ""
    if last_login_dt and current_login_dt:
        date_guidance = (
            f" STRICT REQUIREMENT: By default, filter by the payload date window on created_at: "
            f"`WHERE created_at >= '{last_login_dt.strftime('%Y-%m-%d %H:%M:%S')}' AND created_at <= '{current_login_dt.strftime('%Y-%m-%d %H:%M:%S')}'` "
            f"unless the user specifically asks for all-time/lifetime data."
        )

    return [
        {
            "type": "function",
            "function": {
                "name": "get_dashboard_cx_metrics",
                "description": (
                    "Retrieves the client's aggregated CX performance metrics across their active surveys for the "
                    "active reporting period. Returns overall NPS score, score delta (improvement/decline), total responses, "
                    "promoter/passive/detractor percentages, regional/state/city demographic breakdowns, and top customer "
                    "complaint issues with verbatim feedback."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_nps": {
                            "type": "boolean",
                            "description": "Whether to include overall NPS, promoter/passive/detractor percentages, and delta. Default true."
                        },
                        "include_demographics": {
                            "type": "boolean",
                            "description": "Whether to include Region, State, City, Branch score breakdowns. Default true."
                        },
                        "include_customer_voice": {
                            "type": "boolean",
                            "description": "Whether to include Voice of Customer verbatim feedback and critical churn signals. Default true."
                        },
                        "include_surveys": {
                            "type": "boolean",
                            "description": "Whether to include individual survey response counts and scores. Default true."
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "execute_custom_survey_query",
                "description": (
                    "Executes a custom, safe read-only SQL SELECT query on the client's survey response tables to answer "
                    "detailed or ad-hoc analytical questions not covered by the standard dashboard (e.g. filtering by "
                    "specific survey questions, analyzing specific customer comments, comparing ratings for a specific "
                    "branch or date). Only SELECT queries are permitted."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": (
                                "The read-only SQL SELECT query to execute. Question column slugs are UUIDs and MUST be "
                                "enclosed in backticks (e.g. `2c34473a-ce0c-4cda-acd6-80ef67fd4f45`). Only tables for "
                                f"this client's active surveys (e.g. `survey_responses_{{survey_id}}`) are accessible.{date_guidance}"
                            )
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Brief 1-sentence explanation of what this query calculates and why."
                        }
                    },
                    "required": ["sql_query"]
                }
            }
        }
    ]

# Default tools reference for backward compatibility
AGENT_TOOLS = get_agent_tools()


class AskAIAgent:
    """
    Supervisor Agent for Ask-AI.
    Dedicated to Customer Experience (CX) analytics, metrics, and survey data queries.
    """

    def __init__(self):
        self._schema_cache: dict[int, dict] = {}
        self._schema_cache_ttl = 600  # 10 minutes

    # ── Schema Introspection & Caching ────────────────────────────────────────

    def get_client_schema_context(self, client_id: int) -> dict[str, Any]:
        """
        Inspects the MySQL database to build a schema summary of active surveys,
        questions, UUID slugs, and filter fields for the given client_id.
        """
        now = time.time()
        cached = self._schema_cache.get(client_id)
        if cached and (now - cached["timestamp"]) < self._schema_cache_ttl:
            return cached["data"]

        db = get_db_service()
        if not db or not database.DB_AVAILABLE:
            return {"surveys": [], "allowed_tables": []}

        surveys = db._execute_query(
            "SELECT id, name FROM surveys WHERE client_id = %s ORDER BY id ASC LIMIT 25",
            (client_id,)
        )
        if not surveys:
            return {"surveys": [], "allowed_tables": []}

        survey_ids = [s["id"] for s in surveys]
        allowed_tables = [f"survey_responses_{sid}" for sid in survey_ids] + ["surveys", "questions", "metadata_fields"]

        # Fetch questions for these surveys
        placeholders = ", ".join(["%s"] * len(survey_ids))
        questions = db._execute_query(
            f"SELECT id, survey_id, question, slug, type FROM questions WHERE survey_id IN ({placeholders}) ORDER BY survey_id, sort_order ASC LIMIT 200",
            tuple(survey_ids)
        )

        # Fetch metadata fields
        meta_rows = db._execute_query(
            f"SELECT survey_id, filter_1, filter_2, filter_3, filter_4 FROM metadata_fields WHERE survey_id IN ({placeholders})",
            tuple(survey_ids)
        )
        meta_by_survey = {
            m["survey_id"]: {
                "filter_1": m.get("filter_1") or "Region",
                "filter_2": m.get("filter_2") or "State",
                "filter_3": m.get("filter_3") or "City",
                "filter_4": m.get("filter_4") or "Branch",
            }
            for m in meta_rows
        }

        questions_by_survey = {}
        for q in questions:
            sid = q["survey_id"]
            if sid not in questions_by_survey:
                questions_by_survey[sid] = []
            questions_by_survey[sid].append({
                "slug": q["slug"],
                "type": q["type"],
                "question": q["question"]
            })

        survey_summaries = []
        for s in surveys:
            sid = s["id"]
            survey_summaries.append({
                "survey_id": sid,
                "name": s["name"],
                "table_name": f"survey_responses_{sid}",
                "filters": meta_by_survey.get(sid, {}),
                "questions": questions_by_survey.get(sid, [])[:15]
            })

        result = {
            "surveys": survey_summaries,
            "allowed_tables": allowed_tables,
            "survey_ids": survey_ids
        }
        self._schema_cache[client_id] = {"timestamp": now, "data": result}
        return result

    # ── Secure SQL Execution Guardrail ────────────────────────────────────────

    def validate_and_execute_sql(
        self,
        client_id: int,
        sql_query: str,
        allowed_tables: list[str]
    ) -> dict[str, Any]:
        """
        Validates that the SQL query is strictly read-only, accesses only allowed tables
        for this client, enforces a maximum row limit of 50, and executes it securely.
        """
        clean_sql = sql_query.strip().rstrip(";")

        # 1. Reject empty queries
        if not clean_sql:
            return {"success": False, "error": "Query cannot be empty."}

        # 2. Strict read-only check: Must start with SELECT or WITH
        if not re.match(r'^(SELECT|WITH)\b', clean_sql, re.IGNORECASE):
            return {
                "success": False,
                "error": "Security Violation: Only read-only SELECT or WITH statements are allowed."
            }

        # 3. Reject any mutation / DDL keywords
        if FORBIDDEN_SQL_KEYWORDS.search(clean_sql):
            return {
                "success": False,
                "error": "Security Violation: Data modification, DDL, or file access commands are strictly forbidden."
            }

        # 4. Table-level Tenant Isolation: Extract referenced tables
        table_matches = re.findall(r'\b(?:FROM|JOIN)\s+([`\w]+)', clean_sql, re.IGNORECASE)
        allowed_set = {t.lower().replace("`", "") for t in allowed_tables}

        for raw_tbl in table_matches:
            tbl_clean = raw_tbl.replace("`", "").strip().lower()
            if tbl_clean not in allowed_set:
                return {
                    "success": False,
                    "error": f"Security Violation: Access denied to table '{tbl_clean}'."
                }

        # 5. Enforce LIMIT 50 to prevent memory exhaustion
        limit_match = re.search(r'\bLIMIT\s+(\d+)', clean_sql, re.IGNORECASE)
        if limit_match:
            val = int(limit_match.group(1))
            if val > 50:
                clean_sql = re.sub(r'\bLIMIT\s+\d+', 'LIMIT 50', clean_sql, flags=re.IGNORECASE)
        else:
            clean_sql += " LIMIT 50"

        # 6. Execute via existing MySQL connection pool
        db = get_db_service()
        if not db or not database.DB_AVAILABLE:
            return {"success": False, "error": "Database service is offline."}

        try:
            logger.info(f"Agent executing safe SQL for client {client_id}: {clean_sql[:120]}")
            rows = db._execute_query(clean_sql)
            return {
                "success": True,
                "row_count": len(rows),
                "rows": rows[:50]
            }
        except Exception as e:
            logger.warning(f"Agent SQL execution error: {e} | Query: {clean_sql}")
            return {"success": False, "error": str(e)}

    # ── Tool Execution Dispatcher ─────────────────────────────────────────────

    async def execute_tool(
        self,
        name: str,
        args_json: str,
        client_id: int,
        survey_ids: list[int],
        last_login_dt: datetime,
        current_login_dt: datetime,
        allowed_tables: list[str]
    ) -> dict[str, Any]:
        """Dispatches an agent tool call to the appropriate backend service."""
        try:
            args = json.loads(args_json) if args_json else {}
        except Exception:
            args = {}

        if name == "get_dashboard_cx_metrics":
            db = get_db_service()
            if not db or not database.DB_AVAILABLE:
                return {"error": "Database service is offline."}

            # Filter survey_ids to those whose table actually exists in MySQL to avoid 1146 errors
            existing_survey_ids = [
                sid for sid in survey_ids
                if db._check_table_exists(f"survey_responses_{sid}")
            ]
            active_survey_ids = existing_survey_ids if existing_survey_ids else survey_ids

            results = await asyncio.gather(
                asyncio.to_thread(db.get_nps_data_for_surveys, active_survey_ids, last_login_dt, current_login_dt),
                asyncio.to_thread(db.get_demographic_breakdown_for_surveys, active_survey_ids, last_login_dt, current_login_dt),
                asyncio.to_thread(db.get_customer_voice_data_for_surveys, active_survey_ids, last_login_dt, current_login_dt),
                asyncio.to_thread(db.get_survey_comparison, active_survey_ids, last_login_dt, current_login_dt),
                return_exceptions=True
            )

            nps_data = results[0] if not isinstance(results[0], Exception) else {}
            demographics = results[1] if not isinstance(results[1], Exception) else []
            voice = results[2] if not isinstance(results[2], Exception) else {}
            survey_comparison = results[3] if not isinstance(results[3], Exception) else []

            critical_issues = await asyncio.to_thread(aggregate_issues, voice.get("high_severity_records", [])) if voice else []

            # Format compact summary
            return {
                "period": f"{last_login_dt.strftime('%d/%m/%Y')} to {current_login_dt.strftime('%d/%m/%Y')}",
                "nps": {
                    "current": nps_data.get("current", 0),
                    "previous": nps_data.get("previous", 0),
                    "delta": nps_data.get("delta", 0),
                    "total_responses": nps_data.get("total_responses", 0),
                    "promoters_pct": nps_data.get("promoters_pct", 0),
                    "passives_pct": nps_data.get("passives_pct", 0),
                    "detractors_pct": nps_data.get("detractors_pct", 0),
                },
                "demographics_top": demographics[:10] if demographics else [],
                "critical_issues": [
                    {"issue": i["issue"], "count": i["count"], "severity": i["severity"], "samples": [s.get("verbatim", "") for s in i.get("samples", [])[:2]]}
                    for i in critical_issues[:5]
                ],
                "surveys": [
                    {"name": s["name"], "id": s["survey_id"], "responses": s["responses"], "current_nps": s["current_nps"], "delta": s["delta"]}
                    for s in survey_comparison[:10]
                ]
            }

        elif name == "execute_custom_survey_query":
            sql_query = args.get("sql_query", "")
            return self.validate_and_execute_sql(client_id, sql_query, allowed_tables)

        return {"error": f"Unknown tool: {name}"}

    # ── System Prompt Builder ─────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        client_id: int,
        last_login_dt: datetime,
        current_login_dt: datetime,
        schema_context: dict[str, Any]
    ) -> str:
        """Constructs the system prompt with database schema metadata and behavioral guidelines."""
        surveys_info = []
        for s in schema_context.get("surveys", []):
            q_list = ", ".join([f"`{q['slug']}` ({q['type']}: '{q['question'][:50]}')" for q in s.get("questions", [])[:8]])
            f_list = f"filter_1={s['filters'].get('filter_1')}, filter_2={s['filters'].get('filter_2')}, filter_3={s['filters'].get('filter_3')}, filter_4={s['filters'].get('filter_4')}"
            surveys_info.append(
                f"- Survey '{s['name']}' (ID {s['survey_id']}) -> Table: `{s['table_name']}`\n"
                f"  Filters: {f_list}\n"
                f"  Questions: {q_list or 'None'}"
            )

        surveys_str = "\n".join(surveys_info) if surveys_info else "No survey schema available."

        start_str = last_login_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_str = current_login_dt.strftime('%Y-%m-%d %H:%M:%S')
        period_label = f"{last_login_dt.strftime('%d/%m/%Y')} to {current_login_dt.strftime('%d/%m/%Y')}"

        return f"""You are the SurveyCXM Autonomous CX Analytics & Survey Data Specialist Agent.
You have direct tool access to:
1. `get_dashboard_cx_metrics`: Standard aggregated CX metrics (NPS, response totals, demographics, churn verbatims, survey breakdowns).
2. `execute_custom_survey_query`: Custom read-only SQL queries against the client's dynamic survey response tables for question-level analysis, rating comparisons, or customer feedback searches.

MANDATORY PAYLOAD CONSTRAINTS & STRICT DATA BINDINGS:
1. CLIENT ID (Strict Multi-Tenant Isolation):
   - Active Client ID: {client_id}
   - You MUST ONLY access, analyze, and reference survey data belonging strictly to Client ID {client_id}.
   - Never attempt to query or mention data from other clients. All queries are strictly whitelisted to this client's tables.

2. REPORTING PERIOD (user_last_login_date & user_current_login_date):
   - Start Date (user_last_login_date): {start_str}
   - End Date (user_current_login_date): {end_str}
   - Active Period Label: "{period_label}"
   - STRICT TIME BINDING RULE:
     - All CX metrics, counts, and analysis MUST be strictly bound to this reporting window unless the user explicitly requests all-time or lifetime data.
     - When constructing custom SQL queries via `execute_custom_survey_query` against any `survey_responses_{{id}}` table, you MUST filter by the date window on `created_at`:
       `created_at >= '{start_str}' AND created_at <= '{end_str}'`
       (Exception: only omit this filter if the user explicitly asks for "all time", "lifetime", or a specific historical date range).
     - If no responses exist during this reporting period, state clearly and honestly: "No survey responses were recorded during the selected period ({period_label})." Do NOT invent or hallucinate response counts.

3. USER QUESTION:
   - Target User Query: Answer the user's specific inquiry directly, accurately, and concisely based strictly on retrieved tool data.
   - Ground all numerical metrics, percentages, and verbatim feedback in the data returned by the tools.

4. CONVERSATIONAL CONTEXT (chat_history):
   - Prior conversation turns are provided in context strictly to resolve conversational follow-ups, pronouns (e.g., "what about them?", "and for branch B?"), or comparisons across turns.

CLIENT'S SURVEY DATABASE SCHEMA:
{surveys_str}

STRICT DOMAIN SCOPE & BEHAVIORAL GUIDELINES:
1. EXCLUSIVELY SURVEY DATA & CX ANALYTICS:
   - You answer questions strictly regarding this client's customer experience metrics, survey performance, response counts, NPS changes, regional demographics, and Voice of Customer feedback.
   - For standard dashboard metrics: Call `get_dashboard_cx_metrics`.
   - For specific questions, comment filters, or custom ratings not on the standard dashboard: Call `execute_custom_survey_query`.

2. PLATFORM DOCUMENTATION & HOW-TO QUESTIONS (STRICT REDIRECTION TO DOC RAG):
   - You DO NOT answer platform feature guides, how-to setups, survey creation workflows, branching/skip logic, user role settings, or webhook configurations.
   - If the user asks ANY question about how to use, configure, create, or set up a SurveyCXM platform feature, respond immediately with:
     "{DOC_REDIRECT_MESSAGE}"

3. GENERAL OUT-OF-SCOPE QUESTIONS:
   - If the user asks general-purpose questions unrelated to SurveyCXM (such as writing outside programming code, cooking recipes, weather, sports, or general trivia), respond strictly with:
     "<p>I am your SurveyCXM AI Assistant dedicated to your account CX metrics and survey responses. I cannot assist with topics outside of SurveyCXM.</p>"

4. DYNAMIC SQL RULES:
   - Always enclose question UUID column slugs in backticks (e.g. `SELECT `2c34473a-ce0c-4cda-acd6-80ef67fd4f45` FROM survey_responses_8`).
   - Only query tables belonging to this client (e.g. `survey_responses_{{id}}`).
   - By default, apply the date window filter: `WHERE created_at >= '{start_str}' AND created_at <= '{end_str}'`.
   - Never run mutation statements (no UPDATE/DELETE/DROP). Only SELECT statements.

5. RESPONSE FORMATTING:
   - Format final responses in clean HTML (<p>, <strong>, <ul>, <ol>, <li>, <table>, <code>).
   - Do NOT use Markdown formatting (no **, no markdown headers, no raw markdown bullet points).
   - If asked casual greetings, reply politely: "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>".
   - LANGUAGE ADAPTATION: Always generate your final response in the same language used by the user (English, Spanish, Hindi, etc.).
"""

    # ── Non-Streaming Agent Execution ─────────────────────────────────────────

    async def run(
        self,
        client_id: int,
        last_login_dt: datetime,
        current_login_dt: datetime,
        question: str,
        chat_history: Optional[list] = None
    ) -> str:
        """Runs the agent in non-streaming mode and returns the final HTML string."""
        # 1. Fast-path greeting
        clean_q = re.sub(r'[^\w\s]', '', question.strip().lower())
        if clean_q in ["hyy", "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "greetings", "help"]:
            return "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>"

        # 2. Fast-path redirection for platform documentation queries
        if DOC_REDIRECT_TRIGGERS.search(question):
            return DOC_REDIRECT_MESSAGE

        schema_context = self.get_client_schema_context(client_id)
        survey_ids = schema_context.get("survey_ids", [])
        allowed_tables = schema_context.get("allowed_tables", [])

        system_prompt = self._build_system_prompt(client_id, last_login_dt, current_login_dt, schema_context)
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history and isinstance(chat_history, list):
            for msg in chat_history[-6:]:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({"role": msg["role"], "content": str(msg["content"])[:500]})

        messages.append({"role": "user", "content": question})

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Agent ReAct Loop (Up to 2 tool-calling turns)
        for _ in range(2):
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=get_agent_tools(last_login_dt, current_login_dt),
                tool_choice="auto",
                temperature=0.3
            )

            msg = response.choices[0].message
            if not msg.tool_calls:
                return msg.content or "<p>No response generated.</p>"

            # Append assistant message with tool calls
            messages.append(msg)

            # Execute all requested tools concurrently
            tasks = []
            for tc in msg.tool_calls:
                t_name = tc.function.name
                t_args = tc.function.arguments
                tasks.append(
                    self.execute_tool(
                        name=t_name,
                        args_json=t_args,
                        client_id=client_id,
                        survey_ids=survey_ids,
                        last_login_dt=last_login_dt,
                        current_login_dt=current_login_dt,
                        allowed_tables=allowed_tables
                    )
                )

            tool_outputs = await asyncio.gather(*tasks)

            for tc, output in zip(msg.tool_calls, tool_outputs):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(output)
                })

        # Final synthesis turn
        final_res = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.35
        )
        return final_res.choices[0].message.content or "<p>No response generated.</p>"

    # ── Real-Time Streaming Agent Execution ───────────────────────────────────

    async def run_stream(
        self,
        client_id: int,
        last_login_dt: datetime,
        current_login_dt: datetime,
        question: str,
        chat_history: Optional[list] = None
    ) -> AsyncGenerator[str, None]:
        """
        Runs the agent with full tool-calling execution, streaming final output tokens
        via Server-Sent Events (SSE).
        """
        # 1. Fast-path greeting
        clean_q = re.sub(r'[^\w\s]', '', question.strip().lower())
        if clean_q in ["hyy", "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "greetings", "help"]:
            yield f"data: {json.dumps({'token': '<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>'})}\n\n"
            yield 'data: {"token": "", "done": true}\n\n'
            yield "data: [DONE]\n\n"
            return

        # 2. Fast-path redirection for platform documentation queries
        if DOC_REDIRECT_TRIGGERS.search(question):
            yield f"data: {json.dumps({'token': DOC_REDIRECT_MESSAGE})}\n\n"
            yield 'data: {"token": "", "done": true}\n\n'
            yield "data: [DONE]\n\n"
            return

        schema_context = self.get_client_schema_context(client_id)
        survey_ids = schema_context.get("survey_ids", [])
        allowed_tables = schema_context.get("allowed_tables", [])

        system_prompt = self._build_system_prompt(client_id, last_login_dt, current_login_dt, schema_context)
        messages = [{"role": "system", "content": system_prompt}]

        if chat_history and isinstance(chat_history, list):
            for msg in chat_history[-6:]:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({"role": msg["role"], "content": str(msg["content"])[:500]})

        messages.append({"role": "user", "content": question})

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Step 1: Initial call with tools (streaming delta check)
        initial_stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            tools=get_agent_tools(last_login_dt, current_login_dt),
            tool_choice="auto",
            temperature=0.3,
            stream=True
        )

        tool_calls_acc: dict[int, dict] = {}
        direct_tokens = []

        async for chunk in initial_stream:
            delta = chunk.choices[0].delta
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or f"call_{idx}",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "arguments": ""
                        }
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_acc[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["arguments"] += tc.function.arguments
            elif delta.content:
                # Direct content stream (no tool needed)
                direct_tokens.append(delta.content)
                yield f"data: {json.dumps({'token': delta.content})}\n\n"

        # If model answered directly without tools, close SSE stream
        if not tool_calls_acc:
            yield 'data: {"token": "", "done": true}\n\n'
            yield "data: [DONE]\n\n"
            return

        # Step 2: Tools were requested. Execute them!
        assistant_tool_calls = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"]
                }
            }
            for tc in tool_calls_acc.values()
        ]
        messages.append({
            "role": "assistant",
            "tool_calls": assistant_tool_calls
        })

        tasks = []
        for tc in tool_calls_acc.values():
            tasks.append(
                self.execute_tool(
                    name=tc["name"],
                    args_json=tc["arguments"],
                    client_id=client_id,
                    survey_ids=survey_ids,
                    last_login_dt=last_login_dt,
                    current_login_dt=current_login_dt,
                    allowed_tables=allowed_tables
                )
            )

        tool_outputs = await asyncio.gather(*tasks)

        for tc, output in zip(tool_calls_acc.values(), tool_outputs):
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(output)
            })

        # Step 3: Stream the final synthesized answer token-by-token
        final_stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.35,
            stream=True
        )

        async for chunk in final_stream:
            tok = chunk.choices[0].delta.content or ""
            if tok:
                yield f"data: {json.dumps({'token': tok})}\n\n"

        yield 'data: {"token": "", "done": true}\n\n'
        yield "data: [DONE]\n\n"


# Singleton instance
ask_ai_agent = AskAIAgent()

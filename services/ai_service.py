"""
AI Summary Service — Executive briefing for login popup.
Uses last_login → now comparison (no week logic).
"""
import json
from datetime import datetime
from openai import OpenAI
from loguru import logger
from config import settings

def _fmt_num(val):
    if isinstance(val, (int, float)):
        return int(val) if val == int(val) else val
    try:
        f = float(val)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return val


def generate_ai_summary(nps_data: dict, demographics: list, critical_issues: list, survey_comparison: list, last_login_label: str, current_login_dt: datetime, html_format: bool = False) -> dict:
    hour = current_login_dt.hour
    if 5 <= hour < 12:
        greeting = "Good Morning"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using rule-based summary.")
        return _fallback_summary(nps_data, demographics, critical_issues, survey_comparison, last_login_label, current_login_dt, html_format)

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        top_gainers   = [d for d in demographics if d.get("trend") == "up"][:3]
        top_decliners = [d for d in demographics if d.get("trend") == "down"][:3]
        top_issues = []
        if critical_issues:
            global_sample_count = 0
            for theme_group in critical_issues:
                theme_sample_count = 0
                for s in theme_group.get("samples", []):
                    if theme_sample_count >= 10 or global_sample_count >= 50:
                        break
                    loc_parts = []
                    for k, v in s.get("loc_data", {}).items():
                        if v and v != "Unknown":
                            loc_parts.append(f"{k}:{v}")
                    loc_str = ", ".join(loc_parts) or "Unknown Location"
                    churn_flag = " [CHURN RISK DETECTED BY DATABASE]" if s.get("churn_intent") else ""
                    top_issues.append(f"Verbatim: \"{s.get('verbatim', '')}\" ({loc_str}){churn_flag}")
                    theme_sample_count += 1
                    global_sample_count += 1
                if global_sample_count >= 50:
                    break
        
        top_survey_gainers = [s for s in survey_comparison if s.get("trend") == "up"][:2]
        top_survey_decliners = [s for s in survey_comparison if s.get("trend") == "down"][:2]
        delta         = _fmt_num(nps_data.get("delta", 0) or 0)
        trend_word    = "improved" if delta >= 0 else "declined"

        period_label = nps_data.get('current_period_label', f'since {last_login_label}')

        html_instruction = ""
        if html_format:
            html_instruction = """You MUST format the summary using clean HTML. 
If there is no change in NPS and no significant data, output a simple message like: <p>I have analyzed the changes since your last visit.</p><p>Overall NPS remains steady at <strong>[NPS]</strong>.</p>
Otherwise, provide a narrative summary wrapped in <p> tags instead of bullet points. Use <strong> tags for key metrics and area names.
Example structure:
<p>I have analyzed the changes since your last visit.</p>
<p>The good news is that overall NPS has improved by <strong>[Points]</strong> points, bringing the current score to <strong>[NPS]</strong>.</p>
<p><strong>[Strongest Region]</strong> is leading the turnaround, posting a strong <strong>[Gain]</strong> points improvement and setting the benchmark for customer experience performance.</p>
<p>However, <strong>[Declining Region]</strong> requires attention, with NPS declining by <strong>[Decline]</strong> points, making it the largest contributor to recent negative movement.</p>
<p>The top themes driving dissatisfaction remain <strong>[Themes]</strong>. [If churn risk: These issues are also associated with customers showing early signs of churn risk.]</p>
<p>If addressed promptly, the current recovery momentum can be accelerated while reducing attrition risk in vulnerable segments.</p>
Adjust the tone appropriately if the overall NPS has declined instead of improved. Do not use unordered lists (<ul> or <li>).
Format numbers cleanly: if a decimal value ends in .0, omit the decimal entirely (e.g., use 100 instead of 100.0). Never use hyphens between a number and the word "point" (e.g., use "100 points" instead of "100-points").
CRITICAL: Do NOT output any newline characters (\\n) in the JSON strings. Use <br> if you need a line break."""

        context = f"""
You are an analyst for a CX platform (SurveyCXM).
Generate a concise executive summary for a login popup.
Be specific, data-driven, and action-oriented. Professional but conversational.
Always explicitly mention that this data is for the period: {period_label}.

DATA FOR PERIOD ({period_label}):
- NPS: {_fmt_num(nps_data.get('current', 0))} (was {_fmt_num(nps_data.get('previous', 0))}, {'+' if delta >= 0 else ''}{delta} pts, {trend_word})
- Responses this period: {nps_data.get('total_responses', 0)} (was {nps_data.get('prev_total_responses', 0)})
- Promoters: {_fmt_num(nps_data.get('promoters_pct', 0))}% | Passives: {_fmt_num(nps_data.get('passives_pct', 0))}% | Detractors: {_fmt_num(nps_data.get('detractors_pct', 0))}%

TOP IMPROVING AREAS (in this period):
{chr(10).join([f"- {d['name']} ({d['type']}): NPS {_fmt_num(d['current_nps'])} ({'+' if float(d.get('delta',0)) >= 0 else ''}{_fmt_num(d['delta'])} pts)" for d in top_gainers]) or "None significant"}

TOP DECLINING AREAS (in this period):
{chr(10).join([f"- {d['name']} ({d['type']}): NPS {_fmt_num(d['current_nps'])} ({_fmt_num(d['delta'])} pts)" for d in top_decliners]) or "None significant"}

CRITICAL CUSTOMER ISSUES (raw voice of customer in this period):
{chr(10).join([f"- {issue}" for issue in top_issues]) or "No critical issues flagged"}

Provide JSON with:
- "summary": 3-4 paragraphs, highly impressive executive briefing tone. You MUST start the summary exactly like this: "<p>I have analyzed the changes since your last visit.</p>". Follow it with narrative paragraphs describing the overall NPS movement, the strongest area gain, the worst decline that needs immediate attention, and the top customer concerns (analyze the provided verbatims to determine 2-3 themes yourself). Conclude with a forward-looking statement. If any of the verbatims indicate CHURN RISK, mention it in the sentence about customer concerns. Only include areas or concerns if they are actually present in the data. {html_instruction}
- "key_points": exactly 5 bullet strings, each under 15 words
- "critical_vocs": exactly 5 most critical verbatim quotes representing the analyzed themes (or all available if less than 5) with their location data, extracted from the CRITICAL CUSTOMER ISSUES section. Format as an array of objects: {{"verbatim": "exact quote", "extra_info": "Label1:Value1, Label2:Value2"}}. Omit extra_info if location data is not provided.
"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": context}],
            temperature=0.35,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content
        try:
            result = json.loads(raw_content, strict=False)
        except json.JSONDecodeError:
            # Fallback cleanup for unescaped control characters
            clean_content = raw_content.replace("\n", " ").replace("\r", "")
            result = json.loads(clean_content, strict=False)
        summary_text = result.get("summary", "")
        if html_format:
            summary_text = summary_text.replace("\n", "<br>")
            
        return {
            "summary":       summary_text,
            "key_points":    result.get("key_points", []),
            "critical_vocs": result.get("critical_vocs", []),
        }

    except Exception as e:
        logger.error(f"AI summary error: {e}")
        return _fallback_summary(nps_data, demographics, critical_issues, survey_comparison, last_login_label, current_login_dt, html_format)


def _fallback_summary(nps_data: dict, demographics: list, critical_issues: list, survey_comparison: list, last_login_label: str, current_login_dt: datetime, html_format: bool = False) -> dict:
    delta      = _fmt_num(nps_data.get("delta", 0) or 0)
    current    = _fmt_num(nps_data.get("current", 0) or 0)
    trend_word = "improved" if delta >= 0 else "declined"
    top_gainer   = next((d for d in demographics if d.get("trend") == "up"),   None)
    top_decliner = next((d for d in demographics if d.get("trend") == "down"),  None)
    top_issue    = critical_issues[0]["issue"] if critical_issues else "response quality"

    period_label = nps_data.get('current_period_label', f'since {last_login_label}')

    hour = current_login_dt.hour
    if 5 <= hour < 12:
        greeting = "Good Morning"
    elif 12 <= hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    if html_format:
        if delta == 0 and not top_gainer and not top_decliner:
            summary = f"<p>I have analyzed the changes since your last visit.</p><p>Overall NPS remains steady at <strong>{current}</strong>.</p>"
        else:
            summary = f"<p>I have analyzed the changes since your last visit.</p>"
            summary += (
                f"<p>The {'good' if delta >= 0 else 'bad'} news is that overall NPS has {trend_word} by "
                f"<strong>{abs(delta)} points</strong>, bringing the current score to <strong>{current}</strong>.</p>"
            )
            if top_gainer:
                summary += (
                    f"<p><strong>{top_gainer['name']}</strong> is leading the turnaround, "
                    f"posting a strong <strong>{_fmt_num(abs(top_gainer['delta']))} points improvement</strong> and setting the benchmark for customer experience performance.</p>"
                )
            if top_decliner:
                summary += (
                    f"<p>However, <strong>{top_decliner['name']}</strong> requires attention, with NPS declining by <strong>{_fmt_num(abs(top_decliner['delta']))} points</strong>, making it the largest contributor to recent negative movement.</p>"
                )
            if top_issue and critical_issues:
                summary += f"<p>The top themes driving dissatisfaction remain <strong>{top_issue}</strong>.</p>"
            
            summary += "<p>If addressed promptly, the current recovery momentum can be accelerated while reducing attrition risk in vulnerable segments.</p>"
    else:
        summary = (
            f"Since your last login on {last_login_label}, your overall NPS has {trend_word} by "
            f"{abs(delta)} points, now at {current}. "
        )
        if top_gainer:
            summary += (
                f"{top_gainer['name']} ({top_gainer['type']}) is your strongest area "
                f"with a {top_gainer['delta']:+} pt gain. "
            )
        if top_decliner:
            summary += (
                f"{top_decliner['name']} shows a {top_decliner['delta']} pt decline and needs immediate attention. "
            )
        summary += f"Top customer concern: '{top_issue}' — addressing this will have maximum CX impact."

    key_points = [
        f"NPS {trend_word} {abs(delta)} pts to {current} since last login",
        f"Promoters {nps_data.get('promoters_pct', 0)}% | Detractors {nps_data.get('detractors_pct', 0)}%",
    ]
    if top_gainer:
        key_points.append(f"{top_gainer['name']} leads with {top_gainer['delta']:+} pt improvement")
    if top_decliner:
        key_points.append(f"{top_decliner['name']} declining — action needed")
    key_points.append(f"Top VOC issue: {top_issue}")

    critical_vocs = []
    if critical_issues and critical_issues[0].get("samples"):
        for s in critical_issues[0]["samples"][:5]:
            loc_parts = []
            for k, v in s.get("loc_data", {}).items():
                if v and v != "Unknown":
                    loc_parts.append(f"{k}:{v}")
            loc_str = ", ".join(loc_parts)
            voc = {
                "verbatim": s.get("verbatim", ""),
            }
            if loc_str:
                voc["extra_info"] = loc_str
            critical_vocs.append(voc)

    return {"summary": summary, "key_points": key_points[:5], "critical_vocs": critical_vocs}


def answer_user_question(
    nps_data: dict,
    demographics: list,
    critical_issues: list,
    question: str,
    survey_comparison: list = None,
    chat_history: list = None
) -> str:
    """Answers a specific user question using real-time database CX metrics."""
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using fallback answer.")
        return "I am currently offline."

    try:
        client = OpenAI(api_key=settings.openai_api_key)

        delta      = nps_data.get("delta", 0) or 0
        trend_word = "improved" if delta >= 0 else "declined"

        # Full demographic detail with previous NPS for drill-down
        demo_str = chr(10).join([
            f"- {d['name']} ({d['type']}): NPS {d['current_nps']} (was {d.get('previous_nps','?')}, Delta: {d['delta']:+} pts, Responses: {d['responses']}, Trend: {d.get('trend','?')})"
            for d in demographics
        ])

        # Individual survey breakdown (e.g. Customer Experience, Delivery Experience)
        surveys_str = ""
        if survey_comparison:
            surveys_str = chr(10).join([
                f"- Survey '{s['name']}' (ID {s['survey_id']}): {s['responses']} responses, {s.get('triggers', 0)} triggers/sent, Current NPS: {s['current_nps']} (was {s.get('previous_nps','?')}, Change: {s['delta']:+} pts)"
                for s in survey_comparison
            ])

        # Issues with verbatim samples and churn counts, including location data
        def format_sample(s):
            locs = [f"{k}:{v}" for k, v in s.get("loc_data", {}).items() if v and v != "Unknown"]
            loc_str = f" (Loc: {', '.join(locs)})" if locs else ""
            return f"{s.get('verbatim', '')}{loc_str}"

        issues_str = chr(10).join([
            f"- {i['issue']} | Count: {i['count']} | Severity: {i['severity']} | Churn/Critical Signals: {i.get('critical_count', 0)} | Samples: \"{' | '.join(format_sample(s) for s in i.get('samples', [])[:3])}\""
            for i in critical_issues
        ])

        # Pre-sort for quick AI reference
        top_gainers   = sorted([d for d in demographics if d.get("delta", 0) > 0], key=lambda x: -x["delta"])[:3]
        top_decliners = sorted([d for d in demographics if d.get("delta", 0) < 0], key=lambda x:  x["delta"])[:3]
        churn_signals = [i for i in critical_issues if i.get("critical_count", 0) > 0]

        role_header = """You are SurveyCXM AI — an intelligent, highly accurate CX Analyst and Performance Intelligence Assistant.
You have access to:
USER'S REAL-TIME CX DATABASE METRICS: Live NPS scores, response counts, demographic breakdowns, customer feedback verbatims, survey breakdown, and time period context."""

        app_section = """2. APPLICATION & HOW-TO QUESTIONS (FEATURE GUIDES & WORKFLOWS):
   - If the user asks how a platform feature or module works (e.g., survey creation methods, branching logic, multilingual setup, user roles, automated event triggers):
   - Respond cleanly in HTML: "<p>For platform feature guides, please use the Documentation Search assistant (/api/doc-rag-search).</p>"."""

        context = f"""
{role_header}

BEHAVIOR & RESPONSE GUIDELINES:
1. GREETINGS: If the user sends casual greetings (e.g., "hyy", "hello", "hi", "hey", "good morning"), respond concisely in a friendly chatbot manner: "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>".

{app_section}

3. REAL-TIME CX METRICS & DATA QUESTIONS:
   - If the user asks about their specific account metrics (e.g., current NPS, score changes, response counts, detractors, customer verbatim feedback, or region/store performance), answer directly and accurately using the REAL-TIME METRICS section below.
   - If asked about calculations (e.g. NPS formula: NPS = % Promoters - % Detractors), explain clearly using their exact figures.
   - DATE RANGE QUERIES: If the user asks about their data time period or date range (e.g., "what time period is this survey data from?"), answer directly: "<p>Your survey data covers the period: <strong>[TIME WINDOW]</strong>.</p>".
   - VALID CX QUESTIONS WITH NO RECORDED DATA: If the user asks a valid SurveyCXM data query about a specific survey, store, or region for which NO records exist in the current period, respond directly: "<p>No response data was recorded for <strong>[requested item/location/survey]</strong>.</p>".

4. HYBRID QUESTIONS (METRICS + WORKFLOWS):
   - If the user asks a question combining both analytical performance and platform configuration: summarize the live CX metrics, and if documentation is provided, include the configuration steps.

5. STRICT DOMAIN SCOPE & OUT-OF-SCOPE REJECTION:
   - You are EXCLUSIVELY a SurveyCXM Assistant.
   - Reject ONLY questions completely unrelated to SurveyCXM or CX (such as writing outside programming code, cooking recipes, general jokes, weather, sports, or general trivia).
   - For non-SurveyCXM topics, respond strictly with: "<p>I cannot assist with topics outside of SurveyCXM.</p>".
   - CRITICAL: NEVER return an out-of-scope rejection for ANY question about SurveyCXM features, surveys, creation, logic, triggers, multilingual, permissions, modules, or metrics!

6. CLEAN HTML OUTPUT ONLY:
   - Format your entire response using clean, interactive-ready HTML tags (<p>, <strong>, <ul>, <ol>, <li>, <table>, <code>).
   - Do NOT use Markdown formatting (no asterisks **, no markdown headers #, no markdown dashes -). Keep the output professional and easy to read in chat bubbles.

TIME WINDOW / DATE PERIOD: {nps_data.get('current_period_label', 'Since last login')}

NPS OVERVIEW:
- Current NPS    : {nps_data.get('current', 0)} (previous: {nps_data.get('previous', 0)}, change: {'+' if delta >= 0 else ''}{delta} pts — {trend_word})
- Total Responses: {nps_data.get('total_responses', 0)} (previous period: {nps_data.get('prev_total_responses', 0)})
- Promoters: {nps_data.get('promoters_pct', 0)}% | Passives: {nps_data.get('passives_pct', 0)}% | Detractors: {nps_data.get('detractors_pct', 0)}%

INDIVIDUAL SURVEY BREAKDOWN:
{surveys_str or "No individual survey data available."}

TOP IMPROVING AREAS:
{chr(10).join([f"- {d['name']} ({d['type']}): NPS {d['current_nps']} ({d['delta']:+} pts)" for d in top_gainers]) or "None"}

TOP DECLINING AREAS:
{chr(10).join([f"- {d['name']} ({d['type']}): NPS {d['current_nps']} ({d['delta']:+} pts)" for d in top_decliners]) or "None"}

ALL DEMOGRAPHICS (Region / State / City — full list):
{demo_str or "No demographic data available."}

CRITICAL CUSTOMER ISSUES (Voice of Customer with verbatim samples):
{issues_str or "No critical issues flagged."}

CHURN INTENT SIGNALS:
{chr(10).join([f"- {i['issue']}: {i['critical_count']} churn signals" for i in churn_signals]) or "No explicit churn signals in current period."}
"""

        messages = [{"role": "system", "content": context}]

        if chat_history and isinstance(chat_history, list):
            for msg in chat_history[-6:]:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    if msg["role"] in ["user", "assistant"]:
                        messages.append({"role": msg["role"], "content": str(msg["content"])})

        messages.append({"role": "user", "content": question})

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Ask AI error: {e}")
        return "An error occurred while processing your question. Please try again later."


def answer_rag_question(
    question: str,
    doc_context: list = None,
    chat_history: list = None
) -> str:
    """Answers user question using retrieved documentation context (dedicated RAG pipeline)."""
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        logger.warning("No valid OpenAI API key — using fallback answer.")
        return "<p>AI service is currently offline. Please verify API configuration.</p>"

    # 1. Immediate polite greeting response for standalone conversational greetings
    import re
    clean_q = question.strip().lower()
    normalized_q = re.sub(r'[^\w\s]', '', clean_q).strip()
    if normalized_q in [
        "hyy", "hello", "hi", "hey", "good morning", "good afternoon",
        "good evening", "greetings", "who are you", "what can you do", "help"
    ]:
        return "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>"

    doc_context = doc_context or []

    try:
        from services.rag_service import rag_service
        docs_str = rag_service.format_docs_for_prompt(doc_context)

        context = f"""
You are SurveyCXM AI — an intelligent, highly accurate SurveyCXM Application Specialist and Documentation Assistant.
Your primary role is to provide clear, actionable, step-by-step guidance on SurveyCXM features, modules, configurations, survey creation methods, branching logic, multilingual setup, user roles & permissions, automated event triggers, distributions, and workflows.

{docs_str if docs_str else "DOCUMENTATION KNOWLEDGE BASE STATUS: No matching documentation chunks found for this specific query."}

BEHAVIOR & RESPONSE GUIDELINES:
1. GREETINGS & COURTESY:
   - If the user opens with a greeting or asks who you are:
   - Respond concisely in a friendly chatbot manner: "<p>Hello! I am your SurveyCXM AI Assistant. How can I assist you today?</p>".

2. STRICT DOMAIN SCOPE & OUT-OF-SCOPE REJECTION:
   - You are EXCLUSIVELY a SurveyCXM Assistant.
   - If the query is completely unrelated to SurveyCXM or Customer Experience (such as general knowledge, cooking recipes, jokes, weather, sports, movies, outside programming languages, trivia, etc.):
   - You MUST respond strictly with: "<p>I cannot assist with topics outside of SurveyCXM.</p>".

3. SURVEYCXM QUERIES WITH NO RECORDED DOCUMENTATION:
   - If the user asks a valid question related to SurveyCXM (such as surveys, feedback, logic, triggers, modules, reports, settings, integrations) but the specific details or feature are NOT covered in the documentation above:
   - Do NOT invent procedures, fake URLs, or hallucinate settings.
   - Respond clearly in HTML: "<p>No documentation found for this feature. Please contact your administrator.</p>".

4. APPLICATION & HOW-TO QUESTIONS (FEATURE GUIDES & WORKFLOWS):
   - When the documentation is available in the references above:
   - Provide direct, clear, structured, and actionable step-by-step instructions.
   - Use clean HTML formatting:
     * Use <p> for introductory text, summaries, and concept explanations.
     * Use <ol> and <li> for sequential, ordered step-by-step procedures.
     * Use <ul> and <li> for feature highlights, options, bulleted lists, or prerequisites.
     * Use <strong> to highlight module names, tab titles, buttons, menus, and key terms (e.g., <strong>Survey Management</strong>, <strong>Tab 5: Logics & Conditional Branching</strong>).
     * Use <code> for variables, placeholders, or API fields (e.g., <code>{{FIRST_NAME}}</code>).
   - NEVER say you don't know or don't have access if the information is present in the documentation above.

5. CLEAN HTML OUTPUT ONLY:
   - Format your entire response using clean, interactive-ready HTML tags (<p>, <strong>, <ul>, <ol>, <li>, <table>, <code>).
   - Do NOT use Markdown formatting (no asterisks **, no markdown headers #, no markdown dashes -). Keep the output professional and easy to read in chat bubbles.
"""

        client = OpenAI(api_key=settings.openai_api_key)
        messages = [{"role": "system", "content": context}]

        if chat_history and isinstance(chat_history, list):
            for msg in chat_history[-6:]:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    if msg["role"] in ["user", "assistant"]:
                        messages.append({"role": msg["role"], "content": str(msg["content"])})

        messages.append({"role": "user", "content": question})

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Doc RAG question error: {e}")
        return "<p>An error occurred while processing your question. Please try again later.</p>"


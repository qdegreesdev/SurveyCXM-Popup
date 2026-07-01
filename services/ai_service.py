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

        result = json.loads(response.choices[0].message.content)
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


def answer_user_question(nps_data: dict, demographics: list, critical_issues: list, question: str) -> str:
    """Answers a specific user question using the popup data context with full drill-down detail."""
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

        # Issues with verbatim samples and churn counts
        issues_str = chr(10).join([
            f"- {i['issue']} | Count: {i['count']} | Severity: {i['severity']} | Churn/Critical Signals: {i.get('critical_count', 0)} | Samples: \"{' | '.join([s.get('verbatim', '') for s in i.get('samples', [])[:3]])}\""
            for i in critical_issues
        ])

        # Pre-sort for quick AI reference
        top_gainers   = sorted([d for d in demographics if d.get("delta", 0) > 0], key=lambda x: -x["delta"])[:3]
        top_decliners = sorted([d for d in demographics if d.get("delta", 0) < 0], key=lambda x:  x["delta"])[:3]
        churn_signals = [i for i in critical_issues if i.get("critical_count", 0) > 0]

        context = f"""
You are an intelligent AI analyst for a CX intelligence platform (SurveyCXM).
You have access to the user's REAL-TIME data from the database for their login window.
Answer in a detailed drill-down style — like a smart data analyst explaining findings.
You MUST dynamically format your entire response using standard HTML tags (e.g., <p>, <br>, <strong>, <ul>, <ol>, <li>). Do NOT use Markdown formatting (no asterisks **, no hyphens -).
Provide clear, concise, and complete answers directly addressing the user's question. 
When making comparisons, briefly state your methodology, then highlight ONLY the most relevant data points (e.g., the top 1 or 2 regions) rather than listing every single data point. 
Keep your response focused and readable, avoiding unnecessary length while ensuring the conclusion is well-explained.
Never say "I don't have data" if the context has relevant info.
For general/industry questions, combine context data with your broader knowledge.

PERIOD: Since the user's last login

NPS OVERVIEW:
- Current NPS    : {nps_data.get('current', 0)} (previous: {nps_data.get('previous', 0)}, change: {'+' if delta >= 0 else ''}{delta} pts — {trend_word})
- Total Responses: {nps_data.get('total_responses', 0)} (previous period: {nps_data.get('prev_total_responses', 0)})
- Promoters: {nps_data.get('promoters_pct', 0)}% | Passives: {nps_data.get('passives_pct', 0)}% | Detractors: {nps_data.get('detractors_pct', 0)}%

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

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": context},
                {"role": "user",   "content": question}
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Ask AI error: {e}")
        return "An error occurred while processing your question. Please try again later."

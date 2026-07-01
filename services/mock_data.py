"""
Mock data service — realistic sample data matching real schema structure.
Accepts last_login_dt and now_dt so labels match the last-login logic.
"""
from datetime import datetime, timedelta


def get_mock_popup_data(survey_id: str, last_login_dt: datetime = None, now_dt: datetime = None) -> dict:
    now          = now_dt or datetime.now()
    last_login   = last_login_dt or (now - timedelta(days=7))
    window       = now - last_login

    fmt        = "%d/%m/%Y"
    cur_label  = f"{last_login.strftime(fmt)} → {now.strftime(fmt)}"
    prev_start = last_login - window
    prev_label = f"{prev_start.strftime(fmt)} → {last_login.strftime(fmt)}"

    current_nps  = 47.5
    previous_nps = 41.2
    delta        = round(current_nps - previous_nps, 2)

    demographics = [
        {"type": "Region", "name": "North India",  "current_nps": 58.0,  "previous_nps": 49.0, "delta":  9.0,  "trend": "up",   "responses": 1240},
        {"type": "Region", "name": "South India",  "current_nps": 52.0,  "previous_nps": 55.0, "delta": -3.0,  "trend": "down", "responses":  980},
        {"type": "Region", "name": "West India",   "current_nps": 44.0,  "previous_nps": 38.0, "delta":  6.0,  "trend": "up",   "responses":  870},
        {"type": "Region", "name": "East India",   "current_nps": 31.0,  "previous_nps": 42.0, "delta": -11.0, "trend": "down", "responses":  620},
        {"type": "State",  "name": "Rajasthan",    "current_nps": 62.0,  "previous_nps": 51.0, "delta":  11.0, "trend": "up",   "responses":  540},
        {"type": "State",  "name": "Maharashtra",  "current_nps": 48.0,  "previous_nps": 52.0, "delta": -4.0,  "trend": "down", "responses":  730},
        {"type": "State",  "name": "Karnataka",    "current_nps": 55.0,  "previous_nps": 50.0, "delta":  5.0,  "trend": "up",   "responses":  490},
        {"type": "State",  "name": "West Bengal",  "current_nps": 28.0,  "previous_nps": 44.0, "delta": -16.0, "trend": "down", "responses":  310},
        {"type": "City",   "name": "Jaipur",       "current_nps": 65.0,  "previous_nps": 54.0, "delta":  11.0, "trend": "up",   "responses":  280},
        {"type": "City",   "name": "Mumbai",       "current_nps": 46.0,  "previous_nps": 53.0, "delta": -7.0,  "trend": "down", "responses":  390},
        {"type": "City",   "name": "Bangalore",    "current_nps": 57.0,  "previous_nps": 51.0, "delta":  6.0,  "trend": "up",   "responses":  260},
        {"type": "City",   "name": "Kolkata",      "current_nps": 25.0,  "previous_nps": 46.0, "delta": -21.0, "trend": "down", "responses":  180},
    ]

    critical_issues = [
        {"issue": "Churn Intent Detected",      "count":  87, "severity": "critical", "severity_score": 95, "critical_count":  87, "sample": "I am cancelling my subscription after this experience. Nobody helped me."},
        {"issue": "Escalation Language",        "count":  64, "severity": "critical", "severity_score": 95, "critical_count":  64, "sample": "I will escalate this to the consumer forum if not resolved in 24 hours."},
        {"issue": "Long Wait / Response Times", "count": 342, "severity": "high",     "severity_score": 85, "critical_count":  12, "sample": "Had to wait 45 minutes before anyone picked up my call."},
        {"issue": "App / Platform Issues",      "count": 197, "severity": "high",     "severity_score": 85, "critical_count":   8, "sample": "The app crashes every time I try to check my policy status."},
        {"issue": "Complaint Signals",          "count": 143, "severity": "high",     "severity_score": 85, "critical_count": 143, "sample": "I filed a complaint but received zero acknowledgement for 5 days."},
        {"issue": "Billing & Payment Errors",   "count": 121, "severity": "medium",   "severity_score": 70, "critical_count":   0, "sample": "Charged twice for the same month. Refund still pending after 2 weeks."},
    ]

    survey_comparison = [
        {
            "survey_id": 101,
            "name": "Post-Purchase Experience",
            "current_nps": 65.5,
            "previous_nps": 50.0,
            "delta": 15.5,
            "trend": "up",
            "responses": 1200
        },
        {
            "survey_id": 102,
            "name": "Customer Support Interaction",
            "current_nps": 30.0,
            "previous_nps": 42.0,
            "delta": -12.0,
            "trend": "down",
            "responses": 850
        },
        {
            "survey_id": 103,
            "name": "Website Usability",
            "current_nps": 45.0,
            "previous_nps": 43.5,
            "delta": 1.5,
            "trend": "up",
            "responses": 2100
        }
    ]

    return {
        "survey_id":             survey_id,
        "last_login":            last_login.strftime("%b %d, %Y %I:%M %p"),
        "data_as_of":            now.strftime("%b %d, %Y %I:%M %p"),
        "current_period_label":  cur_label,
        "previous_period_label": prev_label,
        "nps": {
            "current":              current_nps,
            "previous":             previous_nps,
            "delta":                delta,
            "trend":                "up" if delta >= 0 else "down",
            "total_responses":      3710,
            "prev_total_responses": 3240,
            "promoters_pct":        58.0,
            "passives_pct":         25.0,
            "detractors_pct":       17.0,
            "prev_promoters_pct":   51.0,
            "prev_passives_pct":    28.0,
            "prev_detractors_pct":  21.0,
            "current_period_label":  cur_label,
            "previous_period_label": prev_label,
        },
        "demographics":    demographics,
        "survey_comparison": survey_comparison,
        "critical_issues": critical_issues,
        "ai_summary":      None,
        "key_points":      [],
        "is_mock":         True,
    }

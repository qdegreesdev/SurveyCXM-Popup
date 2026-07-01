from datetime import datetime, timedelta
from loguru import logger
from config import settings

_DEFAULT_LAST_LOGIN_HOURS = 24 * 7   # fallback: 7 days ago if not supplied

def parse_datetime(dt_str: str | None, default_offset_hours: int | None = None, is_end_date: bool = False) -> datetime:
    """Parse ISO or custom format date strings (like DD/MM/YYYY, YYYY-MM-DD). Falls back to offset or now."""
    parsed_dt = None
    if dt_str:
        dt_str = dt_str.strip()
        try:
            parsed_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        if not parsed_dt:
            formats = [
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %I:%M %p",
                "%d/%m/%Y",
                "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y %I:%M %p",
                "%d-%m-%Y",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]
            for fmt in formats:
                try:
                    parsed_dt = datetime.strptime(dt_str, fmt)
                    break
                except Exception:
                    pass

    if not parsed_dt:
        if default_offset_hours is not None:
            parsed_dt = datetime.now() - timedelta(hours=default_offset_hours)
        else:
            parsed_dt = datetime.now()
            
    # If this is the end of a date range and the user only supplied a date (00:00:00), 
    # push it to the end of the day so it includes all events on that day.
    if is_end_date and parsed_dt.hour == 0 and parsed_dt.minute == 0 and parsed_dt.second == 0:
        parsed_dt = parsed_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        
    return parsed_dt


def aggregate_issues(records: list[dict]) -> list[dict]:
    """Group voc_alert rows by theme and produce ranked issue list."""
    from collections import defaultdict
    theme_map: dict[str, list] = defaultdict(list)
    for r in records:
        theme_map[r["theme"]].append(r)

    result = []
    for theme, items in theme_map.items():
        count          = len(items)
        critical_count = sum(1 for i in items if i.get("churn_intent"))
        max_severity   = max((i["severity_score"] for i in items), default=70)
        
        samples = []
        for i in items:
            if i.get("verbatim"):
                loc_data = {}
                for x in [1, 2, 3, 4]:
                    if i.get(f"f{x}_val"):
                        loc_data[i.get(f"f{x}_label", f"Level {x}")] = i[f"f{x}_val"]
                samples.append({
                    "verbatim": i.get("verbatim", "")[:200],
                    "loc_data": loc_data,
                    "severity_score": i.get("severity_score", 80),
                    "churn_intent": i.get("churn_intent", False)
                })

        severity = "critical" if max_severity >= 90 else ("high" if max_severity >= 80 else "medium")

        result.append({
            "issue":          theme,
            "count":          count,
            "severity":       severity,
            "severity_score": max_severity,
            "critical_count": critical_count,
            "sample":         samples[0]["verbatim"] if samples else "",
            "samples":        samples,
            "loc_data":       samples[0]["loc_data"] if samples else {}
        })

    result.sort(key=lambda x: (-x["severity_score"], -x["count"]))
    return result[:6]


def mock_with_ai(survey_id: str, last_login_dt: datetime, current_login_dt: datetime, last_login_label: str, client_id: int = 1, error: str = "") -> dict:
    from services.mock_data import get_mock_popup_data
    from services.ai_service import generate_ai_summary
    mock = get_mock_popup_data(survey_id, last_login_dt, current_login_dt)
    mock["client_id"] = client_id
    mock["last_login_date"] = last_login_dt.isoformat()
    mock["current_login_date"] = current_login_dt.isoformat()
    mock.pop("survey_id", None)
    mock.pop("last_login", None)
    mock.pop("data_as_of", None)
    ai = generate_ai_summary(
        mock["nps"], 
        mock["demographics"], 
        mock["critical_issues"], 
        mock.get("survey_comparison", []),
        last_login_label, 
        current_login_dt
    )
    mock["ai_summary"]    = ai.get("summary", "")
    mock["key_points"]    = ai.get("key_points", [])
    mock["top_alert_VOC"] = ai.get("critical_vocs", [])
    if error:
        mock["error"] = error
    return mock

"""
Demographic Service — breaks NPS down by Region → State → City.
Shows both gainers and decliners since last login.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from loguru import logger
from config import settings
from datetime import datetime, timedelta


def _calc_nps_from_rows(rows) -> float:
    scores = [r[0] for r in rows if r[0] is not None]
    if not scores:
        return 0.0
    total = len(scores)
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return round(((promoters - detractors) / total) * 100, 1)


def get_demographic_breakdown(db: Session, last_login: datetime, now: datetime) -> list:
    """
    Returns a list of demographic entries with current/previous NPS and delta.
    Covers Region, State, and City dimensions.
    """
    t = settings.nps_table
    score_col = settings.nps_score_col
    date_col = settings.nps_date_col
    region_col = settings.nps_region_col
    state_col = settings.nps_state_col
    city_col = settings.nps_city_col

    window_days = (now - last_login).days or 7
    prev_start = last_login - timedelta(days=window_days)

    results = []

    for dim_type, dim_col in [("region", region_col), ("state", state_col), ("city", city_col)]:
        try:
            # Get distinct dimension values
            q_dims = text(f"SELECT DISTINCT {dim_col} FROM {t} WHERE {dim_col} IS NOT NULL AND {dim_col} != ''")
            dim_values = [r[0] for r in db.execute(q_dims).fetchall()]

            for dim_val in dim_values:
                # Current window scores
                q = text(f"""
                    SELECT {score_col} FROM {t}
                    WHERE {dim_col} = :val AND {date_col} BETWEEN :start AND :end
                """)
                cur_rows = db.execute(q, {"val": dim_val, "start": last_login, "end": now}).fetchall()
                prev_rows = db.execute(q, {"val": dim_val, "start": prev_start, "end": last_login}).fetchall()

                current_nps = _calc_nps_from_rows(cur_rows)
                previous_nps = _calc_nps_from_rows(prev_rows)
                delta = round(current_nps - previous_nps, 1)

                results.append({
                    "type": dim_type,
                    "name": dim_val,
                    "current_nps": current_nps,
                    "previous_nps": previous_nps,
                    "delta": delta,
                    "trend": "up" if delta >= 0 else "down",
                    "responses": len(cur_rows),
                })
        except Exception as e:
            logger.error(f"Demographic service error for {dim_type}: {e}")
            continue

    # Sort: biggest movers first within each type
    results.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return results

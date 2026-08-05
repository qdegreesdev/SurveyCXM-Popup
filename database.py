"""
Database Service

Fetches real-time data from MySQL database for the SurveyCXM login popup.

DATE LOGIC:
  - current_period : last_login_dt  →  now          (what changed since you were here)
  - previous_period: (last_login_dt - window) → last_login_dt   (equal-length window before, for comparison)

Schema: dynamic per-survey tables (survey_responses_{id}, filter_hierarchy_{id}, voc_alerts, etc.)
"""

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings

logger = logging.getLogger(__name__)

DB_AVAILABLE = False
_db_service_instance = None


class DatabaseService:
    """Service to fetch real-time data from MySQL database."""

    def __init__(self):
        self.engine = None
        self._connect()

    # ── Connection management ────────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            from sqlalchemy import create_engine
            db_url = f"mysql+pymysql://{settings.survey_db_user}:{settings.survey_db_password}@{settings.survey_db_host}:{settings.survey_db_port}/{settings.survey_db_name}?charset=utf8mb4"
            self.engine = create_engine(
                db_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            logger.info(f"✅ MySQL pool created — host={settings.survey_db_host}, db={settings.survey_db_name}")
        except Exception as e:
            logger.error(f"❌ Database pool creation error: {e}")
            self.engine = None

    def _ensure_connection(self) -> bool:
        if self.engine is None:
            self._connect()
        return self.engine is not None

    @contextmanager
    def _cursor(self):
        if not self._ensure_connection():
            raise RuntimeError("No database connection available")
        with self.engine.raw_connection() as conn:
            try:
                cursor = conn.cursor(DictCursor)
                yield cursor
            finally:
                cursor.close()

    def _execute_query(self, query: str, params: tuple = ()) -> list[dict]:
        normalized_params: tuple = ()
        try:
            if params is None:
                normalized_params = ()
            elif isinstance(params, tuple):
                normalized_params = params
            elif isinstance(params, list):
                normalized_params = tuple(params)
            else:
                normalized_params = (params,)
        except Exception:
            normalized_params = ()

        if isinstance(normalized_params, (str, bytes)):
            normalized_params = (normalized_params,)

        try:
            with self._cursor() as cursor:
                cursor.execute(query, normalized_params)
                return cursor.fetchall()
        except RuntimeError:
            return []
        except Exception as e:
            if "Unknown column" in str(e):
                # Suppress spam for expected missing columns in dynamic survey tables
                pass
            else:
                logger.error(f"Query error: {e} | preview: {query[:120]}")
            return []

    @staticmethod
    def _safe_slug(slug: str) -> str:
        return f"`{slug.strip('`')}`"

    @staticmethod
    def _to_date(val) -> date:
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()

    # ── Connection test ──────────────────────────────────────────────────────

    def test_connection(self) -> dict[str, Any]:
        try:
            results = self._execute_query("SELECT 1 AS ok")
            if results:
                return {"connected": True, "database": settings.survey_db_name, "host": settings.survey_db_host}
            return {"connected": False, "error": "Empty result from SELECT 1"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    # ── Schema helpers ───────────────────────────────────────────────────────

    def _get_nps_slug(self, survey_id: int) -> str | None:
        result = self._execute_query(
            """
            SELECT slug FROM questions
            WHERE survey_id = %s AND type = 'nps'
            ORDER BY sort_order ASC LIMIT 1
            """,
            (survey_id,),
        )
        return result[0]["slug"] if result else None

    def _get_filter_labels(self, survey_id: int) -> dict[str, str]:
        result = self._execute_query(
            "SELECT filter_1, filter_2, filter_3, filter_4 FROM metadata_fields WHERE survey_id = %s LIMIT 1",
            (survey_id,),
        )
        if not result:
            return {"f1": "Region", "f2": "State", "f3": "City", "f4": "Branch"}
        return {
            "f1": result[0].get("filter_1") or "Region",
            "f2": result[0].get("filter_2") or "State",
            "f3": result[0].get("filter_3") or "City",
            "f4": result[0].get("filter_4") or "Branch",
        }

    def _check_table_exists(self, table_name: str) -> bool:
        result = self._execute_query(
            """
            SELECT COUNT(*) AS cnt FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            """,
            (settings.survey_db_name, table_name),
        )
        if result and result[0]["cnt"] > 0:
            return True
        try:
            rows = self._execute_query(f"SHOW TABLES LIKE '{table_name}'")
            return bool(rows)
        except Exception:
            return False

    # ── NPS helpers ──────────────────────────────────────────────────────────

    def _get_nps_scores_for_range(
        self,
        survey_id: int,
        slug: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        responses_table = f"survey_responses_{survey_id}"
        safe_col = self._safe_slug(slug)

        query = f"""
            SELECT
                sr.{safe_col}  AS score,
                sr.created_at
            FROM {responses_table} sr
            WHERE sr.survey_id = %s
              AND sr.{safe_col} IS NOT NULL
              AND sr.created_at >= %s
              AND sr.created_at  < %s
        """
        return self._execute_query(query, (survey_id, start_dt, end_dt))

    @staticmethod
    def _calculate_nps(scores: list[dict]) -> tuple[float, float, float, float]:
        if not scores:
            return 0.0, 0.0, 0.0, 0.0

        def to_float(val) -> float | None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        scores_float = [s for s in (to_float(r["score"]) for r in scores) if s is not None]
        total = len(scores_float)
        if total == 0:
            return 0.0, 0.0, 0.0, 0.0

        promoters  = sum(1 for s in scores_float if s >= 9)
        passives   = sum(1 for s in scores_float if 7 <= s <= 8)
        detractors = sum(1 for s in scores_float if s <= 6)

        nps           = round(((promoters - detractors) / total) * 100, 2)
        promoter_pct  = round((promoters  / total) * 100, 2)
        passive_pct   = round((passives   / total) * 100, 2)
        detractor_pct = round((detractors / total) * 100, 2)

        return nps, promoter_pct, passive_pct, detractor_pct

    # ── Date helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_periods(last_login_dt: datetime, now_dt: datetime) -> dict:
        """
        Build current and previous period date ranges from last login.

        current_period  : last_login_dt → now_dt
        previous_period : (last_login_dt - window) → last_login_dt
        window          : same duration as current period (so comparison is fair)
        """
        window = now_dt - last_login_dt
        if window.total_seconds() < 3600:          # guard: min 1 hour window
            window = timedelta(hours=1)

        prev_start = last_login_dt - window
        prev_end   = last_login_dt

        return {
            "cur_start":  last_login_dt,
            "cur_end":    now_dt,
            "prev_start": prev_start,
            "prev_end":   prev_end,
        }

    @staticmethod
    def _format_period_label(start: datetime, end: datetime) -> str:
        """Human-readable label e.g. '27/05/2026 → 03/06/2026'"""
        fmt = "%d/%m/%Y"
        return f"{start.strftime(fmt)} → {end.strftime(fmt)}"

    # ── Public data methods ──────────────────────────────────────────────────

    def get_nps_data(self, survey_id: int, last_login_dt: datetime, now_dt: datetime) -> dict[str, Any]:
        """
        NPS comparison: last_login → now  vs  equal window before last_login.
        """
        nps_slug = self._get_nps_slug(survey_id)
        if not nps_slug:
            logger.warning(f"No NPS slug found for survey {survey_id}")
            return {}

        p = self._build_periods(last_login_dt, now_dt)

        cur_scores  = self._get_nps_scores_for_range(survey_id, nps_slug, p["cur_start"],  p["cur_end"])
        prev_scores = self._get_nps_scores_for_range(survey_id, nps_slug, p["prev_start"], p["prev_end"])

        cur_nps,  cur_promo,  cur_passive,  cur_det  = self._calculate_nps(cur_scores)
        prev_nps, prev_promo, prev_passive, prev_det = self._calculate_nps(prev_scores)

        delta = round(cur_nps - prev_nps, 2)

        logger.debug(
            f"NPS — current: {cur_nps} ({len(cur_scores)} resp) | "
            f"previous: {prev_nps} ({len(prev_scores)} resp) | delta: {delta}"
        )

        return {
            "current":              cur_nps,
            "previous":             prev_nps,
            "delta":                delta,
            "trend":                "up" if delta >= 0 else "down",
            "total_responses":      len(cur_scores),
            "prev_total_responses": len(prev_scores),
            "promoters_pct":        cur_promo,
            "passives_pct":         cur_passive,
            "detractors_pct":       cur_det,
            "prev_promoters_pct":   prev_promo,
            "prev_passives_pct":    prev_passive,
            "prev_detractors_pct":  prev_det,
            "current_period_label": self._format_period_label(p["cur_start"],  p["cur_end"]),
            "previous_period_label":self._format_period_label(p["prev_start"], p["prev_end"]),
            # keep internals for drilldown
            "_cur_start":  p["cur_start"].isoformat(),
            "_cur_end":    p["cur_end"].isoformat(),
            "_prev_start": p["prev_start"].isoformat(),
            "_prev_end":   p["prev_end"].isoformat(),
            "_slug":       nps_slug,
        }

    def get_demographic_breakdown(
        self,
        survey_id: int,
        last_login_dt: datetime,
        now_dt: datetime,
    ) -> list[dict]:
        """
        NPS delta (current vs previous) broken down by Region → State → City.
        """
        p = self._build_periods(last_login_dt, now_dt)
        filter_labels = self._get_filter_labels(survey_id)
        results = []

        for dimension, label_key in [("region", "f1"), ("state", "f2"), ("city", "f3")]:
            rows = self._get_nps_drilldown(survey_id, dimension, p)
            label = filter_labels.get(label_key, dimension.title())
            for row in rows:
                cur_nps  = row["cur"]["nps"]
                prev_nps = row["prev"]["nps"]
                delta    = round(cur_nps - prev_nps, 2)
                results.append({
                    "type":         label,
                    "name":         row["name"],
                    "current_nps":  cur_nps,
                    "previous_nps": prev_nps,
                    "delta":        delta,
                    "trend":        "up" if delta >= 0 else "down",
                    "responses":    row["cur"]["count"],
                })

        results.sort(key=lambda x: abs(x["delta"]), reverse=True)
        return results

    def _get_nps_drilldown(self, survey_id: int, dimension: str, p: dict) -> list[dict]:
        """
        Single-query NPS drilldown using current vs previous period.
        """
        nps_slug = self._get_nps_slug(survey_id)
        if not nps_slug:
            return []

        responses_table = f"survey_responses_{survey_id}"
        nr_table        = f"survey_responses_nr_{survey_id}"
        fh_table        = f"filter_hierarchy_{survey_id}"
        safe_col        = self._safe_slug(nps_slug)

        dim_map = {
            "region": ("nr.f1", 1),
            "state":  ("nr.f2", 2),
            "city":   ("nr.f3", 3),
        }
        field, level = dim_map.get(dimension.lower(), ("nr.f1", 1))

        cur_start  = p["cur_start"]
        cur_end    = p["cur_end"]
        prev_start = p["prev_start"]
        prev_end   = p["prev_end"]

        rows = self._execute_query(
            f"""
            SELECT
                fh.value AS name,
                -- current period (last_login → now)
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s THEN 1 END)                                             AS cur_count,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} >= 9        THEN 1 END)               AS cur_promoters,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} BETWEEN 7 AND 8 THEN 1 END)           AS cur_passives,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} <= 6        THEN 1 END)               AS cur_detractors,
                -- previous period (equal window before last_login)
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s THEN 1 END)                                             AS prev_count,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} >= 9        THEN 1 END)               AS prev_promoters,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} BETWEEN 7 AND 8 THEN 1 END)           AS prev_passives,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} <= 6        THEN 1 END)               AS prev_detractors
            FROM {responses_table} sr
            INNER JOIN {nr_table} nr  ON sr.survey_response = nr.id
            INNER JOIN {fh_table} fh  ON {field} = fh.id AND fh.level = %s
            WHERE sr.survey_id = %s
              AND sr.{safe_col} IS NOT NULL
              AND (
                  (sr.created_at >= %s AND sr.created_at < %s)
                  OR
                  (sr.created_at >= %s AND sr.created_at < %s)
              )
            GROUP BY fh.id, fh.value
            ORDER BY cur_count DESC
            LIMIT 20
            """,
            (
                # current period counters (4 sets × 2 params)
                cur_start, cur_end,
                cur_start, cur_end,
                cur_start, cur_end,
                cur_start, cur_end,
                # previous period counters (4 sets × 2 params)
                prev_start, prev_end,
                prev_start, prev_end,
                prev_start, prev_end,
                prev_start, prev_end,
                # level, survey_id
                level, survey_id,
                # WHERE date range
                cur_start, cur_end,
                prev_start, prev_end,
            ),
        )

        def _nps_stats(promoters, passives, detractors, total):
            if not total:
                return {"nps": 0.0, "promoter_pct": 0.0, "passive_pct": 0.0, "detractor_pct": 0.0}
            return {
                "nps":           round(((promoters - detractors) / total) * 100, 2),
                "promoter_pct":  round((promoters / total) * 100, 2),
                "passive_pct":   round((passives  / total) * 100, 2),
                "detractor_pct": round((detractors / total) * 100, 2),
            }

        result = []
        for r in rows:
            cur_total  = r["cur_count"]  or 0
            prev_total = r["prev_count"] or 0
            cur_stats  = _nps_stats(r["cur_promoters"],  r["cur_passives"],  r["cur_detractors"],  cur_total)
            prev_stats = _nps_stats(r["prev_promoters"], r["prev_passives"], r["prev_detractors"], prev_total)
            result.append({
                "name": r["name"],
                "cur":  {**cur_stats,  "count": cur_total},
                "prev": {**prev_stats, "count": prev_total},
            })
        return result

    def get_customer_voice_data(self, survey_id: int, last_login_dt: datetime, now_dt: datetime) -> dict[str, Any]:
        """
        High-severity negative voc_alerts created since last login.
        """
        if not self._check_table_exists("voc_alerts"):
            logger.warning(f"voc_alerts table not found for survey {survey_id}")
            return {"high_severity_records": []}

        nr_table = f"survey_responses_nr_{survey_id}"
        fh_table = f"filter_hierarchy_{survey_id}"
        labels = self._get_filter_labels(survey_id)

        col_rows = self._execute_query(f"SHOW COLUMNS FROM {nr_table}")
        existing_cols = {row['Field'].lower() for row in col_rows} if col_rows else set()

        select_cols = []
        join_clauses = []
        for i in range(1, 5):
            f_col = f"f{i}"
            if f_col in existing_cols:
                select_cols.append(f"fh{i}.value AS {f_col}_val")
                join_clauses.append(f"LEFT JOIN {fh_table} fh{i} ON nr.{f_col} = fh{i}.id AND fh{i}.level = {i}")
            else:
                select_cols.append(f"NULL AS {f_col}_val")

        select_str = ",\n                ".join(select_cols)
        join_str = "\n            ".join(join_clauses)

        rows = self._execute_query(
            f"""
            SELECT
                v.priority_level,
                v.category           AS theme,
                v.sub_category,
                v.customer_verbatim  AS verbatim,
                v.keyword,
                v.sentiment,
                v.is_critical,
                v.created_at,
                {select_str}
            FROM voc_alerts v
            LEFT JOIN {nr_table} nr ON v.survey_res_id = nr.id
            {join_str}
            WHERE v.survey_id = %s
              AND v.sentiment = 'Negative'
              AND v.created_at >= %s
              AND v.created_at  < %s
              AND (
                    LOWER(v.priority_level) IN ('high', 'critical', 'urgent', 'medium')
                    OR v.is_critical = 1
              )
            ORDER BY
                CASE LOWER(v.priority_level)
                    WHEN 'critical' THEN 1
                    WHEN 'urgent'   THEN 2
                    WHEN 'high'     THEN 3
                    WHEN 'medium'   THEN 4
                    ELSE 5
                END ASC,
                v.created_at DESC
            """,
            (survey_id, last_login_dt, now_dt),
        )

        priority_score_map = {"critical": 95, "urgent": 90, "high": 85, "medium": 70, "low": 50}
        critical_keyword_set = {"churn intent", "escalation language", "complaint signals", "abusive experience"}

        records = []
        print(f"DEBUG DB: Survey {survey_id} retrieved {len(rows)} raw rows.")
        for row in rows:
            priority       = (row.get("priority_level") or "").lower().strip()
            severity_score = priority_score_map.get(priority, 80)
            keyword_raw    = (row.get("keyword") or "").strip()
            keyword_lower  = keyword_raw.lower()
            has_critical   = any(ck in keyword_lower for ck in critical_keyword_set)
            is_critical    = priority == "critical" or bool(row.get("is_critical")) or has_critical
            if has_critical:
                severity_score = 95

            records.append({
                "severity_score": severity_score,
                "theme":          (row.get("theme") or "Unknown").strip() or "Unknown",
                "sub_category":   (row.get("sub_category") or "").strip(),
                "verbatim":       (row.get("verbatim") or "").strip()[:300],
                "f1_label":       labels["f1"],
                "f1_val":         (row.get("f1_val") or "").strip(),
                "f2_label":       labels["f2"],
                "f2_val":         (row.get("f2_val") or "").strip(),
                "f3_label":       labels["f3"],
                "f3_val":         (row.get("f3_val") or "").strip(),
                "f4_label":       labels["f4"],
                "f4_val":         (row.get("f4_val") or "").strip(),
                "keyword":        keyword_raw,
                "priority":       priority,
                "churn_intent":   is_critical,
            })

        return {"high_severity_records": records}

    def get_available_survey_ids(self, limit: int = 200) -> list[int]:
        if self._check_table_exists("surveys"):
            rows = self._execute_query(
                "SELECT id FROM surveys WHERE id IS NOT NULL ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            ids = []
            for r in rows:
                try:
                    ids.append(int(r.get("id")))
                except Exception:
                    continue
            return sorted(set(ids))

        rows = self._execute_query(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_name LIKE 'survey_responses_%'
            ORDER BY table_name DESC LIMIT %s
            """,
            (settings.survey_db_name, limit * 3),
        )
        ids_set: set[int] = set()
        for r in rows:
            name = r.get("table_name") or ""
            parts = name.split("survey_responses_")
            if len(parts) != 2:
                continue
            try:
                ids_set.add(int(parts[1]))
            except Exception:
                continue
        ids = sorted(ids_set)
        return ids[-limit:] if len(ids) > limit else ids

    def get_survey_ids_by_client(self, client_id: int) -> list[int]:
        """Query the surveys table to find all survey IDs for a given client_id."""
        if not self._check_table_exists("surveys"):
            logger.warning("surveys table does not exist")
            return []
        try:
            rows = self._execute_query("SELECT id FROM surveys WHERE client_id = %s", (client_id,))
            ids = [int(r["id"]) for r in rows if r.get("id") is not None]
            
            # Filter IDs by whether the corresponding response table actually exists
            valid_ids = []
            for sid in ids:
                if self._check_table_exists(f"survey_responses_{sid}"):
                    valid_ids.append(sid)
            return valid_ids
        except Exception as e:
            logger.warning(f"Error querying 'id' from surveys (column may not exist): {e}")
            try:
                rows = self._execute_query("SELECT survey_id FROM surveys WHERE client_id = %s", (client_id,))
                ids = [int(r["survey_id"]) for r in rows if r.get("survey_id") is not None]
                valid_ids = []
                for sid in ids:
                    if self._check_table_exists(f"survey_responses_{sid}"):
                        valid_ids.append(sid)
                return valid_ids
            except Exception as ex:
                logger.error(f"Error querying 'survey_id' from surveys: {ex}")
        return []


    def get_client_by_id(self, client_id: int) -> dict | None:
        """Query the clients table to validate the client and retrieve basic info."""
        if not self._check_table_exists("clients"):
            logger.warning("clients table does not exist")
            return None
        try:
            rows = self._execute_query("SELECT id, company_name FROM clients WHERE id = %s AND is_deleted = 0", (client_id,))
            if rows:
                return rows[0]
        except Exception as e:
            logger.error(f"Error querying client: {e}")
        return None

    def get_nps_data_for_surveys(self, survey_ids: list[int], last_login_dt: datetime, now_dt: datetime) -> dict[str, Any]:
        """
        NPS comparison aggregated across multiple surveys.
        """
        if not survey_ids:
            return {}

        p = self._build_periods(last_login_dt, now_dt)
        all_cur_scores = []
        all_prev_scores = []

        for survey_id in survey_ids:
            nps_slug = self._get_nps_slug(survey_id)
            if not nps_slug:
                continue
            cur_scores  = self._get_nps_scores_for_range(survey_id, nps_slug, p["cur_start"],  p["cur_end"])
            prev_scores = self._get_nps_scores_for_range(survey_id, nps_slug, p["prev_start"], p["prev_end"])
            all_cur_scores.extend(cur_scores)
            all_prev_scores.extend(prev_scores)

        if not all_cur_scores and not all_prev_scores:
            return {}

        cur_nps,  cur_promo,  cur_passive,  cur_det  = self._calculate_nps(all_cur_scores)
        prev_nps, prev_promo, prev_passive, prev_det = self._calculate_nps(all_prev_scores)

        delta = round(cur_nps - prev_nps, 2)

        return {
            "current":              cur_nps,
            "previous":             prev_nps,
            "delta":                delta,
            "trend":                "up" if delta >= 0 else "down",
            "total_responses":      len(all_cur_scores),
            "prev_total_responses": len(all_prev_scores),
            "promoters_pct":        cur_promo,
            "passives_pct":         cur_passive,
            "detractors_pct":       cur_det,
            "prev_promoters_pct":   prev_promo,
            "prev_passives_pct":    prev_passive,
            "prev_detractors_pct":  prev_det,
            "current_period_label": self._format_period_label(p["cur_start"],  p["cur_end"]),
            "previous_period_label":self._format_period_label(p["prev_start"], p["prev_end"]),
            "_cur_start":  p["cur_start"].isoformat(),
            "_cur_end":    p["cur_end"].isoformat(),
            "_prev_start": p["prev_start"].isoformat(),
            "_prev_end":   p["prev_end"].isoformat(),
        }

    def get_survey_comparison(self, survey_ids: list[int], last_login_dt: datetime, now_dt: datetime) -> list[dict]:
        """
        Compare individual surveys against each other for the given time period.
        """
        if not survey_ids:
            return []

        p = self._build_periods(last_login_dt, now_dt)
        results = []

        try:
            format_strings = ','.join(['%s'] * len(survey_ids))
            query = f"SELECT id, name FROM surveys WHERE id IN ({format_strings})"
            rows = self._execute_query(query, tuple(survey_ids))
            survey_names = {int(row["id"]): row["name"] for row in rows}
        except Exception as e:
            logger.warning(f"Failed to fetch survey names: {e}")
            survey_names = {}

        for survey_id in survey_ids:
            nps_slug = self._get_nps_slug(survey_id)
            if not nps_slug:
                continue
            
            cur_scores  = self._get_nps_scores_for_range(survey_id, nps_slug, p["cur_start"],  p["cur_end"])
            prev_scores = self._get_nps_scores_for_range(survey_id, nps_slug, p["prev_start"], p["prev_end"])
            
            cur_nps,  _, _, _ = self._calculate_nps(cur_scores)
            prev_nps, _, _, _ = self._calculate_nps(prev_scores)
            
            delta = round(cur_nps - prev_nps, 2)
            
            results.append({
                "survey_id": survey_id,
                "name": survey_names.get(survey_id, f"Survey #{survey_id}"),
                "current_nps": cur_nps,
                "previous_nps": prev_nps,
                "delta": delta,
                "trend": "up" if delta >= 0 else "down",
                "responses": len(cur_scores)
            })
            
        results.sort(key=lambda x: abs(x["delta"]), reverse=True)
        return results

    def _get_raw_nps_drilldown(self, survey_id: int, dimension: str, p: dict) -> list[dict]:
        nps_slug = self._get_nps_slug(survey_id)
        if not nps_slug:
            return []
        responses_table = f"survey_responses_{survey_id}"
        nr_table        = f"survey_responses_nr_{survey_id}"
        fh_table        = f"filter_hierarchy_{survey_id}"
        safe_col        = self._safe_slug(nps_slug)

        dim_map = {
            "region": ("nr.f1", 1),
            "state":  ("nr.f2", 2),
            "city":   ("nr.f3", 3),
        }
        field, level = dim_map.get(dimension.lower(), ("nr.f1", 1))

        cur_start  = p["cur_start"]
        cur_end    = p["cur_end"]
        prev_start = p["prev_start"]
        prev_end   = p["prev_end"]

        return self._execute_query(
            f"""
            SELECT
                fh.value AS name,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s THEN 1 END)                                             AS cur_count,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} >= 9        THEN 1 END)               AS cur_promoters,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} BETWEEN 7 AND 8 THEN 1 END)           AS cur_passives,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} <= 6        THEN 1 END)               AS cur_detractors,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s THEN 1 END)                                             AS prev_count,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} >= 9        THEN 1 END)               AS prev_promoters,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} BETWEEN 7 AND 8 THEN 1 END)           AS prev_passives,
                COUNT(CASE WHEN sr.created_at >= %s AND sr.created_at < %s AND sr.{safe_col} <= 6        THEN 1 END)               AS prev_detractors
            FROM {responses_table} sr
            INNER JOIN {nr_table} nr  ON sr.survey_response = nr.id
            INNER JOIN {fh_table} fh  ON {field} = fh.id AND fh.level = %s
            WHERE sr.survey_id = %s
              AND sr.{safe_col} IS NOT NULL
              AND (
                  (sr.created_at >= %s AND sr.created_at < %s)
                  OR
                  (sr.created_at >= %s AND sr.created_at < %s)
              )
            GROUP BY fh.id, fh.value
            ORDER BY cur_count DESC
            """,
            (
                cur_start, cur_end, cur_start, cur_end, cur_start, cur_end, cur_start, cur_end,
                prev_start, prev_end, prev_start, prev_end, prev_start, prev_end, prev_start, prev_end,
                level, survey_id, cur_start, cur_end, prev_start, prev_end,
            ),
        )

    def get_demographic_breakdown_for_surveys(
        self,
        survey_ids: list[int],
        last_login_dt: datetime,
        now_dt: datetime,
    ) -> list[dict]:
        if not survey_ids:
            return []

        p = self._build_periods(last_login_dt, now_dt)
        from collections import defaultdict

        agg_data = defaultdict(lambda: {
            "cur_count": 0, "cur_promoters": 0, "cur_passives": 0, "cur_detractors": 0,
            "prev_count": 0, "prev_promoters": 0, "prev_passives": 0, "prev_detractors": 0
        })

        for survey_id in survey_ids:
            filter_labels = self._get_filter_labels(survey_id)
            for dimension, label_key in [("region", "f1"), ("state", "f2"), ("city", "f3")]:
                label = filter_labels.get(label_key, dimension.title())
                rows = self._get_raw_nps_drilldown(survey_id, dimension, p)
                for r in rows:
                    key = (label, r["name"])
                    agg_data[key]["cur_count"]      += r["cur_count"] or 0
                    agg_data[key]["cur_promoters"]  += r["cur_promoters"] or 0
                    agg_data[key]["cur_passives"]   += r["cur_passives"] or 0
                    agg_data[key]["cur_detractors"] += r["cur_detractors"] or 0
                    agg_data[key]["prev_count"]     += r["prev_count"] or 0
                    agg_data[key]["prev_promoters"] += r["prev_promoters"] or 0
                    agg_data[key]["prev_passives"]  += r["prev_passives"] or 0
                    agg_data[key]["prev_detractors"]+= r["prev_detractors"] or 0

        def _nps_stats(promoters, passives, detractors, total):
            if not total:
                return {"nps": 0.0, "promoter_pct": 0.0, "passive_pct": 0.0, "detractor_pct": 0.0}
            return {
                "nps":           round(((promoters - detractors) / total) * 100, 2),
                "promoter_pct":  round((promoters / total) * 100, 2),
                "passive_pct":   round((passives  / total) * 100, 2),
                "detractor_pct": round((detractors / total) * 100, 2),
            }

        results = []
        for (label, name), counts in agg_data.items():
            cur_stats  = _nps_stats(counts["cur_promoters"], counts["cur_passives"], counts["cur_detractors"], counts["cur_count"])
            prev_stats = _nps_stats(counts["prev_promoters"], counts["prev_passives"], counts["prev_detractors"], counts["prev_count"])
            delta      = round(cur_stats["nps"] - prev_stats["nps"], 2)
            results.append({
                "type":         label,
                "name":         name,
                "current_nps":  cur_stats["nps"],
                "previous_nps": prev_stats["nps"],
                "delta":        delta,
                "trend":        "up" if delta >= 0 else "down",
                "responses":    counts["cur_count"],
            })

        results.sort(key=lambda x: abs(x["delta"]), reverse=True)
        return results

    def get_customer_voice_data_for_surveys(self, survey_ids: list[int], last_login_dt: datetime, now_dt: datetime) -> dict[str, Any]:
        all_records = []
        for survey_id in survey_ids:
            voice = self.get_customer_voice_data(survey_id, last_login_dt, now_dt)
            all_records.extend(voice.get("high_severity_records", []))
        return {"high_severity_records": all_records}

    def close(self) -> None:
        if self.engine:
            try:
                self.engine.dispose()
            except Exception as e:
                logger.warning(f"Error closing engine: {e}")
            finally:
                self.engine = None


# ── Module-level singleton ────────────────────────────────────────────────────
def get_db_service() -> DatabaseService | None:
    global _db_service_instance, DB_AVAILABLE
    if _db_service_instance is None:
        try:
            svc = DatabaseService()
            test = svc.test_connection()
            if test.get("connected"):
                _db_service_instance = svc
                DB_AVAILABLE = True
            else:
                logger.warning(f"⚠️  DB not available: {test.get('error')}. Using mock data.")
                DB_AVAILABLE = False
        except Exception as e:
            logger.warning(f"⚠️  DB init failed: {e}. Using mock data.")
            DB_AVAILABLE = False
    return _db_service_instance

def reset_db_service() -> None:
    """Clear the cached database service instance."""
    global _db_service_instance, DB_AVAILABLE
    if _db_service_instance:
        _db_service_instance.close()
    _db_service_instance = None
    DB_AVAILABLE = False
    logger.info("Database service cache cleared.")

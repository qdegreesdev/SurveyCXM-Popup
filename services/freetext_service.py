"""
Free-text Service — extracts critical issues from customer feedback comments.
Uses keyword clustering for fast results, with optional OpenAI topic extraction.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from loguru import logger
from config import settings
from datetime import datetime
from collections import Counter
import re


# Common issue keywords mapped to readable issue names
ISSUE_KEYWORDS = {
    "wait|waiting|hold|queue|slow|delayed|late|time": "Long Wait / Response Times",
    "rude|behavior|attitude|unprofessional|impolite|harsh": "Poor Agent Behavior",
    "crash|error|bug|not working|broken|fail|loading|freeze": "App / Platform Issues",
    "not resolved|unresolved|same issue|again|repeat|follow up": "Issue Not Resolved",
    "billing|charge|payment|overcharge|refund|invoice|fee": "Billing & Payment Errors",
    "no update|no communication|informed|notify|message": "Lack of Communication",
    "rude|staff|representative|executive|agent": "Staff Behavior",
    "policy|claim|insurance|coverage|terms": "Policy / Coverage Concern",
    "portal|website|login|access|password": "Portal / Access Issues",
    "callback|call back|return call|called back": "Callback Not Received",
}


def _cluster_issues(texts: list[str]) -> list[dict]:
    """Simple keyword-based clustering to identify top issues."""
    issue_counts = Counter()
    issue_samples = {}

    for text_val in texts:
        text_lower = text_val.lower()
        for pattern, issue_name in ISSUE_KEYWORDS.items():
            if re.search(pattern, text_lower):
                issue_counts[issue_name] += 1
                if issue_name not in issue_samples:
                    # Store first sample (truncated)
                    issue_samples[issue_name] = text_val[:150] + ("..." if len(text_val) > 150 else "")

    results = []
    for issue_name, count in issue_counts.most_common(6):
        total = len(texts)
        freq_pct = round((count / total) * 100) if total else 0
        if freq_pct >= 60:
            severity = "critical"
        elif freq_pct >= 35:
            severity = "high"
        else:
            severity = "medium"

        results.append({
            "issue": issue_name,
            "count": count,
            "severity": severity,
            "frequency_pct": freq_pct,
            "sample": issue_samples.get(issue_name, ""),
        })

    return results


def get_critical_issues(db: Session, last_login: datetime, now: datetime) -> list[dict]:
    """Fetch free-text comments and extract top critical issues."""
    try:
        t = settings.freetext_table
        text_col = settings.freetext_col
        date_col = settings.freetext_date_col

        q = text(f"""
            SELECT {text_col} FROM {t}
            WHERE {date_col} BETWEEN :start AND :end
              AND {text_col} IS NOT NULL
              AND LENGTH({text_col}) > 10
            LIMIT 2000
        """)
        rows = db.execute(q, {"start": last_login, "end": now}).fetchall()
        texts = [row[0] for row in rows if row[0]]

        if not texts:
            return []

        return _cluster_issues(texts)
    except Exception as e:
        logger.error(f"Free-text service error: {e}")
        raise

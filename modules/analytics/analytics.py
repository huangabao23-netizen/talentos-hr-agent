"""
Recruitment Data Review / Analytics Agent.
Aggregates screening records into digestible hiring analytics:
- Funnel analysis
- Time-to-X metrics (screen / interview / offer / hire)
- Monthly trend
- Source effectiveness
- Rejection reasons
- Score distribution
- Domain breakdown
"""

import logging
from datetime import date, timedelta
from typing import List, Optional, Dict, Any, Tuple

from models.schemas import (
    CandidateResult, ParsedJD, FunnelStage, ScreeningRecord,
)
from utils.db import (
    init_db, add_screening_record, list_screening_records, list_jd_records,
    funnel_summary, time_metrics, trend_by_month, source_effectiveness,
    rejection_reasons, score_distribution, domain_breakdown,
    result_to_screening,
)

logger = logging.getLogger(__name__)
init_db()


def log_screening_run(
    results: List[CandidateResult],
    jd: ParsedJD,
    source: str = "Manual",
) -> int:
    """
    Persist an entire screening run to the analytics DB.
    Returns count of records saved.
    """
    saved = 0
    for r in results:
        try:
            rec = result_to_screening(r, jd, source=source)
            add_screening_record(rec)
            saved += 1
        except Exception as e:
            logger.warning("Could not log screening for %s: %s",
                           r.profile.candidate_name, e)
    return saved


def overall_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Top-of-dashboard headline KPIs."""
    funnel = funnel_summary(from_date, to_date)
    tm = time_metrics(from_date, to_date)

    applied = (funnel.get("Applied", 0) + funnel.get("Screened", 0)
               + funnel.get("Interviewed", 0) + funnel.get("Offered", 0)
               + funnel.get("Hired", 0) + funnel.get("Rejected", 0))
    screened = funnel.get("Screened", 0) + funnel.get("Interviewed", 0) + funnel.get("Offered", 0) + funnel.get("Hired", 0)
    interviewed = funnel.get("Interviewed", 0) + funnel.get("Offered", 0) + funnel.get("Hired", 0)
    offered = funnel.get("Offered", 0) + funnel.get("Hired", 0)
    hired = funnel.get("Hired", 0)
    rejected = funnel.get("Rejected", 0)
    total_pipeline = applied + rejected

    def _safe_rate(num, den, default=0.0):
        return round(num / den * 100, 1) if den else default

    return {
        "total_records": total_pipeline,
        "applied": applied,
        "screened": screened,
        "interviewed": interviewed,
        "offered": offered,
        "hired": hired,
        "rejected": rejected,
        "screen_rate": _safe_rate(screened, total_pipeline),
        "interview_rate": _safe_rate(interviewed, screened),
        "offer_rate": _safe_rate(offered, interviewed),
        "accept_rate": _safe_rate(hired, offered),
        "overall_hire_rate": _safe_rate(hired, total_pipeline),
        "avg_days_to_screen": tm["avg_days_to_screen"],
        "avg_days_to_interview": tm["avg_days_to_interview"],
        "avg_days_to_offer": tm["avg_days_to_offer"],
        "avg_days_to_hire": tm["avg_days_to_hire"],
    }


def funnel_data_for_chart(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    job_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce funnel-stage names and counts for Plotly funnel chart."""
    f = funnel_summary(from_date, to_date, job_title)
    applied = sum(v for v in f.values())
    stages = [
        ("Applied",      applied),
        ("Screened",     f.get("Screened", 0) + f.get("Interviewed", 0) + f.get("Offered", 0) + f.get("Hired", 0)),
        ("Interviewed",  f.get("Interviewed", 0) + f.get("Offered", 0) + f.get("Hired", 0)),
        ("Offered",      f.get("Offered", 0) + f.get("Hired", 0)),
        ("Hired",        f.get("Hired", 0)),
    ]
    labels, values = zip(*stages)
    dropoffs = []
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        d = round((1 - (cur / prev)) * 100, 1) if prev else 0.0
        dropoffs.append(d)
    return {
        "labels": list(labels),
        "values": list(values),
        "dropoffs_pct": dropoffs,
    }


def monthly_trend(months: int = 6) -> List[Dict[str, Any]]:
    return trend_by_month(months)


def sources(limit: int = 8) -> List[Dict[str, Any]]:
    return source_effectiveness(limit)


def rejections(limit: int = 10) -> List[Tuple[str, int]]:
    return rejection_reasons(limit)


def score_histogram(bins: int = 10) -> List[Dict[str, Any]]:
    return score_distribution(bins)


def domains() -> List[Dict[str, Any]]:
    return domain_breakdown()


def open_jobs() -> List[Dict[str, Any]]:
    """Return JD records with progress % toward target hires."""
    out = []
    for j in list_jd_records(limit=100):
        progress = (
            round(j.total_hired / j.target_hires * 100, 1)
            if j.target_hires else 0.0
        )
        days_open = None
        today = date.today()
        end = j.closed_date or today
        days_open = (end - j.opened_date).days
        out.append({
            "id": j.id,
            "job_title": j.job_title,
            "domain": j.domain,
            "department": j.department,
            "seniority": j.seniority_level,
            "status": j.status,
            "opened_date": j.opened_date.isoformat(),
            "closed_date": j.closed_date.isoformat() if j.closed_date else "",
            "days_open": days_open,
            "applicants": j.total_applicants,
            "screened": j.total_screened,
            "interviewed": j.total_interviewed,
            "offered": j.total_offered,
            "hired": j.total_hired,
            "target": j.target_hires,
            "progress_pct": min(100.0, progress),
        })
    return out


def generate_insights() -> List[Dict[str, Any]]:
    """
    Rule-based insights from analytics data.
    Returns list of {severity, title, detail} for dashboard display.
    """
    insights: List[Dict[str, Any]] = []
    summary = overall_summary()
    src = sources(5)
    rej = rejections(5)
    dms = domains()

    if summary["overall_hire_rate"] is not None and summary["overall_hire_rate"] < 3 and summary["total_records"] > 20:
        insights.append({
            "severity": "warning",
            "title": "Low overall hire rate",
            "detail": f"Only {summary['overall_hire_rate']}% of applicants convert to hires — consider JD specificity or source quality.",
        })

    if summary["avg_days_to_hire"] and summary["avg_days_to_hire"] > 40:
        insights.append({
            "severity": "warning",
            "title": "Slow time-to-hire",
            "detail": f"Average {summary['avg_days_to_hire']} days to hire — SLA typically <30d. Check interview scheduling bottlenecks.",
        })

    if summary["avg_days_to_screen"] and summary["avg_days_to_screen"] > 7:
        insights.append({
            "severity": "info",
            "title": "Slow initial screening",
            "detail": f"{summary['avg_days_to_screen']} days average to screen — set a 5-day SLA for first touch.",
        })

    if src and src[0]["total"] > 0:
        top = src[0]
        insights.append({
            "severity": "success",
            "title": "Top recruiting source",
            "detail": f"{top['source']} leads with {top['total']} applicants and {top['conversion_rate']}% hire rate.",
        })

    if rej:
        top_reason, top_count = rej[0]
        insights.append({
            "severity": "info",
            "title": "Top rejection reason",
            "detail": f"{top_reason} ({top_count} candidates) — refine screening questions or JD expectations.",
        })

    if dms:
        best = max(dms, key=lambda x: x["hire_rate"])
        if best["hire_rate"] > 0:
            insights.append({
                "severity": "success",
                "title": "Best hiring domain",
                "detail": f"{best['domain']}: {best['hire_rate']}% hire rate across {best['applicants']} applicants.",
            })

    if summary["screen_rate"] and summary["screen_rate"] > 75 and summary["total_records"] > 20:
        insights.append({
            "severity": "info",
            "title": "High screening pass rate",
            "detail": f"{summary['screen_rate']}% of applicants are screened — consider stricter JD requirements to reduce recruiter load.",
        })

    return insights

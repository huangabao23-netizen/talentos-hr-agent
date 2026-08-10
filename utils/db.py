"""
SQLite Database persistence layer.
Handles TalentPool, ScreeningRecords, and JDRecords storage & queries.
Uses the project-relative data directory to keep everything self-contained.
"""

import sqlite3
import json
import logging
import os
from pathlib import Path
from datetime import datetime, date, timedelta
from contextlib import contextmanager
from typing import List, Optional, Dict, Any, Tuple

from models.schemas import (
    TalentPoolRecord, TalentPoolStatus,
    ScreeningRecord, FunnelStage, JDRecord,
    ParsedProfile, CandidateResult, ParsedJD,
)

logger = logging.getLogger(__name__)

_DB_PATH = None


def get_db_path() -> Path:
    """Return project-relative SQLite DB path (cached)."""
    global _DB_PATH
    if _DB_PATH is None:
        root = Path(__file__).resolve().parent.parent
        configured_path = os.environ.get("TALENTOS_DB_PATH", "").strip()
        if configured_path:
            candidate = Path(configured_path)
            _DB_PATH = candidate if candidate.is_absolute() else root / candidate
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        else:
            data_dir_name = os.environ.get("TALENTOS_DATA_DIR", "data").strip() or "data"
            data_dir = Path(data_dir_name)
            data_dir = data_dir if data_dir.is_absolute() else root / data_dir
            data_dir.mkdir(parents=True, exist_ok=True)
            _DB_PATH = data_dir / "talentos.db"
    return _DB_PATH


@contextmanager
def _conn():
    """Context-managed connection with row factory and foreign keys on."""
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist. Idempotent."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS talent_pool (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_name       TEXT NOT NULL,
            anonymized_name      TEXT DEFAULT '',
            domain               TEXT DEFAULT '',
            seniority_level      TEXT DEFAULT '',
            total_experience_years REAL DEFAULT 0.0,
            skills               TEXT DEFAULT '[]',
            education            TEXT DEFAULT '[]',
            certifications       TEXT DEFAULT '[]',
            work_summary         TEXT DEFAULT '',
            project_summary      TEXT DEFAULT '',
            location             TEXT DEFAULT '',
            open_to_remote       INTEGER DEFAULT 1,
            status               TEXT DEFAULT 'Active',
            tags                 TEXT DEFAULT '[]',
            raw_profile          TEXT DEFAULT '',
            created_at           TEXT DEFAULT (datetime('now')),
            updated_at           TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_talent_domain ON talent_pool(domain);
        CREATE INDEX IF NOT EXISTS idx_talent_status ON talent_pool(status);

        CREATE TABLE IF NOT EXISTS jd_records (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            job_title            TEXT NOT NULL,
            domain               TEXT DEFAULT '',
            seniority_level      TEXT DEFAULT '',
            department           TEXT DEFAULT '',
            opened_date          TEXT NOT NULL,
            closed_date          TEXT,
            status               TEXT DEFAULT 'Open',
            total_applicants     INTEGER DEFAULT 0,
            total_screened       INTEGER DEFAULT 0,
            total_interviewed    INTEGER DEFAULT 0,
            total_offered        INTEGER DEFAULT 0,
            total_hired          INTEGER DEFAULT 0,
            target_hires         INTEGER DEFAULT 1,
            created_at           TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_jd_status ON jd_records(status);
        CREATE INDEX IF NOT EXISTS idx_jd_opened ON jd_records(opened_date);

        CREATE TABLE IF NOT EXISTS screening_records (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            job_title            TEXT NOT NULL,
            domain               TEXT DEFAULT '',
            seniority_level      TEXT DEFAULT '',
            candidate_name       TEXT NOT NULL,
            anonymized_name      TEXT DEFAULT '',
            initial_score        REAL DEFAULT 0.0,
            final_score          REAL DEFAULT 0.0,
            recommendation       TEXT DEFAULT '',
            stage                TEXT DEFAULT 'Applied',
            source               TEXT DEFAULT '',
            applied_date         TEXT NOT NULL,
            screened_date        TEXT,
            interviewed_date     TEXT,
            offered_date         TEXT,
            hired_date           TEXT,
            rejected_date        TEXT,
            days_to_screen       INTEGER,
            days_to_interview    INTEGER,
            days_to_offer        INTEGER,
            days_to_hire         INTEGER,
            recruiter            TEXT DEFAULT '',
            hiring_manager       TEXT DEFAULT '',
            rejection_reason     TEXT DEFAULT '',
            created_at           TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_screen_stage ON screening_records(stage);
        CREATE INDEX IF NOT EXISTS idx_screen_job ON screening_records(job_title);
        CREATE INDEX IF NOT EXISTS idx_screen_applied ON screening_records(applied_date);

        CREATE TABLE IF NOT EXISTS candidate_followups (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_name         TEXT NOT NULL,
            source_file            TEXT DEFAULT '',
            job_profile_id         TEXT DEFAULT '',
            job_title              TEXT DEFAULT '',
            department             TEXT DEFAULT '',
            matching_skill_id      TEXT DEFAULT '',
            matching_skill_name    TEXT DEFAULT '',
            initial_score          REAL DEFAULT 0.0,
            initial_recommendation TEXT DEFAULT '',
            hr_screening_decision  TEXT DEFAULT '',
            talent_tier            TEXT DEFAULT '',
            current_status         TEXT DEFAULT '待反馈',
            business_review_result TEXT DEFAULT '',
            interview_stage        TEXT DEFAULT '',
            final_result           TEXT DEFAULT '',
            fail_reason            TEXT DEFAULT '',
            hr_note                TEXT DEFAULT '',
            candidate_snapshot     TEXT DEFAULT '{}',
            score_snapshot         TEXT DEFAULT '{}',
            created_at             TEXT DEFAULT (datetime('now')),
            updated_at             TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_followup_status ON candidate_followups(current_status);
        CREATE INDEX IF NOT EXISTS idx_followup_skill ON candidate_followups(matching_skill_id);
        CREATE INDEX IF NOT EXISTS idx_followup_job ON candidate_followups(job_profile_id);

        CREATE TABLE IF NOT EXISTS sourcing_tasks (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name            TEXT NOT NULL,
            talent_direction     TEXT DEFAULT '',
            target_level         TEXT DEFAULT '',
            business_scene       TEXT DEFAULT '',
            focus_signals        TEXT DEFAULT '[]',
            exclusion_rules      TEXT DEFAULT '',
            location_preference  TEXT DEFAULT '',
            linked_job_profile_id TEXT DEFAULT '',
            description          TEXT DEFAULT '',
            strategy_json        TEXT DEFAULT '{}',
            status               TEXT DEFAULT '待确认策略',
            created_at           TEXT DEFAULT (datetime('now')),
            updated_at           TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sourcing_tasks_status ON sourcing_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_sourcing_tasks_direction ON sourcing_tasks(talent_direction);

        CREATE TABLE IF NOT EXISTS sourcing_candidates (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id                INTEGER NOT NULL,
            candidate_name         TEXT NOT NULL,
            current_org            TEXT DEFAULT '',
            source_origin_type     TEXT DEFAULT '',
            authenticity_status    TEXT DEFAULT '待核验',
            direction_tags         TEXT DEFAULT '[]',
            match_score            REAL DEFAULT 0.0,
            recommendation_level   TEXT DEFAULT '',
            recommendation_reason  TEXT DEFAULT '',
            evidence_links         TEXT DEFAULT '[]',
            uncertainties          TEXT DEFAULT '[]',
            suggested_action       TEXT DEFAULT '',
            decision_status        TEXT DEFAULT '待确认',
            hr_note                TEXT DEFAULT '',
            raw_snapshot           TEXT DEFAULT '{}',
            talent_pool_id         INTEGER,
            created_at             TEXT DEFAULT (datetime('now')),
            updated_at             TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(task_id) REFERENCES sourcing_tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sourcing_candidates_task ON sourcing_candidates(task_id);
        CREATE INDEX IF NOT EXISTS idx_sourcing_candidates_decision ON sourcing_candidates(decision_status);
        """)
        _ensure_column(c, "sourcing_candidates", "source_origin_type", "TEXT DEFAULT ''")
        _ensure_column(c, "sourcing_candidates", "authenticity_status", "TEXT DEFAULT '待核验'")
        _ensure_column(c, "candidate_followups", "hr_screening_decision", "TEXT DEFAULT ''")
        _ensure_column(c, "candidate_followups", "talent_tier", "TEXT DEFAULT ''")
        c.execute("""
            UPDATE sourcing_candidates
               SET authenticity_status='待核验'
             WHERE authenticity_status IS NULL OR authenticity_status=''
        """)
        logger.info("DB initialised: %s", get_db_path())


# ── JSON helpers ────────────────────────────────────────────────────────────

def _to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _from_json(s: str) -> Any:
    if not s:
        return []
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return []


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ── Talent Pool CRUD ────────────────────────────────────────────────────────

def _row_to_talent(row: sqlite3.Row) -> TalentPoolRecord:
    return TalentPoolRecord(
        id=row["id"],
        candidate_name=row["candidate_name"],
        anonymized_name=row["anonymized_name"],
        domain=row["domain"],
        seniority_level=row["seniority_level"],
        total_experience_years=row["total_experience_years"],
        skills=_from_json(row["skills"]),
        education=_from_json(row["education"]),
        certifications=_from_json(row["certifications"]),
        work_summary=row["work_summary"],
        project_summary=row["project_summary"],
        location=row["location"],
        open_to_remote=bool(row["open_to_remote"]),
        status=TalentPoolStatus(row["status"]),
        tags=_from_json(row["tags"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        raw_profile=row["raw_profile"],
    )


def add_talent(rec: TalentPoolRecord) -> int:
    """Insert a talent pool record. Returns the new row id."""
    if not rec.anonymized_name:
        rec.anonymized_name = _anonymize(rec.candidate_name, rec.domain)
    rec.updated_at = datetime.now()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO talent_pool
               (candidate_name, anonymized_name, domain, seniority_level,
                total_experience_years, skills, education, certifications,
                work_summary, project_summary, location, open_to_remote,
                status, tags, raw_profile, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.candidate_name, rec.anonymized_name, rec.domain,
                rec.seniority_level, rec.total_experience_years,
                _to_json(rec.skills), _to_json(rec.education),
                _to_json(rec.certifications), rec.work_summary,
                rec.project_summary, rec.location, int(rec.open_to_remote),
                rec.status.value, _to_json(rec.tags), rec.raw_profile or "",
                rec.created_at.isoformat(), rec.updated_at.isoformat(),
            ),
        )
        return cur.lastrowid


def update_talent(rec: TalentPoolRecord) -> None:
    if rec.id is None:
        raise ValueError("Cannot update talent without id")
    rec.updated_at = datetime.now()
    with _conn() as c:
        c.execute(
            """UPDATE talent_pool SET
               candidate_name=?, anonymized_name=?, domain=?,
               seniority_level=?, total_experience_years=?, skills=?,
               education=?, certifications=?, work_summary=?,
               project_summary=?, location=?, open_to_remote=?, status=?,
               tags=?, raw_profile=?, updated_at=?
               WHERE id=?""",
            (
                rec.candidate_name, rec.anonymized_name, rec.domain,
                rec.seniority_level, rec.total_experience_years,
                _to_json(rec.skills), _to_json(rec.education),
                _to_json(rec.certifications), rec.work_summary,
                rec.project_summary, rec.location, int(rec.open_to_remote),
                rec.status.value, _to_json(rec.tags), rec.raw_profile or "",
                rec.updated_at.isoformat(), rec.id,
            ),
        )


def delete_talent(talent_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM talent_pool WHERE id=?", (talent_id,))


def get_talent(talent_id: int) -> Optional[TalentPoolRecord]:
    with _conn() as c:
        row = c.execute("SELECT * FROM talent_pool WHERE id=?", (talent_id,)).fetchone()
        return _row_to_talent(row) if row else None


def list_talents(
    domain: Optional[str] = None,
    status: Optional[TalentPoolStatus] = None,
    min_experience: Optional[float] = None,
    skill_keyword: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 200,
) -> List[TalentPoolRecord]:
    q = "SELECT * FROM talent_pool WHERE 1=1"
    params: list = []
    if domain:
        q += " AND domain LIKE ?"
        params.append(f"%{domain}%")
    if status:
        q += " AND status = ?"
        params.append(status.value)
    if min_experience is not None:
        q += " AND total_experience_years >= ?"
        params.append(min_experience)
    if skill_keyword:
        q += " AND skills LIKE ?"
        params.append(f"%{skill_keyword}%")
    if search_text:
        q += " AND (candidate_name LIKE ? OR work_summary LIKE ? OR project_summary LIKE ? OR skills LIKE ?)"
        kw = f"%{search_text}%"
        params.extend([kw, kw, kw, kw])
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
        return [_row_to_talent(r) for r in rows]


def talent_stats() -> Dict[str, Any]:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM talent_pool").fetchone()[0]
        by_status = dict(c.execute(
            "SELECT status, COUNT(*) FROM talent_pool GROUP BY status"
        ).fetchall())
        by_domain = dict(c.execute(
            "SELECT domain, COUNT(*) FROM talent_pool "
            "WHERE domain <> '' GROUP BY domain ORDER BY 2 DESC LIMIT 10"
        ).fetchall())
        avg_exp = c.execute(
            "SELECT AVG(total_experience_years) FROM talent_pool"
        ).fetchone()[0] or 0.0
        active = c.execute(
            "SELECT COUNT(*) FROM talent_pool WHERE status='Active'"
        ).fetchone()[0]
        remote_ok = c.execute(
            "SELECT COUNT(*) FROM talent_pool WHERE open_to_remote=1"
        ).fetchone()[0]
        return {
            "total": total,
            "by_status": by_status,
            "by_domain": by_domain,
            "avg_experience_years": round(float(avg_exp), 1),
            "active": active,
            "remote_ok": remote_ok,
        }


# ── JD Records CRUD ──────────────────────────────────────────────────────────

def _row_to_jd(row: sqlite3.Row) -> JDRecord:
    return JDRecord(
        id=row["id"],
        job_title=row["job_title"],
        domain=row["domain"],
        seniority_level=row["seniority_level"],
        department=row["department"],
        opened_date=date.fromisoformat(row["opened_date"]),
        closed_date=date.fromisoformat(row["closed_date"]) if row["closed_date"] else None,
        status=row["status"],
        total_applicants=row["total_applicants"],
        total_screened=row["total_screened"],
        total_interviewed=row["total_interviewed"],
        total_offered=row["total_offered"],
        total_hired=row["total_hired"],
        target_hires=row["target_hires"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def add_jd_record(jd: JDRecord) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO jd_records
               (job_title, domain, seniority_level, department,
                opened_date, closed_date, status, total_applicants,
                total_screened, total_interviewed, total_offered,
                total_hired, target_hires, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jd.job_title, jd.domain, jd.seniority_level, jd.department,
                jd.opened_date.isoformat(),
                jd.closed_date.isoformat() if jd.closed_date else None,
                jd.status, jd.total_applicants, jd.total_screened,
                jd.total_interviewed, jd.total_offered, jd.total_hired,
                jd.target_hires, jd.created_at.isoformat(),
            ),
        )
        return cur.lastrowid


def list_jd_records(limit: int = 100) -> List[JDRecord]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM jd_records ORDER BY opened_date DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [_row_to_jd(r) for r in rows]


# ── Screening Records CRUD ────────────────────────────────────────────────────

def _row_to_screening(row: sqlite3.Row) -> ScreeningRecord:
    def _d(s):
        return date.fromisoformat(s) if s else None
    return ScreeningRecord(
        id=row["id"],
        job_title=row["job_title"],
        domain=row["domain"],
        seniority_level=row["seniority_level"],
        candidate_name=row["candidate_name"],
        anonymized_name=row["anonymized_name"],
        initial_score=row["initial_score"],
        final_score=row["final_score"],
        recommendation=row["recommendation"],
        stage=FunnelStage(row["stage"]),
        source=row["source"],
        applied_date=date.fromisoformat(row["applied_date"]),
        screened_date=_d(row["screened_date"]),
        interviewed_date=_d(row["interviewed_date"]),
        offered_date=_d(row["offered_date"]),
        hired_date=_d(row["hired_date"]),
        rejected_date=_d(row["rejected_date"]),
        days_to_screen=row["days_to_screen"],
        days_to_interview=row["days_to_interview"],
        days_to_offer=row["days_to_offer"],
        days_to_hire=row["days_to_hire"],
        recruiter=row["recruiter"],
        hiring_manager=row["hiring_manager"],
        rejection_reason=row["rejection_reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def add_screening_record(rec: ScreeningRecord) -> int:
    if not rec.anonymized_name:
        rec.anonymized_name = _anonymize(rec.candidate_name, rec.domain)
    def _iso(d):
        return d.isoformat() if d else None
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO screening_records
               (job_title, domain, seniority_level, candidate_name,
                anonymized_name, initial_score, final_score, recommendation,
                stage, source, applied_date, screened_date, interviewed_date,
                offered_date, hired_date, rejected_date, days_to_screen,
                days_to_interview, days_to_offer, days_to_hire,
                recruiter, hiring_manager, rejection_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec.job_title, rec.domain, rec.seniority_level,
                rec.candidate_name, rec.anonymized_name,
                rec.initial_score, rec.final_score, rec.recommendation,
                rec.stage.value, rec.source,
                rec.applied_date.isoformat(), _iso(rec.screened_date),
                _iso(rec.interviewed_date), _iso(rec.offered_date),
                _iso(rec.hired_date), _iso(rec.rejected_date),
                rec.days_to_screen, rec.days_to_interview,
                rec.days_to_offer, rec.days_to_hire,
                rec.recruiter, rec.hiring_manager, rec.rejection_reason,
                rec.created_at.isoformat(),
            ),
        )
        return cur.lastrowid


def list_screening_records(
    job_title: Optional[str] = None,
    stage: Optional[FunnelStage] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 500,
) -> List[ScreeningRecord]:
    q = "SELECT * FROM screening_records WHERE 1=1"
    params: list = []
    if job_title:
        q += " AND job_title LIKE ?"
        params.append(f"%{job_title}%")
    if stage:
        q += " AND stage = ?"
        params.append(stage.value)
    if from_date:
        q += " AND applied_date >= ?"
        params.append(from_date.isoformat())
    if to_date:
        q += " AND applied_date <= ?"
        params.append(to_date.isoformat())
    q += " ORDER BY applied_date DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
        return [_row_to_screening(r) for r in rows]


# ── Analytics Aggregations ───────────────────────────────────────────────────

def funnel_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    job_title: Optional[str] = None,
) -> Dict[str, int]:
    """Count candidates per funnel stage."""
    q = "SELECT stage, COUNT(*) FROM screening_records WHERE 1=1"
    params: list = []
    if from_date:
        q += " AND applied_date >= ?"; params.append(from_date.isoformat())
    if to_date:
        q += " AND applied_date <= ?"; params.append(to_date.isoformat())
    if job_title:
        q += " AND job_title LIKE ?"; params.append(f"%{job_title}%")
    q += " GROUP BY stage"
    with _conn() as c:
        rows = dict(c.execute(q, params).fetchall())
    stages = [s.value for s in FunnelStage]
    return {s: rows.get(s, 0) for s in stages}


def time_metrics(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Aggregate time-to-X metrics across the funnel."""
    q = """SELECT AVG(days_to_screen), AVG(days_to_interview),
                  AVG(days_to_offer), AVG(days_to_hire),
                  COUNT(*)
           FROM screening_records WHERE 1=1"""
    params: list = []
    if from_date:
        q += " AND applied_date >= ?"; params.append(from_date.isoformat())
    if to_date:
        q += " AND applied_date <= ?"; params.append(to_date.isoformat())
    with _conn() as c:
        row = c.execute(q, params).fetchone()
    def _r(v):
        return round(float(v), 1) if v else None
    return {
        "avg_days_to_screen": _r(row[0]),
        "avg_days_to_interview": _r(row[1]),
        "avg_days_to_offer": _r(row[2]),
        "avg_days_to_hire": _r(row[3]),
        "total_records": row[4] or 0,
    }


def trend_by_month(months: int = 6) -> List[Dict[str, Any]]:
    """Monthly counts of applicants, screened, interviewed, hired."""
    today = date.today().replace(day=1)
    start = today - timedelta(days=31 * (months - 1))
    start = start.replace(day=1)
    with _conn() as c:
        rows = c.execute(
            """SELECT
                 substr(applied_date,1,7) AS m,
                 SUM(CASE WHEN stage IN ('Applied','Screened','Interviewed','Offered','Hired','Rejected') THEN 1 ELSE 0 END) AS applied,
                 SUM(CASE WHEN screened_date IS NOT NULL THEN 1 ELSE 0 END) AS screened,
                 SUM(CASE WHEN interviewed_date IS NOT NULL THEN 1 ELSE 0 END) AS interviewed,
                 SUM(CASE WHEN offered_date IS NOT NULL THEN 1 ELSE 0 END) AS offered,
                 SUM(CASE WHEN hired_date IS NOT NULL THEN 1 ELSE 0 END) AS hired
               FROM screening_records
               WHERE date(applied_date) >= date(?)
               GROUP BY m ORDER BY m""",
            (start.isoformat(),),
        ).fetchall()
    existing = {r["m"]: dict(r) for r in rows}
    result = []
    cur = start
    for _ in range(months):
        key = cur.strftime("%Y-%m")
        r = existing.get(key, {"m": key, "applied": 0, "screened": 0,
                               "interviewed": 0, "offered": 0, "hired": 0})
        result.append({
            "month": key,
            "applied": r["applied"] or 0,
            "screened": r["screened"] or 0,
            "interviewed": r["interviewed"] or 0,
            "offered": r["offered"] or 0,
            "hired": r["hired"] or 0,
        })
        # advance month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return result


def source_effectiveness(limit: int = 8) -> List[Dict[str, Any]]:
    """Per source: total, hired, conversion rate."""
    with _conn() as c:
        rows = c.execute(
            """SELECT source, COUNT(*) AS total,
                      SUM(CASE WHEN stage='Hired' THEN 1 ELSE 0 END) AS hired
               FROM screening_records
               WHERE source <> ''
               GROUP BY source ORDER BY total DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        total = r["total"] or 0
        hired = r["hired"] or 0
        result.append({
            "source": r["source"] or "Unknown",
            "total": total,
            "hired": hired,
            "conversion_rate": round(hired / total * 100, 1) if total else 0.0,
        })
    return result


def rejection_reasons(limit: int = 10) -> List[Tuple[str, int]]:
    with _conn() as c:
        rows = c.execute(
            """SELECT rejection_reason, COUNT(*) c
               FROM screening_records
               WHERE rejection_reason <> ''
               GROUP BY rejection_reason ORDER BY c DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [(r["rejection_reason"], r["c"]) for r in rows]


def score_distribution(bins: int = 10) -> List[Dict[str, Any]]:
    """Distribution of final_score across 0-10 in given bins."""
    with _conn() as c:
        rows = c.execute(
            "SELECT final_score FROM screening_records WHERE final_score IS NOT NULL"
        ).fetchall()
    scores = [r["final_score"] for r in rows]
    if not scores:
        return []
    width = 10.0 / bins
    dist = []
    for i in range(bins):
        lo = round(i * width, 1)
        hi = round((i + 1) * width, 1)
        count = sum(1 for s in scores if lo <= s < hi)
        if i == bins - 1:
            count += sum(1 for s in scores if s == 10.0)
        dist.append({"range": f"{lo}-{hi}", "low": lo, "high": hi, "count": count})
    return dist


def domain_breakdown() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            """SELECT domain,
                      COUNT(*) AS applicants,
                      SUM(CASE WHEN stage='Hired' THEN 1 ELSE 0 END) AS hired,
                      AVG(final_score) AS avg_score
               FROM screening_records
               WHERE domain <> ''
               GROUP BY domain ORDER BY applicants DESC LIMIT 12"""
        ).fetchall()
    return [
        {
            "domain": r["domain"],
            "applicants": r["applicants"] or 0,
            "hired": r["hired"] or 0,
            "avg_score": round(float(r["avg_score"] or 0), 1),
            "hire_rate": round((r["hired"] or 0) / (r["applicants"] or 1) * 100, 1),
        }
        for r in rows
    ]


# ── Seed sample data (for demo) ───────────────────────────────────────────────

_SAMPLE_DOMAINS = [
    "Machine Learning", "Backend Engineering", "Frontend Engineering",
    "Data Engineering", "Product Management", "DevOps / SRE",
    "UX Design", "Mobile Engineering", "Data Science", "QA Engineering",
]

_SAMPLE_SENIORITY = ["Junior", "Mid", "Senior", "Lead"]

_SAMPLE_SOURCES = [
    "LinkedIn", "Referral", "Company Website", "Indeed",
    "Glassdoor", "Recruiter Outreach", "Campus", "Hacker News",
]

_SAMPLE_REJECTIONS = [
    "Skills mismatch", "Insufficient experience", "Culture fit",
    "Poor interview performance", "Accepted another offer",
    "Salary expectations", "Location mismatch", "Duplicate candidate",
]

_SAMPLE_RECRUITERS = ["Emma Chen", "James Wilson", "Sophie Park", "Mike Johnson"]
_SAMPLE_HM = ["David Li", "Priya Sharma", "Alex Tan", "Rachel Brown"]

_FIRST_NAMES = ["Alex","Sam","Jordan","Taylor","Morgan","Casey","Riley","Avery",
                "Quinn","Rowan","Drew","Hayden","Kai","Reese","Skyler","Emerson",
                "Arjun","Priya","Ravi","Sneha","Amit","Wei","Lin","Yuki","Hiro"]
_LAST_NAMES = ["Patel","Lee","Smith","Chen","Kumar","Johnson","Wang","Gupta",
               "Tanaka","Garcia","Brown","Davis","Wilson","Martinez","Anderson"]


def _anonymize(real_name: str, domain: str) -> str:
    """Generate a consistent fake name from domain hash (no PII leakage)."""
    import hashlib
    seed = int(hashlib.md5(f"{real_name}|{domain}".encode()).hexdigest(), 16)
    fn = _FIRST_NAMES[seed % len(_FIRST_NAMES)]
    ln = _LAST_NAMES[(seed >> 4) % len(_LAST_NAMES)]
    return f"{fn} {ln}"


def seed_demo_data(force: bool = False) -> str:
    """Generate realistic sample data for analytics page. Idempotent."""
    init_db()
    with _conn() as c:
        existing = c.execute("SELECT COUNT(*) FROM screening_records").fetchone()[0]
        if existing > 0 and not force:
            return f"Sample data already present ({existing} records). Use force=True to regenerate."
        if force:
            c.execute("DELETE FROM talent_pool")
            c.execute("DELETE FROM screening_records")
            c.execute("DELETE FROM jd_records")

    import random
    random.seed(42)

    today = date.today()
    skills_pool = {
        "Machine Learning": ["Python","PyTorch","TensorFlow","SQL","MLflow","Scikit-learn","Docker","Kubernetes","AWS","MLOps"],
        "Backend Engineering": ["Python","Java","Go","PostgreSQL","Redis","Kafka","Docker","AWS","REST","GraphQL"],
        "Frontend Engineering": ["React","TypeScript","JavaScript","CSS","Node.js","Next.js","Vite","Redux","Testing","Webpack"],
        "Data Engineering": ["Python","Spark","SQL","Airflow","dbt","Snowflake","BigQuery","Kafka","Docker","AWS"],
        "Product Management": ["SQL","Jira","Figma","User Research","Roadmapping","Stakeholder Management","Analytics","A/B Testing"],
        "DevOps / SRE": ["Kubernetes","Docker","Terraform","AWS","Prometheus","Grafana","CI/CD","Linux","Python","Bash"],
        "UX Design": ["Figma","User Research","Prototyping","Wireframing","Usability Testing","Design Systems","Sketch","Adobe XD"],
        "Mobile Engineering": ["Swift","Kotlin","React Native","Flutter","iOS","Android","Firebase","CI/CD","Testing"],
        "Data Science": ["Python","SQL","Pandas","Scikit-learn","PyTorch","Tableau","Statistics","A/B Testing","R","Spark"],
        "QA Engineering": ["Selenium","Python","Java","Postman","JMeter","CI/CD","API Testing","Automation","Performance Testing"],
    }

    titles_map = {
        "Machine Learning": ("ML Engineer","Senior ML Engineer","ML Lead"),
        "Backend Engineering": ("Backend Engineer","Senior Backend Engineer","Engineering Lead"),
        "Frontend Engineering": ("Frontend Engineer","Senior Frontend Engineer","FE Lead"),
        "Data Engineering": ("Data Engineer","Senior Data Engineer","Data Platform Lead"),
        "Product Management": ("Product Manager","Senior PM","Group PM"),
        "DevOps / SRE": ("SRE Engineer","Senior SRE","Platform Lead"),
        "UX Design": ("UX Designer","Senior UX Designer","Design Lead"),
        "Mobile Engineering": ("Mobile Engineer","Senior Mobile Engineer","Mobile Lead"),
        "Data Science": ("Data Scientist","Senior DS","Staff DS"),
        "QA Engineering": ("QA Engineer","Senior QA","QA Lead"),
    }

    depts = ["Engineering","Engineering","Engineering","Product","Design","Platform","Data"]

    # Create 10 JDs
    jd_ids = []
    for dom in _SAMPLE_DOMAINS[:10]:
        titles = titles_map[dom]
        t = titles[random.randint(0, 2)]
        opened = today - timedelta(days=random.randint(30, 180))
        closed = None
        status = "Open"
        if random.random() < 0.6:
            closed = opened + timedelta(days=random.randint(30, 90))
            if closed < today:
                status = "Closed"
            else:
                closed = None
        jd = JDRecord(
            job_title=t, domain=dom,
            seniority_level=_SAMPLE_SENIORITY[random.randint(0,3)],
            department=random.choice(depts),
            opened_date=opened, closed_date=closed, status=status,
            target_hires=random.randint(1, 3),
        )
        jd_ids.append((add_jd_record(jd), jd))

    # Create 150 screening records
    created_sr = 0
    for jd_id, jd in jd_ids:
        n_applicants = random.randint(8, 28)
        jd.total_applicants = n_applicants
        hired = 0
        for i in range(n_applicants):
            applied = jd.opened_date + timedelta(days=random.randint(0, 60))
            if applied > today:
                continue
            name = f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
            initial = round(random.uniform(2, 9.5), 1)
            # simulate final score
            final = round(max(0, min(10, initial + random.uniform(-1.2, 1.2))), 1)

            stages_order = [FunnelStage.APPLIED, FunnelStage.SCREENED,
                            FunnelStage.INTERVIEWED, FunnelStage.OFFERED,
                            FunnelStage.HIRED]
            # weighted random drop-off
            pass_rate = [1.0, 0.70, 0.45, 0.20, 0.80]
            stage_idx = 0
            for pr in pass_rate[1:]:
                if random.random() < pr:
                    stage_idx += 1
                else:
                    break
            stage = stages_order[stage_idx]
            rejected = stage_idx < len(stages_order) - 1 and random.random() < 0.5
            if rejected and stage_idx < len(stages_order) - 1:
                stage = FunnelStage.REJECTED

            screened = interviewed = offered = hired_d = rejected_d = None
            d2s = d2i = d2o = d2h = None
            if stage_idx >= 1 or stage == FunnelStage.REJECTED and stage_idx >= 1:
                screened = applied + timedelta(days=random.randint(1, 8))
                d2s = (screened - applied).days
            if stage_idx >= 2:
                interviewed = screened + timedelta(days=random.randint(2, 10))
                d2i = (interviewed - applied).days
            if stage_idx >= 3:
                offered = interviewed + timedelta(days=random.randint(2, 14))
                d2o = (offered - applied).days
            if stage_idx >= 4:
                hired_d = offered + timedelta(days=random.randint(3, 21))
                d2h = (hired_d - applied).days
                hired += 1
            if stage == FunnelStage.REJECTED:
                rejected_d = applied + timedelta(days=random.randint(3, 30))

            rec = ScreeningRecord(
                job_title=jd.job_title, domain=jd.domain,
                seniority_level=jd.seniority_level,
                candidate_name=name,
                initial_score=initial, final_score=final,
                recommendation="",
                stage=stage,
                source=random.choice(_SAMPLE_SOURCES),
                applied_date=applied,
                screened_date=screened, interviewed_date=interviewed,
                offered_date=offered, hired_date=hired_d,
                rejected_date=rejected_d,
                days_to_screen=d2s, days_to_interview=d2i,
                days_to_offer=d2o, days_to_hire=d2h,
                recruiter=random.choice(_SAMPLE_RECRUITERS),
                hiring_manager=random.choice(_SAMPLE_HM),
                rejection_reason=random.choice(_SAMPLE_REJECTIONS) if stage == FunnelStage.REJECTED else "",
            )
            add_screening_record(rec)
            created_sr += 1

        jd.total_hired = hired
        jd.total_screened = random.randint(int(n_applicants * 0.55), n_applicants)
        jd.total_interviewed = random.randint(int(n_applicants * 0.25), int(n_applicants * 0.6))
        jd.total_offered = random.randint(int(n_applicants * 0.08), int(n_applicants * 0.25))
        # update jd
        with _conn() as c:
            c.execute(
                """UPDATE jd_records SET total_applicants=?, total_screened=?,
                   total_interviewed=?, total_offered=?, total_hired=?,
                   status=?, closed_date=? WHERE id=?""",
                (jd.total_applicants, jd.total_screened, jd.total_interviewed,
                 jd.total_offered, jd.total_hired, jd.status,
                 jd.closed_date.isoformat() if jd.closed_date else None,
                 jd_id),
            )

    # Create 40 talent pool records (resume open source)
    for i in range(40):
        dom = random.choice(_SAMPLE_DOMAINS)
        name = f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
        skills = random.sample(skills_pool[dom], k=random.randint(4, 8))
        exp = round(random.uniform(0.5, 12), 1)
        edu_opts = [
            ["BSc in Computer Science from IIT Delhi (2021)"],
            ["BTech in IT from NIT Trichy (2019)", "MTech in AI from IISc (2021)"],
            ["B.Eng Software from BITS Pilani (2020)"],
            ["MSc Data Science from Imperial College (2022)"],
            ["BA Economics from Delhi University (2018)", "PGDBA from ISB (2020)"],
        ]
        certs_opts = [
            ["AWS Certified Solutions Architect", "CKA"],
            ["Google Cloud Professional ML Engineer"],
            ["DeepLearning.AI TensorFlow Developer"],
            [],
            ["Certified Kubernetes Admin", "Terraform Associate"],
        ]
        tpr = TalentPoolRecord(
            candidate_name=name,
            domain=dom,
            seniority_level=_SAMPLE_SENIORITY[min(3, int(exp / 3))],
            total_experience_years=exp,
            skills=skills,
            education=random.choice(edu_opts),
            certifications=random.choice(certs_opts),
            work_summary=f"Senior {dom} professional with {exp} years of experience building scalable systems. Previously worked on distributed systems, data pipelines, and product launches.",
            project_summary=f"Led the rebuild of the core {dom.lower()} platform reducing latency by 35%. Implemented end-to-end CI/CD, improving deployment frequency from weekly to daily.",
            location=random.choice(["Bangalore, India","Singapore","Remote","San Francisco, USA","Berlin, Germany","Tokyo, Japan"]),
            open_to_remote=random.random() > 0.25,
            status=random.choices(
                [TalentPoolStatus.ACTIVE, TalentPoolStatus.PLACED, TalentPoolStatus.ARCHIVED],
                weights=[0.70, 0.15, 0.15],
            )[0],
            tags=random.sample(skills_pool[dom][:5], k=random.randint(1, 3)),
        )
        add_talent(tpr)

    return (f"Seeded demo data: {len(jd_ids)} JDs · {created_sr} screening records · "
            f"40 talent pool entries")


# ── Convenience: convert pipeline outputs → storable records ─────────────────

def candidate_to_talent(
    profile: ParsedProfile,
    jd: Optional[ParsedJD] = None,
) -> TalentPoolRecord:
    """Convert a parsed profile into a TalentPoolRecord for入库."""
    return TalentPoolRecord(
        candidate_name=profile.candidate_name,
        domain=jd.domain if jd else "",
        seniority_level=jd.seniority_level if jd else "",
        total_experience_years=profile.total_experience_years,
        skills=profile.skills,
        education=profile.education,
        certifications=profile.certifications,
        work_summary="; ".join(profile.work_history[:3]),
        project_summary="; ".join(profile.projects[:3]),
        raw_profile=profile.summary,
        open_to_remote=True,
        status=TalentPoolStatus.ACTIVE,
        tags=[],
    )


def result_to_screening(
    result: CandidateResult,
    jd: ParsedJD,
    applied_date: Optional[date] = None,
    source: str = "Manual",
) -> ScreeningRecord:
    """Convert CandidateResult + JD → ScreeningRecord for analytics tracking."""
    applied = applied_date or date.today()
    rec = result.hire_recommendation.value
    if rec == "Strong Hire":
        stage = FunnelStage.INTERVIEWED
    elif rec == "Hire":
        stage = FunnelStage.SCREENED
    elif rec == "Maybe":
        stage = FunnelStage.SCREENED
    else:
        stage = FunnelStage.REJECTED
    final = result.weighted_total
    return ScreeningRecord(
        job_title=jd.job_title,
        domain=jd.domain,
        seniority_level=jd.seniority_level,
        candidate_name=result.profile.candidate_name,
        initial_score=final,
        final_score=final,
        recommendation=rec,
        stage=stage,
        source=source,
        applied_date=applied,
        rejection_reason="Low score" if stage == FunnelStage.REJECTED else "",
    )


# ── Candidate follow-up tracking ─────────────────────────────────────────────

def _row_to_followup(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["candidate_snapshot"] = _from_json(data.get("candidate_snapshot", "{}"))
    data["score_snapshot"] = _from_json(data.get("score_snapshot", "{}"))
    return data


def add_candidate_followup(
    result: CandidateResult,
    jd: ParsedJD,
    job_profile_id: str = "",
    department: str = "",
    hr_screening_decision: str = "",
    talent_tier: str = "",
) -> Tuple[int, bool]:
    """
    Create or refresh a candidate follow-up record.

    Returns (row_id, created). Duplicate key is candidate + source file + job profile.
    """
    profile = result.profile
    source_file = profile.source_file or ""
    candidate_name = profile.candidate_name
    job_profile_id = job_profile_id or jd.job_title

    candidate_snapshot = {
        "candidate_name": profile.candidate_name,
        "source_file": source_file,
        "skills": profile.skills,
        "experience_years": profile.total_experience_years,
        "education": profile.education,
        "work_history": profile.work_history[:5],
        "projects": profile.projects[:5],
        "summary": profile.summary,
    }
    score_snapshot = {
        "weighted_total": result.weighted_total,
        "recommendation": result.hire_recommendation.value,
        "hard_checks": result.scores.hard_checks,
        "matched_evidence": result.scores.matched_evidence,
        "gaps": result.scores.gaps,
        "risks": result.scores.risks,
        "suggested_action": result.scores.suggested_action,
        "dimension_weights": result.scores.dimension_weights,
    }

    with _conn() as c:
        existing = c.execute(
            """SELECT id FROM candidate_followups
               WHERE candidate_name=? AND source_file=? AND job_profile_id=?
               ORDER BY id DESC LIMIT 1""",
            (candidate_name, source_file, job_profile_id),
        ).fetchone()
        if existing:
            c.execute(
                """UPDATE candidate_followups SET
                   job_title=?, department=?, matching_skill_id=?, matching_skill_name=?,
                   initial_score=?, initial_recommendation=?, candidate_snapshot=?,
                   score_snapshot=?, hr_screening_decision=?, talent_tier=?,
                   current_status='待反馈', business_review_result='',
                   interview_stage='', final_result='', fail_reason='', hr_note='',
                   updated_at=?
                   WHERE id=?""",
                (
                    jd.job_title,
                    department,
                    result.scores.matching_skill_id,
                    result.scores.matching_skill_name,
                    result.weighted_total,
                    result.hire_recommendation.value,
                    _to_json(candidate_snapshot),
                    _to_json(score_snapshot),
                    hr_screening_decision,
                    talent_tier,
                    datetime.now().isoformat(),
                    existing["id"],
                ),
            )
            return existing["id"], False

        cur = c.execute(
            """INSERT INTO candidate_followups
               (candidate_name, source_file, job_profile_id, job_title, department,
                matching_skill_id, matching_skill_name, initial_score,
                initial_recommendation, hr_screening_decision, talent_tier,
                current_status, candidate_snapshot, score_snapshot, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_name,
                source_file,
                job_profile_id,
                jd.job_title,
                department,
                result.scores.matching_skill_id,
                result.scores.matching_skill_name,
                result.weighted_total,
                result.hire_recommendation.value,
                hr_screening_decision,
                talent_tier,
                "待反馈",
                _to_json(candidate_snapshot),
                _to_json(score_snapshot),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )
        return cur.lastrowid, True


def list_candidate_followups(status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as c:
        if status:
            rows = c.execute(
                """SELECT * FROM candidate_followups
                   WHERE current_status=?
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM candidate_followups
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [_row_to_followup(row) for row in rows]


def update_candidate_followup(
    followup_id: int,
    business_review_result: str,
    interview_stage: str,
    final_result: str,
    fail_reason: str = "",
    hr_note: str = "",
    current_status: str = "已反馈",
) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE candidate_followups SET
               business_review_result=?, interview_stage=?, final_result=?,
               fail_reason=?, hr_note=?, current_status=?, updated_at=?
               WHERE id=?""",
            (
                business_review_result,
                interview_stage,
                final_result,
                fail_reason,
                hr_note,
                current_status,
                datetime.now().isoformat(),
                followup_id,
            ),
        )


def candidate_followup_stats() -> Dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT current_status, COUNT(*) AS n FROM candidate_followups GROUP BY current_status"
        ).fetchall()
    stats = {row["current_status"]: int(row["n"]) for row in rows}
    stats["total"] = sum(stats.values())
    return stats


# ── Open-source talent sourcing ──────────────────────────────────────────────

def _row_to_sourcing_task(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["focus_signals"] = _from_json(data.get("focus_signals", "[]"))
    data["strategy_json"] = _from_json(data.get("strategy_json", "{}")) or {}
    return data


def _row_to_sourcing_candidate(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["direction_tags"] = _from_json(data.get("direction_tags", "[]"))
    data["evidence_links"] = _from_json(data.get("evidence_links", "[]"))
    data["uncertainties"] = _from_json(data.get("uncertainties", "[]"))
    data["raw_snapshot"] = _from_json(data.get("raw_snapshot", "{}")) or {}
    if not data.get("source_origin_type"):
        data["source_origin_type"] = data["raw_snapshot"].get("source_origin_type") or data["raw_snapshot"].get("source_type", "")
    if not data.get("authenticity_status"):
        data["authenticity_status"] = data["raw_snapshot"].get("authenticity_status") or "待核验"
    return data


def add_sourcing_task(
    task_name: str,
    talent_direction: str,
    target_level: str,
    business_scene: str,
    focus_signals: List[str],
    exclusion_rules: str = "",
    location_preference: str = "",
    linked_job_profile_id: str = "",
    description: str = "",
    strategy: Optional[Dict[str, Any]] = None,
    status: str = "待确认策略",
) -> int:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO sourcing_tasks
               (task_name, talent_direction, target_level, business_scene,
                focus_signals, exclusion_rules, location_preference,
                linked_job_profile_id, description, strategy_json, status,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_name,
                talent_direction,
                target_level,
                business_scene,
                _to_json(focus_signals),
                exclusion_rules,
                location_preference,
                linked_job_profile_id,
                description,
                _to_json(strategy or {}),
                status,
                now,
                now,
            ),
        )
        return cur.lastrowid


def update_sourcing_task_strategy(task_id: int, strategy: Dict[str, Any], status: str = "待寻访") -> None:
    with _conn() as c:
        c.execute(
            """UPDATE sourcing_tasks SET strategy_json=?, status=?, updated_at=?
               WHERE id=?""",
            (_to_json(strategy), status, datetime.now().isoformat(), task_id),
        )


def update_sourcing_task_status(task_id: int, status: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sourcing_tasks SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now().isoformat(), task_id),
        )


def get_sourcing_task(task_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM sourcing_tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_sourcing_task(row) if row else None


def list_sourcing_tasks(status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with _conn() as c:
        if status:
            rows = c.execute(
                """SELECT * FROM sourcing_tasks WHERE status=?
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM sourcing_tasks
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [_row_to_sourcing_task(row) for row in rows]


def add_sourcing_candidate(task_id: int, candidate: Dict[str, Any]) -> int:
    now = datetime.now().isoformat()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO sourcing_candidates
               (task_id, candidate_name, current_org, source_origin_type, authenticity_status,
                direction_tags, match_score,
                recommendation_level, recommendation_reason, evidence_links,
                uncertainties, suggested_action, decision_status, hr_note,
                raw_snapshot, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                candidate.get("candidate_name") or "待确认候选人",
                candidate.get("current_org", ""),
                candidate.get("source_origin_type", ""),
                candidate.get("authenticity_status", "待核验"),
                _to_json(candidate.get("direction_tags", [])),
                float(candidate.get("match_score", 0) or 0),
                candidate.get("recommendation_level", ""),
                candidate.get("recommendation_reason", ""),
                _to_json(candidate.get("evidence_links", [])),
                _to_json(candidate.get("uncertainties", [])),
                candidate.get("suggested_action", ""),
                candidate.get("decision_status", "待确认"),
                candidate.get("hr_note", ""),
                _to_json(candidate),
                now,
                now,
            ),
        )
        return cur.lastrowid


def list_sourcing_candidates(
    task_id: Optional[int] = None,
    decision_status: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    q = "SELECT * FROM sourcing_candidates WHERE 1=1"
    params: list = []
    if task_id:
        q += " AND task_id=?"
        params.append(task_id)
    if decision_status:
        q += " AND decision_status=?"
        params.append(decision_status)
    q += " ORDER BY match_score DESC, updated_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [_row_to_sourcing_candidate(row) for row in rows]


def get_sourcing_candidate(candidate_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM sourcing_candidates WHERE id=?", (candidate_id,)).fetchone()
    return _row_to_sourcing_candidate(row) if row else None


def update_sourcing_candidate_decision(
    candidate_id: int,
    decision_status: str,
    hr_note: str = "",
    talent_pool_id: Optional[int] = None,
) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE sourcing_candidates SET decision_status=?, hr_note=?,
               talent_pool_id=COALESCE(?, talent_pool_id), updated_at=?
               WHERE id=?""",
            (
                decision_status,
                hr_note,
                talent_pool_id,
                datetime.now().isoformat(),
                candidate_id,
            ),
        )


def sourcing_stats() -> Dict[str, int]:
    with _conn() as c:
        total_tasks = c.execute("SELECT COUNT(*) FROM sourcing_tasks").fetchone()[0]
        total_candidates = c.execute("SELECT COUNT(*) FROM sourcing_candidates").fetchone()[0]
        by_decision = dict(c.execute(
            "SELECT decision_status, COUNT(*) FROM sourcing_candidates GROUP BY decision_status"
        ).fetchall())
    return {
        "tasks": int(total_tasks or 0),
        "candidates": int(total_candidates or 0),
        "pending": int(by_decision.get("待确认", 0)),
        "in_pool": int(by_decision.get("已入库", 0)),
        "focus": int(by_decision.get("重点关注", 0)),
        "rejected": int(by_decision.get("暂不处理", 0)),
    }

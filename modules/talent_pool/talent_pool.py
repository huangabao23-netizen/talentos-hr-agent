"""
Talent Pool (Resume Open Source) Agent.
Manages anonymized talent search, filtering, and ingestion from screening pipeline.
"""

import logging
import re
from typing import List, Optional, Dict, Any, Tuple
from collections import Counter

from models.schemas import (
    TalentPoolRecord, TalentPoolStatus,
    ParsedProfile, ParsedJD, CandidateResult,
)
from utils.db import (
    init_db, add_talent, update_talent, delete_talent, get_talent,
    list_talents, talent_stats, candidate_to_talent,
)

logger = logging.getLogger(__name__)
init_db()


def ingest_candidates(
    results: List[CandidateResult],
    jd: ParsedJD,
    only_recommended: bool = True,
) -> Tuple[int, List[str]]:
    """
    Ingest candidates from a screening run into the talent pool.
    By default only ingests Strong Hire / Hire / Maybe.
    Returns (count_saved, list_of_messages).
    """
    saved = 0
    messages = []
    for r in results:
        if only_recommended and r.hire_recommendation.value == "No Hire":
            continue
        try:
            tpr = candidate_to_talent(r.profile, jd)
            add_talent(tpr)
            saved += 1
            messages.append(f"✓ Added {r.profile.candidate_name} ({r.hire_recommendation.value})")
        except Exception as e:
            messages.append(f"✗ Failed to add {r.profile.candidate_name}: {e}")
    return saved, messages


def ingest_single_profile(
    profile: ParsedProfile,
    jd: Optional[ParsedJD] = None,
    domain: str = "",
    seniority: str = "",
    location: str = "",
    open_to_remote: bool = True,
) -> int:
    """Manually ingest a parsed profile into the talent pool."""
    tpr = candidate_to_talent(profile, jd)
    if domain:
        tpr.domain = domain
    if seniority:
        tpr.seniority_level = seniority
    if location:
        tpr.location = location
    tpr.open_to_remote = open_to_remote
    return add_talent(tpr)


def search_talents(
    keyword: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[TalentPoolStatus] = None,
    min_experience: Optional[float] = None,
    max_experience: Optional[float] = None,
    skill: Optional[str] = None,
    remote_only: bool = False,
    limit: int = 100,
) -> List[TalentPoolRecord]:
    """
    Advanced talent search with combined filters.
    """
    records = list_talents(
        domain=domain, status=status,
        min_experience=min_experience, skill_keyword=skill,
        search_text=keyword, limit=limit,
    )
    if max_experience is not None:
        records = [r for r in records if r.total_experience_years <= max_experience]
    if remote_only:
        records = [r for r in records if r.open_to_remote]
    return records


def get_skill_cloud(limit: int = 50) -> List[Tuple[str, int]]:
    """Aggregate all skills across the talent pool and return top-N frequencies."""
    all_skills: list = []
    for r in list_talents(limit=1000):
        all_skills.extend([s.strip().title() for s in r.skills if s.strip()])
    return Counter(all_skills).most_common(limit)


def get_domain_seniority_matrix() -> Dict[str, Dict[str, int]]:
    """Return counts per (domain, seniority)."""
    matrix: Dict[str, Dict[str, int]] = {}
    for r in list_talents(limit=1000):
        d = r.domain or "Unspecified"
        s = r.seniority_level or "Unspecified"
        matrix.setdefault(d, {})[s] = matrix.setdefault(d, {}).get(s, 0) + 1
    return matrix


def anonymize_record(r: TalentPoolRecord) -> TalentPoolRecord:
    """Return a copy with PII removed (for public/open browsing)."""
    return TalentPoolRecord(
        id=r.id,
        candidate_name=r.anonymized_name or "Anonymous Candidate",
        anonymized_name=r.anonymized_name or "Anonymous Candidate",
        domain=r.domain,
        seniority_level=r.seniority_level,
        total_experience_years=r.total_experience_years,
        skills=r.skills,
        education=r.education,
        certifications=r.certifications,
        work_summary=r.work_summary,
        project_summary=r.project_summary,
        location=r.location,
        open_to_remote=r.open_to_remote,
        status=r.status,
        tags=r.tags,
        created_at=r.created_at,
        updated_at=r.updated_at,
        raw_profile=None,
    )


def generate_open_resume_card(r: TalentPoolRecord, anonymize: bool = True) -> Dict[str, Any]:
    """
    Produce a clean, shareable card (dict) for open resume display.
    Used by the frontend to render anonymized public resumes.
    """
    rec = anonymize_record(r) if anonymize else r
    exp_level = (
        "Entry (<2y)" if rec.total_experience_years < 2
        else "Mid (2-5y)" if rec.total_experience_years < 5
        else "Senior (5-10y)" if rec.total_experience_years < 10
        else "Lead (>10y)"
    )
    return {
        "id": rec.id,
        "display_name": rec.candidate_name,
        "headline": (
            f"{rec.seniority_level or 'Professional'} · {rec.domain or 'General'}"
            f" · {rec.total_experience_years:.1f}y experience"
        ),
        "experience_level": exp_level,
        "domain": rec.domain,
        "seniority": rec.seniority_level,
        "years": rec.total_experience_years,
        "location": rec.location or "Not specified",
        "open_to_remote": rec.open_to_remote,
        "availability": rec.status.value,
        "skills": rec.skills,
        "education": rec.education,
        "certifications": rec.certifications,
        "tags": rec.tags,
        "work_summary": rec.work_summary,
        "project_summary": rec.project_summary,
        "updated_at": rec.updated_at.strftime("%b %d, %Y") if rec.updated_at else "",
    }


def export_talent_pool_json(
    anonymize: bool = True,
    records: Optional[List[TalentPoolRecord]] = None,
) -> List[Dict[str, Any]]:
    """Export the pool to shareable JSON (anonymized by default)."""
    if records is None:
        records = list_talents(limit=10000)
    return [generate_open_resume_card(r, anonymize=anonymize) for r in records]

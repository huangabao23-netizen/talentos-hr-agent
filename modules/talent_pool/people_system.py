"""
People system adapter placeholders.

This module is the integration boundary for a company People / ATS talent pool.
It is intentionally configuration-driven because the real internal API contract
is not known yet. Fill the PEOPLE_* variables in `.env`, then adjust the field
mapping here to match the actual response schema.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib import error, parse, request

from models.schemas import TalentPoolRecord, TalentPoolStatus
from utils.db import add_talent


def people_system_enabled() -> bool:
    return bool(os.environ.get("PEOPLE_API_BASE_URL", "").strip())


def search_people_talents(
    keywords: List[str],
    department: str = "",
    location: str = "",
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search people-system talent records.

    Expected default endpoint:
    GET {PEOPLE_API_BASE_URL}{PEOPLE_API_SEARCH_ENDPOINT}?q=...&department=...&location=...&limit=...
    """
    if not people_system_enabled():
        return []

    query = " ".join([kw for kw in keywords if kw]).strip()
    params = parse.urlencode({
        "q": query,
        "department": department,
        "location": location,
        "limit": max(1, min(limit, 100)),
    })
    endpoint = os.environ.get("PEOPLE_API_SEARCH_ENDPOINT", "/api/talents/search").strip()
    data = _people_get_json(f"{_people_url(endpoint)}?{params}")
    return _extract_people_items(data)


def get_people_profile(people_id: str) -> Dict[str, Any]:
    """Fetch one people-system profile by ID.

    Expected default endpoint:
    GET {PEOPLE_API_BASE_URL}{PEOPLE_API_PROFILE_ENDPOINT}
    where PEOPLE_API_PROFILE_ENDPOINT can contain `{people_id}`.
    """
    if not people_system_enabled() or not people_id:
        return {}

    endpoint = os.environ.get("PEOPLE_API_PROFILE_ENDPOINT", "/api/talents/{people_id}").strip()
    endpoint = endpoint.replace("{people_id}", parse.quote(str(people_id)))
    return _people_get_json(_people_url(endpoint))


def get_people_candidate_status(people_id: str) -> Dict[str, Any]:
    """Fetch candidate process/status from People / ATS.

    Expected default endpoint:
    GET {PEOPLE_API_BASE_URL}{PEOPLE_API_STATUS_ENDPOINT}
    where PEOPLE_API_STATUS_ENDPOINT can contain `{people_id}`.
    """
    if not people_system_enabled() or not people_id:
        return {}

    endpoint = os.environ.get("PEOPLE_API_STATUS_ENDPOINT", "/api/talents/{people_id}/status").strip()
    endpoint = endpoint.replace("{people_id}", parse.quote(str(people_id)))
    return _people_get_json(_people_url(endpoint))


def import_people_profile_to_local_pool(people_id: str) -> Optional[int]:
    """Fetch one People profile and store it into the local SQLite talent pool."""
    profile = get_people_profile(people_id)
    if not profile:
        return None
    record = people_record_to_talent_pool(profile)
    return add_talent(record)


def people_record_to_talent_pool(record: Dict[str, Any]) -> TalentPoolRecord:
    """Map a People-system record into the local TalentPoolRecord schema."""
    candidate_name = (
        record.get("candidate_name")
        or record.get("name")
        or record.get("display_name")
        or "People 系统候选人"
    )
    skills = _as_list(record.get("skills") or record.get("skill_tags") or record.get("tags"))
    education = _as_list(record.get("education") or record.get("schools"))
    tags = list(dict.fromkeys(_as_list(record.get("tags")) + ["People系统", "内部人才库"]))

    return TalentPoolRecord(
        candidate_name=candidate_name,
        anonymized_name=record.get("anonymized_name", ""),
        domain=record.get("domain") or record.get("job_family") or record.get("talent_direction", ""),
        seniority_level=record.get("seniority_level") or record.get("level", ""),
        total_experience_years=float(record.get("total_experience_years") or record.get("experience_years") or 0),
        skills=skills,
        education=education,
        certifications=_as_list(record.get("certifications")),
        work_summary=record.get("work_summary") or record.get("summary") or record.get("headline", ""),
        project_summary=record.get("project_summary") or record.get("projects", ""),
        location=record.get("location", ""),
        open_to_remote=bool(record.get("open_to_remote", True)),
        status=TalentPoolStatus.ACTIVE,
        tags=tags,
        raw_profile=json.dumps(record, ensure_ascii=False, indent=2),
    )


def _people_get_json(url: str) -> Dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "TalentOS-People-Adapter",
    }
    token = os.environ.get("PEOPLE_API_TOKEN", "").strip()
    if token:
        header_name = os.environ.get("PEOPLE_API_AUTH_HEADER", "Authorization").strip() or "Authorization"
        token_prefix = os.environ.get("PEOPLE_API_TOKEN_PREFIX", "Bearer").strip()
        headers[header_name] = f"{token_prefix} {token}".strip()

    try:
        req = request.Request(url, headers=headers)
        with request.urlopen(req, timeout=int(os.environ.get("PEOPLE_API_TIMEOUT", "15"))) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}


def _people_url(endpoint: str) -> str:
    base_url = os.environ.get("PEOPLE_API_BASE_URL", "").strip().rstrip("/")
    endpoint = "/" + endpoint.strip().lstrip("/")
    return f"{base_url}{endpoint}"


def _extract_people_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ["items", "data", "results", "talents", "candidates"]:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.replace("，", ",").replace("、", ",").split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


__all__ = [
    "people_system_enabled",
    "search_people_talents",
    "get_people_profile",
    "get_people_candidate_status",
    "import_people_profile_to_local_pool",
    "people_record_to_talent_pool",
]

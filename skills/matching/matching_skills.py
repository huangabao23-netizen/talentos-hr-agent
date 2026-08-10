"""
Markdown-backed matching Skill loader.

Human-maintained Skill content lives in `skills/matching/*.md`.
This module only parses those Markdown files and exposes the same runtime
structure used by the scoring algorithm.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Optional


SKILL_DIR = Path(__file__).resolve().parent

SECTION_FIELD_MAP = {
    "硬性检查": "hard_checks",
    "正向信号": "positive_signals",
    "负向信号": "negative_signals",
    "证据规则": "evidence_rules",
    "面试关注点": "interview_focus",
}

DEFAULT_DIMENSION_KEYS = [
    "hard_skills_match",
    "business_project_match",
    "seniority_level_match",
    "education_school_match",
    "soft_requirements_match",
    "risk_signal_control",
]


def _parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    raw_meta = parts[1].strip()
    body = parts[2].strip()
    meta = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def _section_text(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.find(marker)
    if start < 0:
        return ""
    start = body.find("\n", start)
    if start < 0:
        return ""
    next_heading = body.find("\n## ", start + 1)
    if next_heading < 0:
        return body[start:].strip()
    return body[start:next_heading].strip()


def _parse_bullets(body: str, heading: str) -> list[str]:
    section = _section_text(body, heading)
    items = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _parse_weight(value: str) -> float:
    cleaned = value.strip().replace("%", "")
    if not cleaned:
        return 0.0
    number = float(cleaned)
    return number / 100 if number > 1 else number


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_weights(body: str) -> tuple[dict, dict, list[str]]:
    section = _section_text(body, "评分权重")
    weights = {}
    labels = {}
    keys = []

    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if set(stripped.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
            continue
        cells = _split_table_row(stripped)
        if len(cells) < 3 or cells[0] == "dimension_key":
            continue
        dim_key, label, weight = cells[0], cells[1], cells[2]
        if not dim_key:
            continue
        keys.append(dim_key)
        labels[dim_key] = label
        weights[dim_key] = _parse_weight(weight)

    return weights, labels, keys


def _load_skill_file(path: Path) -> dict:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    weights, labels, dimension_keys = _parse_weights(body)
    skill = {
        "skill_id": meta["skill_id"],
        "skill_name": meta["skill_name"],
        "job_family": meta.get("job_family", "开发"),
        "hiring_type": meta.get("hiring_type", "社招"),
        "version": meta.get("version", "v1"),
        "focus_summary": meta.get("focus_summary", ""),
        "dimension_weights": weights,
        "dimension_labels": labels,
        "_dimension_keys": dimension_keys,
        "_source_path": str(path),
    }

    for heading, field_name in SECTION_FIELD_MAP.items():
        skill[field_name] = _parse_bullets(body, heading)

    return skill


def load_matching_skills() -> dict:
    skills = {}
    for path in sorted(SKILL_DIR.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        skill = _load_skill_file(path)
        skills[skill["skill_id"]] = skill
    if not skills:
        raise RuntimeError(f"No matching Skill Markdown files found in {SKILL_DIR}")
    return skills


MATCHING_SKILLS = load_matching_skills()

_first_skill = next(iter(MATCHING_SKILLS.values()))
DIMENSION_KEYS = _first_skill.get("_dimension_keys") or DEFAULT_DIMENSION_KEYS


def normalize_hiring_type(hiring_type: Optional[str]) -> str:
    value = (hiring_type or "").strip()
    if value in {"校招", "实习"}:
        return "校招"
    return "社招"


def get_matching_skill(job_family: Optional[str] = "开发", hiring_type: Optional[str] = "社招") -> dict:
    family = (job_family or "开发").strip() or "开发"
    normalized_type = normalize_hiring_type(hiring_type)
    for skill in MATCHING_SKILLS.values():
        if skill.get("job_family") == family and normalize_hiring_type(skill.get("hiring_type")) == normalized_type:
            return deepcopy(skill)
    return get_matching_skill_by_id("dev_social_v1")


def get_matching_skill_by_id(skill_id: Optional[str]) -> dict:
    if skill_id in MATCHING_SKILLS:
        return deepcopy(MATCHING_SKILLS[skill_id])
    return deepcopy(next(iter(MATCHING_SKILLS.values())))


def weights_for_skill(skill: Optional[dict]) -> dict:
    selected = (skill or {}).get("dimension_weights") or {}
    default_skill = get_matching_skill_by_id("dev_social_v1")
    defaults = default_skill.get("dimension_weights", {})
    weights = {key: float(selected.get(key, defaults.get(key, 0))) for key in DIMENSION_KEYS}
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}

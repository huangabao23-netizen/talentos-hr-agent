"""
JD Generation Agent.
Generates a public JD, internal job profile, and screening strategy from:
- business department needs
- historical offer patterns
- HR soft requirements
- external school priority list
"""

import json
import logging
from typing import Dict, List

from models.schemas import GeneratedJD
from utils.llm_client import chat_completion
from utils.security import sanitize_input

logger = logging.getLogger(__name__)


_FIELD_INFERENCE_PROMPT = """You are a recruiting operations assistant.
Extract structured job requirements from a short natural-language hiring request.

Return ONLY valid JSON with these keys:
{
  "job_title": string,
  "job_level": string,
  "recruitment_type": string,
  "department": string,
  "location": string,
  "hc_count": integer,
  "arrival_time": string,
  "salary_range": string,
  "business_background": string,
  "role_problem": string,
  "core_responsibilities": string,
  "key_projects": string,
  "success_criteria": string,
  "collaborators": [string],
  "tech_stack": string,
  "must_have_skills": string,
  "nice_to_have_skills": string,
  "min_years": integer,
  "project_experience": string,
  "industry_experience": string,
  "hr_soft_requirements": string,
  "candidate_motivation": string,
  "negative_signals": string,
  "stability_requirement": string,
  "communication_requirement": string,
  "manual_offer_patterns": string,
  "school_priority_rule": string,
  "missing_fields": [string]
}

Rules:
- Infer reasonable defaults when the user is brief.
- If level is unclear, infer from words like junior/intermediate/senior/expert/manager; default to "中级".
- If recruitment type is unclear, default to "社招".
- If years are unclear, use 1 for 初级, 3 for 中级, 5 for 高级, 8 for 专家, 0 for 校招.
- If school list priority is mentioned, use "仅作为加分项（推荐）" unless the user explicitly says hard filter.
- Keep all Chinese labels exactly compatible with the UI options when possible.
"""


_SYSTEM_PROMPT = """You are a senior recruiting strategy partner.
Generate a first-draft job description and an internal screening profile.

Return ONLY valid JSON with this exact schema:
{
  "public_jd": "candidate-facing JD in clear sections",
  "internal_profile": {
    "job_title": string,
    "department": string,
    "business_context": string,
    "must_have_skills": [string],
    "nice_to_have_skills": [string],
    "soft_requirements": [string],
    "negative_signals": [string],
    "school_priority_rule": string,
    "historical_offer_patterns": [string]
  },
  "screening_strategy": [string],
  "scoring_weights": {
    "hard_skills": integer,
    "business_context": integer,
    "historical_offer_similarity": integer,
    "soft_requirements": integer,
    "risk_penalty": integer
  },
  "interview_focus": [string]
}

Rules:
- Use historical offer data as evidence, not as absolute truth.
- Treat the R&D school list as priority boosting, not as a hard rejection rule.
- If a candidate is outside the school list, allow strong project/business experience to compensate.
- Keep public_jd suitable for candidates; keep internal_profile and screening_strategy for HR only.
- public_jd MUST be a single markdown-style string, not a nested object.
- Do not fabricate concrete historical facts that are not present in the input.
"""


def infer_jd_fields(
    hiring_request: str,
    offer_data_summary: str = "",
    school_list_summary: str = "",
    jd_style: str = "标准正式",
    screening_strictness: str = "标准",
) -> Dict:
    clean_request = sanitize_input(hiring_request)
    if not clean_request.strip():
        raise ValueError("Please describe the hiring need first.")

    user_prompt = f"""
HIRING REQUEST:
{clean_request}

JD STYLE:
{sanitize_input(jd_style)}

SCREENING STRICTNESS:
{sanitize_input(screening_strictness)}

HISTORICAL OFFER DATA SUMMARY:
{sanitize_input(offer_data_summary) or "No historical offer data provided."}

R&D SCHOOL PRIORITY LIST SUMMARY:
{sanitize_input(school_list_summary) or "No school list provided."}
"""
    raw = chat_completion(
        max_tokens=1800,
        messages=[
            {"role": "system", "content": _FIELD_INFERENCE_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = _strip_json_fence(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JD field inference JSON decode error: %s\nRaw: %s", e, raw[:1000])
        raise ValueError(f"JD field inference returned invalid JSON: {e}") from e
    return _normalize_inferred_fields(data)


def generate_jd_package(
    job_title: str,
    department: str,
    business_needs: str = "",
    hr_soft_requirements: str = "",
    offer_data_summary: str = "",
    school_list_summary: str = "",
    job_level: str = "",
    recruitment_type: str = "",
    location: str = "",
    hc_count: str = "",
    arrival_time: str = "",
    salary_range: str = "",
    business_background: str = "",
    role_problem: str = "",
    core_responsibilities: str = "",
    key_projects: str = "",
    success_criteria: str = "",
    collaborators: str = "",
    tech_stack: str = "",
    must_have_skills: str = "",
    nice_to_have_skills: str = "",
    min_years: str = "",
    project_experience: str = "",
    industry_experience: str = "",
    candidate_motivation: str = "",
    negative_signals: str = "",
    stability_requirement: str = "",
    communication_requirement: str = "",
    manual_offer_patterns: str = "",
    school_priority_rule: str = "",
) -> GeneratedJD:
    clean_inputs = {
        "job_title": sanitize_input(job_title),
        "department": sanitize_input(department),
        "business_needs": sanitize_input(business_needs),
        "hr_soft_requirements": sanitize_input(hr_soft_requirements),
        "offer_data_summary": sanitize_input(offer_data_summary),
        "school_list_summary": sanitize_input(school_list_summary),
        "job_level": sanitize_input(job_level),
        "recruitment_type": sanitize_input(recruitment_type),
        "location": sanitize_input(location),
        "hc_count": sanitize_input(str(hc_count)),
        "arrival_time": sanitize_input(arrival_time),
        "salary_range": sanitize_input(salary_range),
        "business_background": sanitize_input(business_background),
        "role_problem": sanitize_input(role_problem),
        "core_responsibilities": sanitize_input(core_responsibilities),
        "key_projects": sanitize_input(key_projects),
        "success_criteria": sanitize_input(success_criteria),
        "collaborators": sanitize_input(collaborators),
        "tech_stack": sanitize_input(tech_stack),
        "must_have_skills": sanitize_input(must_have_skills),
        "nice_to_have_skills": sanitize_input(nice_to_have_skills),
        "min_years": sanitize_input(str(min_years)),
        "project_experience": sanitize_input(project_experience),
        "industry_experience": sanitize_input(industry_experience),
        "candidate_motivation": sanitize_input(candidate_motivation),
        "negative_signals": sanitize_input(negative_signals),
        "stability_requirement": sanitize_input(stability_requirement),
        "communication_requirement": sanitize_input(communication_requirement),
        "manual_offer_patterns": sanitize_input(manual_offer_patterns),
        "school_priority_rule": sanitize_input(school_priority_rule),
    }

    if not clean_inputs["job_title"].strip():
        raise ValueError("Job title is required.")
    if not (
        clean_inputs["business_needs"].strip()
        or clean_inputs["business_background"].strip()
        or clean_inputs["role_problem"].strip()
    ):
        raise ValueError("Business context is required.")

    user_prompt = f"""
## BASIC ROLE INFORMATION
JOB TITLE:
{clean_inputs["job_title"]}

JOB LEVEL:
{clean_inputs["job_level"] or "Not specified"}

RECRUITMENT TYPE:
{clean_inputs["recruitment_type"] or "Not specified"}

DEPARTMENT:
{clean_inputs["department"] or "Not specified"}

LOCATION:
{clean_inputs["location"] or "Not specified"}

HC COUNT:
{clean_inputs["hc_count"] or "Not specified"}

EXPECTED ARRIVAL TIME:
{clean_inputs["arrival_time"] or "Not specified"}

SALARY RANGE (internal only, do not expose unless appropriate):
{clean_inputs["salary_range"] or "Not specified"}

## BUSINESS NEEDS AND RESPONSIBILITIES
BUSINESS BACKGROUND:
{clean_inputs["business_background"] or clean_inputs["business_needs"] or "Not specified"}

PROBLEM THIS ROLE NEEDS TO SOLVE:
{clean_inputs["role_problem"] or "Not specified"}

CORE RESPONSIBILITIES:
{clean_inputs["core_responsibilities"] or "Not specified"}

KEY PROJECTS IN THE NEXT 3-6 MONTHS:
{clean_inputs["key_projects"] or "Not specified"}

SUCCESS CRITERIA:
{clean_inputs["success_criteria"] or "Not specified"}

CROSS-FUNCTIONAL COLLABORATORS:
{clean_inputs["collaborators"] or "Not specified"}

## HARD SKILLS AND PROJECT EXPERIENCE
TECH STACK:
{clean_inputs["tech_stack"] or "Not specified"}

MUST-HAVE SKILLS:
{clean_inputs["must_have_skills"] or "Not specified"}

NICE-TO-HAVE SKILLS:
{clean_inputs["nice_to_have_skills"] or "Not specified"}

MINIMUM YEARS OF EXPERIENCE:
{clean_inputs["min_years"] or "Infer from job level if not specified."}

REQUIRED PROJECT EXPERIENCE:
{clean_inputs["project_experience"] or "Not specified"}

INDUSTRY EXPERIENCE PREFERENCE:
{clean_inputs["industry_experience"] or "Not specified"}

## SOFT REQUIREMENTS AND RISK SIGNALS
HR SOFT REQUIREMENTS:
{clean_inputs["hr_soft_requirements"] or "Not specified"}

CANDIDATE MOTIVATION REQUIREMENTS:
{clean_inputs["candidate_motivation"] or "Not specified"}

NEGATIVE SIGNALS / NOT SUITABLE:
{clean_inputs["negative_signals"] or "Not specified"}

STABILITY REQUIREMENT:
{clean_inputs["stability_requirement"] or "Not specified"}

COMMUNICATION REQUIREMENT:
{clean_inputs["communication_requirement"] or "Not specified"}

HISTORICAL OFFER DATA SUMMARY:
{clean_inputs["offer_data_summary"] or "No historical offer data provided."}

MANUAL HISTORICAL OFFER PATTERNS:
{clean_inputs["manual_offer_patterns"] or "Not specified"}

R&D SCHOOL PRIORITY LIST SUMMARY:
{clean_inputs["school_list_summary"] or "No school list provided."}

SCHOOL PRIORITY RULE:
{clean_inputs["school_priority_rule"] or "Use as bonus signal, not hard rejection."}
"""

    raw = chat_completion(
        max_tokens=3000,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = _strip_json_fence(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JD generator JSON decode error: %s\nRaw: %s", e, raw[:1000])
        raise ValueError(f"JD generator returned invalid JSON: {e}") from e

    data = _normalize_generated_jd(data)
    try:
        return GeneratedJD(**data)
    except Exception as e:
        logger.error("JD generator validation error: %s", e)
        raise ValueError(f"Generated JD validation failed: {e}") from e


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _normalize_generated_jd(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Generated JD output must be a JSON object.")

    public_jd = data.get("public_jd", "")
    if isinstance(public_jd, dict):
        data["public_jd"] = _dict_to_markdown(public_jd)
    elif isinstance(public_jd, list):
        data["public_jd"] = "\n\n".join(str(item) for item in public_jd)
    else:
        data["public_jd"] = str(public_jd)

    for key in ("screening_strategy", "interview_focus"):
        value = data.get(key, [])
        if isinstance(value, str):
            data[key] = [value]
        elif not isinstance(value, list):
            data[key] = []

    if not isinstance(data.get("internal_profile", {}), dict):
        data["internal_profile"] = {"summary": str(data.get("internal_profile", ""))}
    if not isinstance(data.get("scoring_weights", {}), dict):
        data["scoring_weights"] = {}

    return data


def _normalize_inferred_fields(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Inferred JD fields must be a JSON object.")

    allowed_levels = {"校招", "初级", "中级", "高级", "专家", "管理岗"}
    allowed_types = {"社招", "校招", "实习", "外包", "转岗"}
    allowed_arrivals = {"不限", "立即", "1个月内", "2个月内", "3个月内"}
    allowed_intensity = {"不限", "低", "中", "高"}
    allowed_school_rules = {"仅作为加分项（推荐）", "强优先推荐", "作为硬性筛选条件"}
    allowed_collaborators = {"产品", "测试", "算法", "风控", "运营", "数据团队", "设计", "销售", "客户成功"}

    normalized = {}
    for key, value in data.items():
        if isinstance(value, str):
            normalized[key] = sanitize_input(value)
        elif isinstance(value, list):
            normalized[key] = [sanitize_input(str(item)) for item in value if str(item).strip()]
        else:
            normalized[key] = value

    normalized["job_level"] = normalized.get("job_level") if normalized.get("job_level") in allowed_levels else "中级"
    normalized["recruitment_type"] = normalized.get("recruitment_type") if normalized.get("recruitment_type") in allowed_types else "社招"
    normalized["arrival_time"] = normalized.get("arrival_time") if normalized.get("arrival_time") in allowed_arrivals else "不限"
    normalized["stability_requirement"] = normalized.get("stability_requirement") if normalized.get("stability_requirement") in allowed_intensity else "不限"
    normalized["communication_requirement"] = normalized.get("communication_requirement") if normalized.get("communication_requirement") in allowed_intensity else "不限"
    normalized["school_priority_rule"] = normalized.get("school_priority_rule") if normalized.get("school_priority_rule") in allowed_school_rules else "仅作为加分项（推荐）"

    collaborators = normalized.get("collaborators", [])
    if isinstance(collaborators, str):
        collaborators = [x.strip() for x in collaborators.replace("，", ",").split(",")]
    normalized["collaborators"] = [x for x in collaborators if x in allowed_collaborators]

    try:
        normalized["hc_count"] = max(0, int(normalized.get("hc_count") or 1))
    except Exception:
        normalized["hc_count"] = 1
    try:
        normalized["min_years"] = max(0, int(normalized.get("min_years") or 0))
    except Exception:
        normalized["min_years"] = 0

    if not normalized.get("job_title"):
        normalized["job_title"] = "待定岗位"
    if not normalized.get("department"):
        normalized["department"] = "待定部门"
    if not normalized.get("business_background"):
        normalized["business_background"] = normalized.get("role_problem", "") or "根据岗位需求补充业务背景。"
    if not normalized.get("role_problem"):
        normalized["role_problem"] = normalized.get("business_background", "") or "根据业务目标补充岗位要解决的问题。"
    if not normalized.get("core_responsibilities"):
        normalized["core_responsibilities"] = "围绕业务目标完成核心模块设计、开发、交付和持续优化。"
    if not normalized.get("tech_stack"):
        normalized["tech_stack"] = "根据岗位方向补充核心技术栈。"
    if not normalized.get("must_have_skills"):
        normalized["must_have_skills"] = "具备岗位所需的核心专业能力、项目经验和问题解决能力。"
    if not isinstance(normalized.get("missing_fields"), list):
        normalized["missing_fields"] = []

    return normalized


def _dict_to_markdown(value: dict) -> str:
    sections = []
    for key, item in value.items():
        title = str(key).replace("_", " ").title()
        if isinstance(item, list):
            body = "\n".join(f"- {x}" for x in item)
        elif isinstance(item, dict):
            body = "\n".join(f"- {k}: {v}" for k, v in item.items())
        else:
            body = str(item)
        sections.append(f"## {title}\n{body}")
    return "\n\n".join(sections)


def summarize_table_records(records: List[Dict], title: str, max_rows: int = 30) -> str:
    if not records:
        return ""
    lines = [f"{title}: {len(records)} rows provided. Showing up to {max_rows} rows."]
    for idx, row in enumerate(records[:max_rows], start=1):
        compact = {str(k): str(v)[:120] for k, v in row.items() if str(v).strip() and str(v) != "nan"}
        lines.append(f"{idx}. {compact}")
    return "\n".join(lines)

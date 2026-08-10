"""
Profile Parser Agent.
Converts raw resume text (from PDF/DOCX/LinkedIn JSON) into a structured ParsedProfile.
"""

import json
import logging
import re
from pathlib import Path
from models.schemas import ParsedProfile
from utils.llm_client import chat_completion
from utils.security import sanitize_input

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a precise resume parser. Extract structured information from
a candidate's resume or LinkedIn profile and return valid JSON only.

Return ONLY a JSON object with this exact schema:
{
  "candidate_name": string,
  "email": string or null,
  "skills": [string, ...],
  "total_experience_years": float,
  "education": [string, ...],
  "certifications": [string, ...],
  "work_history": [string, ...],
  "projects": [string, ...],
  "summary": string
}

Rules:
- candidate_name: Full name only. If not found, use "Unknown Candidate".
- email: extract if present, else null. Never fabricate.
- skills: ALL technical and soft skills mentioned anywhere in the document.
- total_experience_years: Sum of all work experience. Use 0 if none found.
- education: Each entry as "<Degree> in <Field> from <Institution> (<Year>)"
- work_history: Each entry as "<Title> at <Company> (<Duration>): <1 line summary>"
- projects: Each as "<Project Name>: <1 line description>"
- summary: 2-3 sentence professional summary of the candidate.
- Return valid JSON only — no markdown, no explanation."""


def parse_profile(raw_text: str, source_file: str = "") -> ParsedProfile:
    """
    Parse a resume or LinkedIn profile text into a structured ParsedProfile.
    """
    clean_text = sanitize_input(raw_text)
    if not clean_text.strip():
        raise ValueError(f"Profile text is empty for: {source_file}")

    try:
        raw = chat_completion(
            max_tokens=2000,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Parse this candidate profile:\n\n{clean_text}"}
            ]
        )
    except Exception as e:
        logger.error(f"Profile parser LLM error for {source_file}: {e}")
        return _fallback_parse_profile(clean_text, source_file, f"LLM call failed: {e}")

    raw = _strip_markdown_json(raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        extracted = _extract_json_object(raw)
        if extracted:
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError:
                logger.error(f"Profile parser JSON error for {source_file}: {e}")
                return _fallback_parse_profile(clean_text, source_file, f"LLM returned invalid JSON: {e}")
        else:
            logger.error(f"Profile parser JSON error for {source_file}: {e}")
            return _fallback_parse_profile(clean_text, source_file, f"LLM returned invalid JSON: {e}")

    try:
        profile = ParsedProfile(**data, source_file=source_file)
        return profile
    except Exception as e:
        logger.error(f"Profile validation error for {source_file}: {e}")
        return _fallback_parse_profile(clean_text, source_file, f"Profile validation failed: {e}")


def _strip_markdown_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _extract_json_object(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1].strip()
    return ""


def _fallback_parse_profile(clean_text: str, source_file: str, reason: str) -> ParsedProfile:
    """Best-effort local parser used when the LLM output is malformed."""
    logger.warning("Using fallback profile parser for %s: %s", source_file, reason)
    lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    email_match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", clean_text)
    candidate_name = _guess_candidate_name(lines, source_file)
    skills = _guess_skills(clean_text)
    education = _guess_lines(clean_text, ["大学", "学院", "university", "college", "bachelor", "master", "phd", "硕士", "本科", "博士"])
    work_history = _guess_lines(clean_text, ["公司", "实习", "工作", "engineer", "developer", "intern", "research", "算法", "研发"])
    projects = _guess_lines(clean_text, ["项目", "project", "论文", "paper", "github", "竞赛", "比赛"])
    years = _guess_experience_years(clean_text)
    summary = "；".join(lines[:3])[:500] if lines else f"从 {source_file} 提取的简历文本，结构化信息有限。"

    return ParsedProfile(
        candidate_name=candidate_name,
        email=email_match.group(0) if email_match else None,
        skills=skills,
        total_experience_years=years,
        education=education[:6],
        certifications=[],
        work_history=work_history[:8],
        projects=projects[:8],
        summary=summary,
        source_file=source_file,
    )


def _guess_candidate_name(lines: list[str], source_file: str) -> str:
    for line in lines[:8]:
        cleaned = re.sub(r"^(姓名|Name)[:：]\s*", "", line, flags=re.IGNORECASE).strip()
        if 2 <= len(cleaned) <= 40 and not any(token in cleaned.lower() for token in ["email", "phone", "github", "http", "@"]):
            return cleaned
    stem = Path(source_file).stem.strip()
    return stem or "Unknown Candidate"


def _guess_skills(text: str) -> list[str]:
    known_skills = [
        "Python", "Java", "C++", "Go", "Golang", "JavaScript", "TypeScript", "SQL",
        "PyTorch", "TensorFlow", "Transformers", "LangChain", "RAG", "LLM", "NLP",
        "CV", "机器学习", "深度学习", "推荐系统", "搜索", "广告算法", "大模型",
        "多模态", "数据挖掘", "Spark", "Flink", "Kafka", "Docker", "Kubernetes",
        "React", "Vue", "Node.js", "Django", "FastAPI",
    ]
    lower_text = text.lower()
    found = []
    for skill in known_skills:
        if skill.lower() in lower_text:
            found.append(skill)
    return list(dict.fromkeys(found))


def _guess_lines(text: str, markers: list[str]) -> list[str]:
    results = []
    lowered_markers = [marker.lower() for marker in markers]
    for line in [line.strip() for line in text.splitlines() if line.strip()]:
        lowered = line.lower()
        if any(marker in lowered for marker in lowered_markers):
            results.append(line[:240])
    return results


def _guess_experience_years(text: str) -> float:
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:年|years?|yrs?)\s*(?:工作|经验|experience)?",
        r"经验\s*(\d+(?:\.\d+)?)\s*(?:年|years?|yrs?)",
    ]
    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                value = float(match.group(1))
                if 0 <= value <= 50:
                    values.append(value)
            except ValueError:
                pass
    return max(values) if values else 0.0

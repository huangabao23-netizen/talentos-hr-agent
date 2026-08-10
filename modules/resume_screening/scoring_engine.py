"""
Scoring Engine.
Scores each candidate against the JD using:
1. LLM reasoning (primary) — produces dimension scores with justifications
2. Embedding similarity (secondary) — cosine similarity for skills match signal

Pydantic validation enforces score bounds on every response.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional
import numpy as np
from models.schemas import ParsedJD, ParsedProfile, CandidateScore, DimensionScore
from skills.matching.matching_skills import get_matching_skill, weights_for_skill
from utils.llm_client import chat_completion
from utils.security import sanitize_input

logger = logging.getLogger(__name__)

_embedder = None


_SOFT_SIGNAL_TERMS = [
    "owner", "ownership", "负责", "主导", "推动", "协作", "沟通", "跨团队",
    "复盘", "主动", "稳定性", "抗压", "学习", "lead", "collaboration",
    "communication", "stakeholder", "mentoring",
]

_RISK_TERMS = [
    "gap", "空窗", "离职", "短期", "频繁", "外包", "contract", "intern only",
    "basic", "简单", "crud", "unclear", "不明确",
]

_SENIORITY_TERMS = {
    "lead": 1.0,
    "principal": 1.0,
    "staff": 1.0,
    "architect": 1.0,
    "senior": 0.7,
    "高级": 0.7,
    "资深": 0.8,
    "专家": 1.0,
    "负责人": 0.8,
    "主导": 0.6,
}


def _get_embedder():
    """Lazy-load SentenceTransformer — only loaded once."""
    global _embedder
    if os.environ.get("ENABLE_EMBEDDING_SIGNAL", "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            _embedder = SentenceTransformer(model_name)
            logger.info("SentenceTransformer loaded: %s", model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed. Embedding signal disabled.")
            _embedder = False
    return _embedder if _embedder else None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _embedding_skills_signal(jd: ParsedJD, profile: ParsedProfile) -> Optional[float]:
    """
    Returns a 0-10 embedding similarity signal for skills overlap.
    Returns None if embedder is unavailable.
    """
    embedder = _get_embedder()
    if not embedder:
        return None

    jd_text = " ".join(jd.required_skills + jd.preferred_skills)
    candidate_text = " ".join(profile.skills)

    if not jd_text.strip() or not candidate_text.strip():
        return None

    embs = embedder.encode([jd_text, candidate_text])
    sim = _cosine_similarity(embs[0], embs[1])
    return round(sim * 10, 1)


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[\s\-_/.+#]+", "", text)
    return text


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]{1,}|[\u4e00-\u9fff]{2,}", text or "")
        if len(token.strip()) >= 2
    }


def _profile_text(profile: ParsedProfile) -> str:
    return "\n".join([
        " ".join(profile.skills),
        " ".join(profile.education),
        " ".join(profile.certifications),
        " ".join(profile.work_history),
        " ".join(profile.projects),
        profile.summary or "",
    ])


def _skill_matches(required: list[str], candidate_text: str, candidate_skills: list[str]) -> tuple[list[str], list[str], float]:
    if not required:
        return [], [], 1.0

    normalized_text = _normalize_text(candidate_text + " " + " ".join(candidate_skills))
    matched = []
    missing = []
    for skill in required:
        norm_skill = _normalize_text(skill)
        if not norm_skill:
            continue
        if norm_skill in normalized_text:
            matched.append(skill)
        else:
            skill_tokens = [_normalize_text(t) for t in _tokenize(skill)]
            if skill_tokens and any(t in normalized_text for t in skill_tokens):
                matched.append(skill)
            else:
                missing.append(skill)
    total = len(matched) + len(missing)
    coverage = len(matched) / total if total else 1.0
    return matched, missing, round(coverage, 3)


def _keyword_overlap_score(source_terms: list[str], target_text: str) -> tuple[float, list[str]]:
    source_tokens = set()
    for term in source_terms:
        source_tokens.update(_tokenize(term))
    source_tokens = {t for t in source_tokens if len(t) >= 2}
    if not source_tokens:
        return 5.0, []

    target_tokens = _tokenize(target_text)
    matched = sorted(source_tokens & target_tokens)
    ratio = len(matched) / max(len(source_tokens), 1)
    return round(min(10.0, 2.5 + ratio * 7.5), 1), matched[:12]


def _education_score(required_education: str, education_entries: list[str]) -> tuple[float, list[str], list[str]]:
    required = (required_education or "").lower()
    education_text = " ".join(education_entries).lower()
    evidence = []
    gaps = []

    if not education_text.strip():
        return 4.0, [], ["Education background is not clearly listed"]

    score = 6.0
    if any(term in education_text for term in ["phd", "doctor", "博士"]):
        score = 9.0
        evidence.append("Doctoral education signal found")
    elif any(term in education_text for term in ["master", "硕士", "mba", "研究生"]):
        score = 8.0
        evidence.append("Master-level education signal found")
    elif any(term in education_text for term in ["bachelor", "本科", "学士"]):
        score = 7.0
        evidence.append("Bachelor-level education signal found")

    if any(term in education_text for term in ["computer", "software", "计算机", "软件", "通信", "电子", "automation", "自动化"]):
        score = min(10.0, score + 1.0)
        evidence.append("Major appears relevant to R&D roles")

    if "master" in required or "硕士" in required or "研究生" in required:
        if not any(term in education_text for term in ["master", "硕士", "研究生", "phd", "博士", "doctor"]):
            score = min(score, 5.0)
            gaps.append("Required master-level education is not evident")
    elif "bachelor" in required or "本科" in required:
        if not any(term in education_text for term in ["bachelor", "本科", "学士", "master", "硕士", "研究生", "phd", "博士"]):
            score = min(score, 5.0)
            gaps.append("Required bachelor-level education is not evident")

    return round(score, 1), evidence, gaps


def _soft_signal_score(jd: ParsedJD, candidate_text: str) -> tuple[float, list[str]]:
    expected_terms = _SOFT_SIGNAL_TERMS + [
        s for s in jd.required_skills + jd.preferred_skills
        if any(term in s.lower() for term in ["communication", "collaboration", "ownership", "沟通", "协作", "owner", "稳定"])
    ]
    normalized = candidate_text.lower()
    matched = sorted({term for term in expected_terms if term.lower() in normalized})
    if not matched:
        return 5.0, []
    return round(min(10.0, 5.0 + len(matched) * 0.8), 1), matched[:8]


def _seniority_score(jd: ParsedJD, profile: ParsedProfile, candidate_text: str) -> tuple[float, list[str], list[str]]:
    min_years = jd.min_experience_years or 0
    years = profile.total_experience_years or 0
    evidence = []
    gaps = []

    if min_years <= 0:
        base = 6.5
    else:
        base = min(10.0, (years / max(min_years, 1)) * 7.5)
    if years >= min_years:
        evidence.append(f"Experience years meet baseline: {years:g} / {min_years:g}")
    else:
        gaps.append(f"Experience years below baseline: {years:g} / {min_years:g}")

    normalized = candidate_text.lower()
    seniority_bonus = 0.0
    matched_terms = []
    for term, bonus in _SENIORITY_TERMS.items():
        if term in normalized:
            seniority_bonus = max(seniority_bonus, bonus)
            matched_terms.append(term)
    if matched_terms:
        evidence.append(f"Seniority/ownership signals: {', '.join(matched_terms[:5])}")

    return round(min(10.0, base + seniority_bonus), 1), evidence, gaps


def _risk_score(
    jd: ParsedJD,
    profile: ParsedProfile,
    required_coverage: float,
    candidate_text: str,
) -> tuple[float, list[str]]:
    risks = []
    score = 9.0

    if required_coverage < 0.5:
        score -= 2.0
        risks.append("Must-have skill coverage is below 50%")
    elif required_coverage < 0.7:
        score -= 1.0
        risks.append("Must-have skill coverage is partial")

    if profile.total_experience_years < jd.min_experience_years:
        score -= 1.5
        risks.append("Experience years are below the JD baseline")

    if len(profile.work_history) <= 1 and profile.total_experience_years >= 3:
        score -= 0.8
        risks.append("Work history detail is thin relative to experience years")

    if len(profile.projects) == 0:
        score -= 0.8
        risks.append("No explicit project evidence parsed from resume")

    normalized = candidate_text.lower()
    matched_risk_terms = [term for term in _RISK_TERMS if term in normalized]
    if matched_risk_terms:
        score -= min(1.5, len(matched_risk_terms) * 0.4)
        risks.append(f"Possible risk terms found: {', '.join(matched_risk_terms[:5])}")

    if not risks:
        risks.append("No obvious risk signals")

    return round(max(0.0, min(10.0, score)), 1), risks


def _build_matching_baseline(
    jd: ParsedJD,
    profile: ParsedProfile,
    emb_signal: Optional[float],
    matching_skill: Optional[dict] = None,
) -> CandidateScore:
    matching_skill = matching_skill or get_matching_skill("开发", "社招")
    weights = weights_for_skill(matching_skill)
    candidate_text = _profile_text(profile)
    required_matched, required_missing, required_coverage = _skill_matches(
        jd.required_skills, candidate_text, profile.skills
    )
    preferred_matched, preferred_missing, preferred_coverage = _skill_matches(
        jd.preferred_skills, candidate_text, profile.skills
    )

    hard_skill_score = required_coverage * 8.0 + preferred_coverage * 1.5
    if emb_signal is not None:
        hard_skill_score = hard_skill_score * 0.85 + emb_signal * 0.15
    hard_skill_score = round(max(0.0, min(10.0, hard_skill_score)), 1)

    business_score, business_terms = _keyword_overlap_score(
        [jd.domain] + jd.key_responsibilities + jd.required_skills + jd.preferred_skills,
        candidate_text,
    )
    seniority_score, seniority_evidence, seniority_gaps = _seniority_score(jd, profile, candidate_text)
    education_score, education_evidence, education_gaps = _education_score(jd.required_education, profile.education)
    soft_score, soft_evidence = _soft_signal_score(jd, candidate_text)
    risk_score, risks = _risk_score(jd, profile, required_coverage, candidate_text)

    hard_checks = [
        f"Minimum years: {'met' if profile.total_experience_years >= jd.min_experience_years else 'not met'} "
        f"({profile.total_experience_years:g}/{jd.min_experience_years:g})",
        f"Must-have skill coverage: {int(required_coverage * 100)}%",
        f"Preferred skill coverage: {int(preferred_coverage * 100)}%",
    ]
    matched_evidence = []
    if required_matched:
        matched_evidence.append(f"Matched must-have skills: {', '.join(required_matched[:8])}")
    if preferred_matched:
        matched_evidence.append(f"Matched preferred skills: {', '.join(preferred_matched[:8])}")
    if business_terms:
        matched_evidence.append(f"Business/project keyword overlap: {', '.join(business_terms[:8])}")
    matched_evidence.extend(seniority_evidence[:2])
    matched_evidence.extend(education_evidence[:2])
    if soft_evidence:
        matched_evidence.append(f"Soft-signal terms found: {', '.join(soft_evidence[:6])}")

    gaps = []
    if required_missing:
        gaps.append(f"Missing/unclear must-have skills: {', '.join(required_missing[:8])}")
    if preferred_missing:
        gaps.append(f"Missing/unclear preferred skills: {', '.join(preferred_missing[:8])}")
    gaps.extend(seniority_gaps)
    gaps.extend(education_gaps)
    if not soft_evidence:
        gaps.append("Soft requirements need interview validation")

    suggested_action = "Recommend interview"
    weighted = (
        hard_skill_score * weights["hard_skills_match"]
        + business_score * weights["business_project_match"]
        + seniority_score * weights["seniority_level_match"]
        + education_score * weights["education_school_match"]
        + soft_score * weights["soft_requirements_match"]
        + risk_score * weights["risk_signal_control"]
    )
    if weighted >= 8:
        suggested_action = "Strong recommend interview"
    elif weighted >= 6.5:
        suggested_action = "Recommend interview"
    elif weighted >= 5:
        suggested_action = "Backup"
    else:
        suggested_action = "Do not proceed"

    signals = {
        "required_skill_coverage": required_coverage,
        "preferred_skill_coverage": preferred_coverage,
        "matched_required_skills": required_matched,
        "missing_required_skills": required_missing,
        "matched_preferred_skills": preferred_matched,
        "missing_preferred_skills": preferred_missing,
        "business_keyword_matches": business_terms,
        "embedding_skills_signal": emb_signal,
        "baseline_weighted_total": round(weighted, 2),
        "matching_skill_id": matching_skill.get("skill_id"),
        "matching_skill_name": matching_skill.get("skill_name"),
        "dimension_weights": weights,
        "skill_focus_summary": matching_skill.get("focus_summary"),
    }

    return CandidateScore(
        hard_skills_match=DimensionScore(
            score=hard_skill_score,
            justification=f"Must-have coverage {int(required_coverage * 100)}%, preferred coverage {int(preferred_coverage * 100)}%; embedding signal {emb_signal if emb_signal is not None else 'not available'}.",
        ),
        business_project_match=DimensionScore(
            score=business_score,
            justification=f"Business/project overlap based on matched terms: {', '.join(business_terms[:8]) or 'limited explicit overlap'}.",
        ),
        seniority_level_match=DimensionScore(
            score=seniority_score,
            justification=f"Candidate has {profile.total_experience_years:g} years vs JD baseline {jd.min_experience_years:g}; {'; '.join(seniority_evidence[:2]) or 'role-level evidence is limited'}.",
        ),
        education_school_match=DimensionScore(
            score=education_score,
            justification="; ".join(education_evidence[:2] or education_gaps[:1] or ["Education signal is present but not strongly differentiated."]),
        ),
        soft_requirements_match=DimensionScore(
            score=soft_score,
            justification=f"Soft requirement evidence from resume: {', '.join(soft_evidence[:6]) if soft_evidence else 'limited; requires interview validation'}.",
        ),
        risk_signal_control=DimensionScore(
            score=risk_score,
            justification=f"Higher is lower risk. {risks[0] if risks else 'No obvious risk signals'}.",
        ),
        hard_checks=hard_checks,
        matched_evidence=matched_evidence[:8],
        gaps=gaps[:8],
        risks=risks[:6],
        suggested_action=suggested_action,
        algorithm_signals=signals,
        matching_skill_id=matching_skill.get("skill_id", "dev_social_v1"),
        matching_skill_name=matching_skill.get("skill_name", "开发序列·社招评分Skill"),
        dimension_weights=weights,
    )


_SYSTEM_PROMPT = """You are a senior HR evaluator. Score a candidate against a confirmed job profile
using a strict, evidence-based person-job matching rubric. Return ONLY valid JSON — no markdown, no explanation.

RUBRIC DIMENSIONS:
- hard_skills_match: Required and preferred technical skills, including evidence of using them in work/projects.
  0=<30% must-have evidence, 5=partial must-have coverage, 10=>85% coverage with applied evidence.
- business_project_match: Similarity between candidate projects/business context and the role's business problem.
  0=unrelated work, 5=adjacent systems, 10=highly similar domain/problem/scale.
- seniority_level_match: Experience years, role responsibility, ownership, and project complexity vs role level.
  0=far below level, 5=borderline, 10=clearly matches/exceeds level.
- education_school_match: Education, major, certifications, and preferred school signals.
  Preferred school/list signals are a boost, not an automatic pass/fail.
- soft_requirements_match: Communication, ownership, collaboration, stability, and motivation evidence.
  Only score from resume evidence; if evidence is weak, say it needs interview validation.
- risk_signal_control: Higher score means lower risk. Consider job hopping, shallow projects, missing core evidence,
  unclear timeline, location/availability mismatch, and thin resume information.

Use the matching_skill.dimension_weights passed by the user message to understand which dimensions matter more
for this role. Social hiring and campus hiring intentionally use different weights and evidence standards.

Return this JSON schema:
{
  "hard_skills_match": {"score": float 0-10, "justification": "one concise sentence with resume evidence"},
  "business_project_match": {"score": float 0-10, "justification": "one concise sentence with resume evidence"},
  "seniority_level_match": {"score": float 0-10, "justification": "one concise sentence with resume evidence"},
  "education_school_match": {"score": float 0-10, "justification": "one concise sentence with resume evidence"},
  "soft_requirements_match": {"score": float 0-10, "justification": "one concise sentence with resume evidence or say interview validation needed"},
  "risk_signal_control": {"score": float 0-10, "justification": "one concise sentence; high score means low risk"},
  "hard_checks": ["short hard check status, e.g. minimum years met / must-have skills partial"],
  "matched_evidence": ["3-6 concrete matched evidence points from resume"],
  "gaps": ["1-5 missing or unclear requirements"],
  "risks": ["0-5 risk signals or 'No obvious risk signals'"],
  "suggested_action": "Strong recommend interview / Recommend interview / Backup / Do not proceed / Needs HR review"
}

Be objective. Base scores ONLY on evidence in the candidate profile. Do NOT fabricate skills.
The final decision belongs to HR; your role is decision support only."""


def score_candidate(
    jd: ParsedJD,
    profile: ParsedProfile,
    matching_skill: Optional[dict] = None,
) -> CandidateScore:
    """
    Score a single candidate against the JD.
    Builds a deterministic matching baseline first, then asks the LLM to calibrate
    the final explanation and scores from the same evidence.
    """
    # Build the context for the LLM
    jd_summary = (
        f"Job Title: {jd.job_title}\n"
        f"Domain: {jd.domain}\n"
        f"Seniority: {jd.seniority_level}\n"
        f"Min Experience: {jd.min_experience_years} years\n"
        f"Required Education: {jd.required_education}\n"
        f"Required Skills: {', '.join(jd.required_skills)}\n"
        f"Preferred Skills: {', '.join(jd.preferred_skills)}\n"
        f"Key Responsibilities: {'; '.join(jd.key_responsibilities[:5])}"
    )

    profile_summary = (
        f"Candidate: {profile.candidate_name}\n"
        f"Experience: {profile.total_experience_years} years\n"
        f"Skills: {', '.join(profile.skills)}\n"
        f"Education: {'; '.join(profile.education)}\n"
        f"Certifications: {'; '.join(profile.certifications) or 'None'}\n"
        f"Work History: {'; '.join(profile.work_history[:5])}\n"
        f"Projects: {'; '.join(profile.projects[:5]) or 'None'}\n"
        f"Summary: {profile.summary}"
    )

    # Sanitize before sending to LLM
    jd_summary = sanitize_input(jd_summary)
    profile_summary = sanitize_input(profile_summary)

    # Get embedding signal (optional augmentation)
    matching_skill = matching_skill or get_matching_skill("开发", "社招")
    weights = weights_for_skill(matching_skill)
    emb_signal = _embedding_skills_signal(jd, profile)
    baseline = _build_matching_baseline(jd, profile, emb_signal, matching_skill)

    embedding_note = ""
    if emb_signal is not None:
        embedding_note = (
            f"\n\nEmbedding similarity signal for skills: {emb_signal}/10. "
            f"Use this as a soft reference — your reasoning takes precedence."
        )

    baseline_note = json.dumps(
        {
            "baseline_scores": {
                "hard_skills_match": baseline.hard_skills_match.dict(),
                "business_project_match": baseline.business_project_match.dict(),
                "seniority_level_match": baseline.seniority_level_match.dict(),
                "education_school_match": baseline.education_school_match.dict(),
                "soft_requirements_match": baseline.soft_requirements_match.dict(),
                "risk_signal_control": baseline.risk_signal_control.dict(),
            },
            "hard_checks": baseline.hard_checks,
            "matched_evidence": baseline.matched_evidence,
            "gaps": baseline.gaps,
            "risks": baseline.risks,
            "suggested_action": baseline.suggested_action,
            "algorithm_signals": baseline.algorithm_signals,
            "matching_skill": {
                "skill_id": matching_skill.get("skill_id"),
                "skill_name": matching_skill.get("skill_name"),
                "job_family": matching_skill.get("job_family"),
                "hiring_type": matching_skill.get("hiring_type"),
                "version": matching_skill.get("version"),
                "focus_summary": matching_skill.get("focus_summary"),
                "dimension_weights": weights,
                "hard_checks": matching_skill.get("hard_checks", []),
                "positive_signals": matching_skill.get("positive_signals", []),
                "negative_signals": matching_skill.get("negative_signals", []),
                "evidence_rules": matching_skill.get("evidence_rules", []),
                "interview_focus": matching_skill.get("interview_focus", []),
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    raw = chat_completion(
        max_tokens=1400,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"JOB DESCRIPTION:\n{jd_summary}\n\n"
                    f"CANDIDATE PROFILE:\n{profile_summary}"
                    f"\n\nDETERMINISTIC MATCHING BASELINE:\n{baseline_note}\n\n"
                    "Use the baseline as the starting point. You may adjust scores only when the resume evidence supports it. "
                    "Preserve concrete hard checks, evidence, gaps, and risk signals where accurate."
                    f"{embedding_note}"
                )
            }
        ]
    )

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Scoring JSON error for {profile.candidate_name}: {e}")
        logger.warning(f"Falling back to deterministic matching baseline for {profile.candidate_name}")
        return baseline

    try:
        return CandidateScore(
            hard_skills_match=DimensionScore(**data["hard_skills_match"]),
            business_project_match=DimensionScore(**data["business_project_match"]),
            seniority_level_match=DimensionScore(**data["seniority_level_match"]),
            education_school_match=DimensionScore(**data["education_school_match"]),
            soft_requirements_match=DimensionScore(**data["soft_requirements_match"]),
            risk_signal_control=DimensionScore(**data["risk_signal_control"]),
            hard_checks=data.get("hard_checks", []),
            matched_evidence=data.get("matched_evidence", []),
            gaps=data.get("gaps", []),
            risks=data.get("risks", []),
            suggested_action=data.get("suggested_action", "Needs HR review"),
            algorithm_signals=baseline.algorithm_signals,
            matching_skill_id=matching_skill.get("skill_id", "dev_social_v1"),
            matching_skill_name=matching_skill.get("skill_name", "开发序列·社招评分Skill"),
            dimension_weights=weights,
        )
    except Exception as e:
        logger.error(f"Score validation error for {profile.candidate_name}: {e}")
        logger.warning(f"Falling back to deterministic matching baseline for {profile.candidate_name}")
        return baseline

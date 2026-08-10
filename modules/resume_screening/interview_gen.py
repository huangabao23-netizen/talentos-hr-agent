"""
Interview Question Generator.
Given a candidate's score gaps vs the JD, generates 5 targeted interview questions.
Called per-candidate after scoring — one extra LLM call, cached in session state.
"""

import json
import logging
from models.schemas import ParsedJD, ParsedProfile, CandidateScore
from utils.llm_client import chat_completion
from utils.security import sanitize_input

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior technical recruiter. Generate targeted interview questions
based on a candidate's specific strengths and gaps for a role.

Return ONLY a JSON object — no markdown, no explanation:
{
  "technical_questions": [string, string],
  "gap_questions": [string, string],
  "culture_question": string
}

Rules:
- technical_questions: 2 deep technical questions based on their strongest skills
- gap_questions: 2 probing questions that explore their weakest scoring dimensions
- culture_question: 1 behavioural question relevant to the role's seniority level
- Each question must be specific — mention actual skills, projects, or gaps from their profile
- Never generate generic questions like "Tell me about yourself"
"""


def generate_interview_questions(
    jd: ParsedJD,
    profile: ParsedProfile,
    scores: CandidateScore,
) -> dict:
    """
    Generate 5 targeted interview questions for a candidate.
    Returns dict with technical_questions, gap_questions, culture_question.
    """
    # Build gap summary
    jd_skills = {s.lower() for s in jd.required_skills}
    cand_skills = {s.lower() for s in profile.skills}
    missing_skills = sorted(jd_skills - cand_skills)

    # Find weakest dimensions
    dim_scores = {
        "Hard Skills": scores.hard_skills_match.score,
        "Business / Project Match": scores.business_project_match.score,
        "Seniority / Level": scores.seniority_level_match.score,
        "Education / School": scores.education_school_match.score,
        "Soft Requirements": scores.soft_requirements_match.score,
        "Risk Signal Control": scores.risk_signal_control.score,
    }
    weakest = sorted(dim_scores, key=dim_scores.get)[:2]

    context = (
        f"Role: {jd.job_title} ({jd.seniority_level}, {jd.domain})\n"
        f"Candidate: {profile.candidate_name}\n"
        f"Experience: {profile.total_experience_years} years\n"
        f"Strong skills: {', '.join(profile.skills[:8])}\n"
        f"Missing required skills: {', '.join(missing_skills[:6]) or 'None'}\n"
        f"Weakest scoring dimensions: {', '.join(weakest)}\n"
        f"Known gaps: {'; '.join(scores.gaps[:5]) or 'None listed'}\n"
        f"Risk signals: {'; '.join(scores.risks[:5]) or 'None listed'}\n"
        f"Projects: {'; '.join(profile.projects[:3]) or 'None listed'}\n"
        f"Weighted total score: {scores.weighted_total}/10"
    )

    raw = chat_completion(
        max_tokens=800,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate interview questions for:\n\n{sanitize_input(context)}"}
        ]
    )

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Interview gen JSON error for {profile.candidate_name}: {e}")
        return {
            "technical_questions": ["Could not generate — please retry."],
            "gap_questions": ["Could not generate — please retry."],
            "culture_question": "Could not generate — please retry."
        }


def get_skills_gap(jd: ParsedJD, profile: ParsedProfile) -> list[str]:
    """Return list of required skills the candidate is missing."""
    jd_skills = {s.lower() for s in jd.required_skills}
    cand_skills = {s.lower() for s in profile.skills}
    return sorted(jd_skills - cand_skills)

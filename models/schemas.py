"""
Pydantic models for all structured outputs.
Using strict validation to prevent hallucinations from LLM responses.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional
from enum import Enum
from datetime import datetime, date


class HireRecommendation(str, Enum):
    STRONG_HIRE = "Strong Hire"
    HIRE = "Hire"
    MAYBE = "Maybe"
    NO_HIRE = "No Hire"


class DimensionScore(BaseModel):
    score: float = Field(..., ge=0, le=10, description="Score from 0 to 10")
    justification: str = Field(..., min_length=10, max_length=600)

    @validator("score")
    def round_score(cls, v):
        return round(v, 1)


class CandidateScore(BaseModel):
    hard_skills_match: DimensionScore
    business_project_match: DimensionScore
    seniority_level_match: DimensionScore
    education_school_match: DimensionScore
    soft_requirements_match: DimensionScore
    risk_signal_control: DimensionScore
    hard_checks: List[str] = Field(default_factory=list)
    matched_evidence: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    suggested_action: str = "Needs HR review"
    algorithm_signals: dict = Field(default_factory=dict)
    matching_skill_id: str = "dev_social_v1"
    matching_skill_name: str = "开发序列·社招评分Skill"
    dimension_weights: dict = Field(default_factory=lambda: {
        "hard_skills_match": 0.30,
        "business_project_match": 0.25,
        "seniority_level_match": 0.15,
        "education_school_match": 0.10,
        "soft_requirements_match": 0.10,
        "risk_signal_control": 0.10,
    })

    @property
    def weighted_total(self) -> float:
        weights = {
            "hard_skills_match": float(self.dimension_weights.get("hard_skills_match", 0.30)),
            "business_project_match": float(self.dimension_weights.get("business_project_match", 0.25)),
            "seniority_level_match": float(self.dimension_weights.get("seniority_level_match", 0.15)),
            "education_school_match": float(self.dimension_weights.get("education_school_match", 0.10)),
            "soft_requirements_match": float(self.dimension_weights.get("soft_requirements_match", 0.10)),
            "risk_signal_control": float(self.dimension_weights.get("risk_signal_control", 0.10)),
        }
        total_weight = sum(weights.values()) or 1.0
        total = (
            self.hard_skills_match.score * weights["hard_skills_match"]
            + self.business_project_match.score * weights["business_project_match"]
            + self.seniority_level_match.score * weights["seniority_level_match"]
            + self.education_school_match.score * weights["education_school_match"]
            + self.soft_requirements_match.score * weights["soft_requirements_match"]
            + self.risk_signal_control.score * weights["risk_signal_control"]
        ) / total_weight
        return round(total, 2)

    @property
    def hire_recommendation(self) -> HireRecommendation:
        t = self.weighted_total
        if t >= 8.0:
            return HireRecommendation.STRONG_HIRE
        elif t >= 6.5:
            return HireRecommendation.HIRE
        elif t >= 5.0:
            return HireRecommendation.MAYBE
        else:
            return HireRecommendation.NO_HIRE

    @property
    def skills_match(self) -> DimensionScore:
        return self.hard_skills_match

    @property
    def experience_relevance(self) -> DimensionScore:
        return self.business_project_match

    @property
    def education_certs(self) -> DimensionScore:
        return self.education_school_match

    @property
    def project_portfolio(self) -> DimensionScore:
        return self.seniority_level_match

    @property
    def communication_quality(self) -> DimensionScore:
        return self.soft_requirements_match


class ParsedJD(BaseModel):
    job_title: str
    required_skills: List[str] = Field(..., min_items=1)
    preferred_skills: List[str] = Field(default_factory=list)
    min_experience_years: int = Field(..., ge=0)
    required_education: str
    key_responsibilities: List[str] = Field(..., min_items=1)
    domain: str
    seniority_level: str


class GeneratedJD(BaseModel):
    public_jd: str = Field(..., min_length=50)
    internal_profile: dict = Field(default_factory=dict)
    screening_strategy: List[str] = Field(default_factory=list)
    scoring_weights: dict = Field(default_factory=dict)
    interview_focus: List[str] = Field(default_factory=list)


class ParsedProfile(BaseModel):
    candidate_name: str
    email: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    total_experience_years: float = Field(..., ge=0)
    education: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    work_history: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    summary: str = ""
    source_file: str = ""


class CandidateResult(BaseModel):
    profile: ParsedProfile
    scores: CandidateScore
    rank: int = 0
    override_applied: bool = False
    override_reason: Optional[str] = None

    @property
    def weighted_total(self) -> float:
        return self.scores.weighted_total

    @property
    def hire_recommendation(self) -> HireRecommendation:
        return self.scores.hire_recommendation


# ── Talent Pool (Resume Open Source) ──────────────────────────────────────

class TalentPoolStatus(str, Enum):
    ACTIVE = "Active"
    ARCHIVED = "Archived"
    PLACED = "Placed"


class TalentPoolRecord(BaseModel):
    id: Optional[int] = None
    candidate_name: str
    anonymized_name: str = ""
    domain: str = ""
    seniority_level: str = ""
    total_experience_years: float = 0.0
    skills: List[str] = Field(default_factory=list)
    education: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    work_summary: str = ""
    project_summary: str = ""
    location: str = ""
    open_to_remote: bool = True
    status: TalentPoolStatus = TalentPoolStatus.ACTIVE
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    raw_profile: Optional[str] = None


# ── Recruitment Analytics (Data Review) ────────────────────────────────────

class FunnelStage(str, Enum):
    APPLIED = "Applied"
    SCREENED = "Screened"
    INTERVIEWED = "Interviewed"
    OFFERED = "Offered"
    HIRED = "Hired"
    REJECTED = "Rejected"


class ScreeningRecord(BaseModel):
    id: Optional[int] = None
    job_title: str
    domain: str
    seniority_level: str
    candidate_name: str
    anonymized_name: str = ""
    initial_score: float = 0.0
    final_score: float = 0.0
    recommendation: str = ""
    stage: FunnelStage = FunnelStage.APPLIED
    source: str = ""
    applied_date: date
    screened_date: Optional[date] = None
    interviewed_date: Optional[date] = None
    offered_date: Optional[date] = None
    hired_date: Optional[date] = None
    rejected_date: Optional[date] = None
    days_to_screen: Optional[int] = None
    days_to_interview: Optional[int] = None
    days_to_offer: Optional[int] = None
    days_to_hire: Optional[int] = None
    recruiter: str = ""
    hiring_manager: str = ""
    rejection_reason: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class JDRecord(BaseModel):
    id: Optional[int] = None
    job_title: str
    domain: str
    seniority_level: str
    department: str = ""
    opened_date: date
    closed_date: Optional[date] = None
    status: str = "Open"
    total_applicants: int = 0
    total_screened: int = 0
    total_interviewed: int = 0
    total_offered: int = 0
    total_hired: int = 0
    target_hires: int = 1
    created_at: datetime = Field(default_factory=datetime.now)

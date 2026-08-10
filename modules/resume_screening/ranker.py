"""
Ranker.
Sorts CandidateResult objects by weighted_total descending.
Handles HR score overrides with full audit logging.
"""

import logging
from typing import List, Optional
from models.schemas import CandidateResult, CandidateScore, DimensionScore

logger = logging.getLogger(__name__)


def rank_candidates(candidates: List[CandidateResult]) -> List[CandidateResult]:
    """
    Sort candidates by weighted_total descending and assign rank numbers.
    Returns a new list — original objects are not mutated.
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda c: c.weighted_total,
        reverse=True
    )
    for i, candidate in enumerate(sorted_candidates, start=1):
        candidate.rank = i
    return sorted_candidates


def apply_override(
    candidate: CandidateResult,
    dimension: str,
    new_score: float,
    reason: str
) -> CandidateResult:
    """
    Apply an HR override to a specific dimension score.
    Logs the change for audit trail.
    Dimension must be one of the person-job matching score dimensions.
    """
    valid_dimensions = [
        "hard_skills_match", "business_project_match", "seniority_level_match",
        "education_school_match", "soft_requirements_match", "risk_signal_control"
    ]

    if dimension not in valid_dimensions:
        raise ValueError(f"Invalid dimension: {dimension}. Must be one of {valid_dimensions}")

    if not 0 <= new_score <= 10:
        raise ValueError(f"Score must be between 0 and 10. Got: {new_score}")

    if not reason.strip():
        raise ValueError("Override reason cannot be empty.")

    old_score = getattr(candidate.scores, dimension).score

    # Update the specific dimension
    current_dim = getattr(candidate.scores, dimension)
    updated_dim = DimensionScore(
        score=new_score,
        justification=f"[HR OVERRIDE] {reason} (original: {old_score}/10)"
    )

    # Build updated scores (Pydantic models are immutable — rebuild)
    updated_scores_data = candidate.scores.dict()
    updated_scores_data[dimension] = updated_dim.dict()
    updated_scores = CandidateScore(**updated_scores_data)

    candidate.scores = updated_scores
    candidate.override_applied = True
    candidate.override_reason = f"Dimension '{dimension}' changed from {old_score} → {new_score}: {reason}"

    logger.info(
        f"OVERRIDE APPLIED | Candidate: {candidate.profile.candidate_name} | "
        f"Dimension: {dimension} | {old_score} → {new_score} | Reason: {reason}"
    )

    return candidate

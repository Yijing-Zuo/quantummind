from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import median

from pydantic import Field

from .models import StrictModel

ODS_VERSION = "ODS-v1"
EPSILON, MAD_MULTIPLIER, UNCERTAINTY_PENALTY, KAPPA = 0.02, 1.4826, 0.5, 40.0
DIMENSION_WEIGHTS, FUSION_WEIGHTS = (0.4, 0.4, 0.2), (0.7, 0.3)
_REVIEW_FIELDS = "technical_validity epistemic_auditability research_utility".split()  # noqa: SIM905
_BREAKDOWN_FIELDS = (  # noqa: SIM905
    "ods_score technical_validity epistemic_auditability research_utility api_quality deterministic_prior "
    "fused_quality semantic_cap judge_disagreement"
).split()
_DISPOSITIONS = (  # noqa: SIM905
    "INVALID_STATE SOURCE_REPAIR_REQUIRED REJECT_TASK_MISMATCH DEMOTE_GENERIC DEMOTE_TO_BENCHMARK "
    "REFORMULATE LITERATURE_SEARCH_FIRST KEEP_FOR_EXPERT_REVIEW"
).split()
DISPOSITION_PRIORS = dict(zip(_DISPOSITIONS, (0.04, 0.10, 0.12, 0.36, 0.45, 0.70, 0.84, 0.95), strict=True))


class ODSJudgeAssessment(StrictModel):
    technical_validity: int = Field(ge=0, le=4, strict=True)
    epistemic_auditability: int = Field(ge=0, le=4, strict=True)
    research_utility: int = Field(ge=0, le=4, strict=True)
    technical_rationale: str = Field(min_length=1, max_length=1000)
    auditability_rationale: str = Field(min_length=1, max_length=1000)
    utility_rationale: str = Field(min_length=1, max_length=1000)
    critical_issue: str | None = Field(default=None, max_length=1000)


JudgeReviews = Sequence[ODSJudgeAssessment]


def stable_softplus(value: float) -> float:
    return max(value, 0.0) + math.log1p(math.exp(-abs(value)))


def robust_dimension_estimate(scores: Sequence[int]) -> tuple[float, float]:
    if len(scores) != 3 or any(type(score) is not int or not 0 <= score <= 4 for score in scores):
        raise ValueError("one dimension requires exactly three integer scores in [0, 4]")
    values = [min(1.0 - EPSILON, max(EPSILON, score / 4.0)) for score in scores]
    center = median(values)
    sigma = MAD_MULTIPLIER * median(abs(value - center) for value in values)
    return min(1.0 - EPSILON, max(EPSILON, center - UNCERTAINTY_PENALTY * sigma)), sigma


def calculate_ods_score(reviews: JudgeReviews, disposition: str, claim_accepted: bool, graph_status: str) -> dict[str, float]:
    if len(reviews) != 3:
        raise ValueError("ODS-v1 requires exactly three judge assessments")
    if disposition not in DISPOSITION_PRIORS or graph_status not in {"PASS", "WARN", "FAIL"}:
        raise ValueError("unknown ODS disposition or graph status")
    estimates = [robust_dimension_estimate([getattr(review, field) for review in reviews]) for field in _REVIEW_FIELDS]
    dimensions = tuple(item[0] for item in estimates)
    api_quality = math.exp(sum(weight * math.log(value) for weight, value in zip(DIMENSION_WEIGHTS, dimensions, strict=True)))
    base = DISPOSITION_PRIORS[disposition]
    prior_logit = math.log(base / (1.0 - base)) + 0.5 * claim_accepted - 1.5 * (graph_status != "PASS")
    prior = 1.0 / (1.0 + math.exp(-prior_logit))
    fatal = graph_status == "FAIL" or disposition in {"INVALID_STATE", "SOURCE_REPAIR_REQUIRED", "REJECT_TASK_MISMATCH"}
    caps = [
        1.0,
        0.25 if fatal else 1.0,
        0.58 if disposition == "DEMOTE_GENERIC" else 1.0,
        0.65 if disposition == "DEMOTE_TO_BENCHMARK" else 1.0,
        0.68 if not claim_accepted else 1.0,
    ]
    cap = min(caps)
    fused_logit = FUSION_WEIGHTS[0] * math.log(api_quality / (1.0 - api_quality)) + FUSION_WEIGHTS[1] * prior_logit
    fused = 1.0 / (1.0 + math.exp(-fused_logit))
    final = 100.0 * min(1.0, max(0.0, fused - stable_softplus(KAPPA * (fused - cap)) / KAPPA))
    disagreement = sum(weight * estimate[1] for weight, estimate in zip(DIMENSION_WEIGHTS, estimates, strict=True))
    values = (final, *dimensions, api_quality, prior, fused, cap, disagreement)
    return dict(zip(_BREAKDOWN_FIELDS, values, strict=True))

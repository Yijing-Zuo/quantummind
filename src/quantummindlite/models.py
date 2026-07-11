from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MatchStrength(str, Enum):
    PLAUSIBLE = "PLAUSIBLE"
    WEAK_ANALOGY = "WEAK_ANALOGY"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class EvidenceState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"
    CONTRADICTED = "CONTRADICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Verdict(str, Enum):
    POSITIVE = "POSITIVE"
    CONDITIONAL = "CONDITIONAL"
    NEGATIVE = "NEGATIVE"
    INVALID = "INVALID"


class ClaimScope(str, Enum):
    QUERY = "QUERY"
    GATE = "GATE"
    END_TO_END = "END_TO_END"
    NONE = "NONE"


class Route(str, Enum):
    EXPERT_REVIEW = "EXPERT_REVIEW"
    EXPERT_REVIEW_WITH_WARNINGS = "EXPERT_REVIEW_WITH_WARNINGS"
    STOP = "STOP"
    RERUN = "RERUN"


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SpeedupClass(str, Enum):
    ASYMPTOTIC = "ASYMPTOTIC"
    CONSTANT_FACTOR_ONLY = "CONSTANT_FACTOR_ONLY"
    NONE = "NONE"


class PriorArtStatus(str, Enum):
    KNOWN_CASE_RECOVERY = "KNOWN_CASE_RECOVERY"
    DIRECT_PRIOR_ART = "DIRECT_PRIOR_ART"
    UNKNOWN = "UNKNOWN"


class NoveltyStatus(str, Enum):
    NOT_GLOBALLY_NOVEL = "NOT_GLOBALLY_NOVEL"
    GLOBAL_NOVELTY_CLAIM = "GLOBAL_NOVELTY_CLAIM"
    UNASSESSED = "UNASSESSED"


class PrimitiveSpec(StrictModel):
    primitive_id: str
    required_structure_ids: list[str]
    allowed_access_models: list[str]
    allowed_output_contracts: list[str]
    required_promises: list[str]
    supported_claim_scope: ClaimScope
    speedup_class: SpeedupClass
    classical_complexity: str
    quantum_complexity: str
    common_barriers: list[str]
    source_ids: list[str]


class BarrierSpec(StrictModel):
    barrier_id: str
    description: str
    blocked_scopes: list[ClaimScope] = Field(default_factory=list)
    satisfied_by_access_models: list[str] = Field(default_factory=list)
    satisfied_by_output_contracts: list[str] = Field(default_factory=list)
    satisfied_by_promises: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def catalog_lists_unique(self) -> BarrierSpec:
        for field_name in (
            "blocked_scopes",
            "satisfied_by_access_models",
            "satisfied_by_output_contracts",
            "satisfied_by_promises",
        ):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
        return self


class SourceSpec(StrictModel):
    source_id: str
    title: str
    year: int
    result_type: str
    status: str
    primitive_ids: list[str]
    official_url: str


class ProblemCard(StrictModel):
    statement: str
    input_model: str
    access_model: str
    output_contract: str
    promises: list[str] = Field(default_factory=list)
    size_parameters: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class FormalizationOutput(StrictModel):
    ambiguities: list[str] = Field(default_factory=list)


class AnalysisCard(StrictModel):
    formalized_problem: str
    canonical_structure_ids: list[str] = Field(default_factory=list)
    absent_or_weak_structures: list[str] = Field(default_factory=list)
    classical_baseline: str
    bottleneck: str
    complexity_model: str


class PrimitiveMatch(StrictModel):
    primitive_id: str
    strength: MatchStrength
    prerequisites: list[str] = Field(default_factory=list)


class WeakAnalogyOpportunity(StrictModel):
    primitive_id: str
    missing_access_or_output_or_promises: list[str] = Field(default_factory=list)
    why_not_selected: str
    possible_reformulation_question: str


class BarrierFinding(StrictModel):
    barrier_id: str
    description: str
    applicable: EvidenceState


class BarrierAssessment(BarrierFinding):
    blocked_scopes: list[ClaimScope] = Field(default_factory=list)


class CandidateCard(StrictModel):
    primitive_matches: list[PrimitiveMatch] = Field(default_factory=list)
    weak_analogy_opportunities: list[WeakAnalogyOpportunity] = Field(default_factory=list)
    selected_candidate: str | None = None
    no_candidate_reason: str | None = None
    barriers: list[BarrierAssessment] = Field(default_factory=list)
    prior_art_status: PriorArtStatus = PriorArtStatus.UNKNOWN
    novelty_status: NoveltyStatus = NoveltyStatus.UNASSESSED
    scheme_steps: list[str] = Field(default_factory=list)
    classical_baseline: str = "UNKNOWN"
    quantum_query_complexity: str | None = None
    gate_complexity: str | None = None
    total_complexity: str | None = None
    claim_scope: ClaimScope = ClaimScope.NONE
    limitations: list[str] = Field(default_factory=list)
    expert_questions: list[str] = Field(default_factory=list)
    claim_flags: list[str] = Field(default_factory=list)
    consistency_review_notes: list[str] = Field(default_factory=list)
    self_assessment: str = "diagnostic_only"

    @model_validator(mode="after")
    def candidate_invariant(self) -> CandidateCard:
        if self.selected_candidate and self.no_candidate_reason:
            raise ValueError("selected_candidate and no_candidate_reason are mutually exclusive")
        return self


class PrimitiveMatchingOutput(StrictModel):
    primitive_matches: list[PrimitiveMatch] = Field(default_factory=list)


class BarrierOutput(StrictModel):
    barriers: list[BarrierFinding] = Field(default_factory=list)


class PriorArtOutput(StrictModel):
    prior_art_status: PriorArtStatus


class SchemeOutput(StrictModel):
    selected_candidate: str | None = None
    no_candidate_reason: str | None = None
    scheme_steps: list[str] = Field(default_factory=list)
    classical_baseline: str = "UNKNOWN"
    quantum_query_complexity: str | None = None
    gate_complexity: str | None = None
    total_complexity: str | None = None
    claim_scope: ClaimScope = ClaimScope.NONE
    limitations: list[str] = Field(default_factory=list)
    expert_questions: list[str] = Field(default_factory=list)
    claim_flags: list[str] = Field(default_factory=list)
    self_assessment: str = "diagnostic_only"


class NoveltyOutput(StrictModel):
    novelty_status: NoveltyStatus


class ConsistencyOutput(StrictModel):
    consistency_review_notes: list[str] = Field(default_factory=list)


class CheckResult(StrictModel):
    rule_id: str
    outcome: CheckOutcome
    reason: str
    evidence_path: str


class DecisionCard(StrictModel):
    authoritative_verdict: Verdict
    maximum_supported_claim_scope: ClaimScope
    b_check_results: list[CheckResult]
    d_route: Route
    concise_reasons: list[str]
    claim_boundary_statement: str


class RunState(StrictModel):
    problem_card: ProblemCard | None = None
    analysis_card: AnalysisCard | None = None
    candidate_card: CandidateCard | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


def stable_union(existing: list[str], incoming: list[str]) -> list[str]:
    return list(dict.fromkeys([*existing, *incoming]))


def problem_satisfies_barrier(problem: ProblemCard, barrier: BarrierSpec) -> bool:
    checks: list[bool] = []
    if barrier.satisfied_by_access_models:
        checks.append(problem.access_model in barrier.satisfied_by_access_models)
    if barrier.satisfied_by_output_contracts:
        checks.append(problem.output_contract in barrier.satisfied_by_output_contracts)
    if barrier.satisfied_by_promises:
        checks.append(set(barrier.satisfied_by_promises) <= set(problem.promises))
    return bool(checks) and all(checks)


def problem_prerequisite_mismatches(problem: ProblemCard | None, spec: PrimitiveSpec) -> list[str]:
    if problem is None:
        return ["missing ProblemCard"]
    missing: list[str] = []
    if problem.access_model not in spec.allowed_access_models:
        missing.append(f"access_model={problem.access_model!r} not in {spec.allowed_access_models}")
    if problem.output_contract not in spec.allowed_output_contracts:
        missing.append(f"output_contract={problem.output_contract!r} not in {spec.allowed_output_contracts}")
    absent = sorted(set(spec.required_promises) - set(problem.promises))
    if absent:
        missing.append("missing required promises: " + ", ".join(absent))
    return missing


def weak_analogy_opportunity(primitive_id: str, missing: list[str]) -> dict[str, Any]:
    return {
        "primitive_id": primitive_id,
        "missing_access_or_output_or_promises": missing,
        "why_not_selected": "Structural similarity is not enough to satisfy the primitive registry prerequisites.",
        "possible_reformulation_question": "Can the task be reformulated with the required access, output contract, and promises?",
    }

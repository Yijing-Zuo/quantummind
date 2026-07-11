from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from .messages import ActionType, Role
from .models import ClaimScope, EvidenceState, MatchStrength, NoveltyStatus, PriorArtStatus


@dataclass(frozen=True)
class ProviderTrace:
    provider: str
    model: str
    usage: dict[str, Any] | None = None
    attempt_count: int = 1
    status: str = "ok"
    refusal: str | None = None
    incomplete_reason: str | None = None
    parse_status: str = "ok"


@dataclass(frozen=True)
class ProviderResult:
    payload: dict[str, Any]
    trace: ProviderTrace


class ProviderError(RuntimeError):
    def __init__(self, message: str, trace: ProviderTrace, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.trace = trace
        self.retryable = retryable


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult: ...


def _joined(*values: object) -> str:
    return " ".join(str(v).lower() for v in values if v is not None)


class MockLLMProvider:
    provider_name = "mock"
    model_name = "mock-deterministic"

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        del role, prompt
        public = inputs.get("public_case", {})
        problem = inputs.get("problem_card", {})
        analysis = inputs.get("analysis_card", {})
        candidate = inputs.get("scheme_summary", {})
        text = _joined(public, problem, analysis, candidate)
        kind = self._kind(text)
        payload: dict[str, Any]
        if action is ActionType.FORMALIZE:
            payload = self._formalize(public)
        elif action is ActionType.ANALYZE_STRUCTURE:
            payload = self._analyze(kind, problem)
        elif action is ActionType.MATCH_PRIMITIVES:
            payload = {"primitive_matches": self._matches(kind)}
        elif action is ActionType.BARRIER_PRECHECK:
            payload = {"barriers": self._barriers(kind)}
        elif action is ActionType.PRIOR_ART:
            payload = {"prior_art_status": self._prior_art_status(inputs)}
        elif action is ActionType.GENERATE_SCHEME:
            payload = self._scheme(kind, problem, analysis)
        elif action is ActionType.REVIEW_SCHEME:
            payload = {"barriers": self._barriers(kind)}
        elif action is ActionType.NOVELTY_AUDIT:
            payload = {"novelty_status": self._novelty_status(inputs)}
        elif action is ActionType.CONSISTENCY_REVIEW:
            payload = {"consistency_review_notes": self._review_notes(kind)}
        else:
            raise ValueError(f"unsupported action {action}")
        output_model.model_validate(payload)
        return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))

    def _kind(self, text: str) -> str:
        if (
            "sorted order" in text
            or "sorted_order" in text
            or "pairwise comparisons" in text
            or "comparison model" in text
            or "comparison_oracle" in text
            or "nondecreasing order" in text
        ):
            return "comparison_sorting"
        if "monotone" in text or "ordered queries" in text:
            return "ordered_search"
        if "complete" in text and ("n-bit" in text or "all n bits" in text):
            return "oracle_interrogation"
        if "parity" in text or "xor" in text:
            return "parity"
        if "full classical solution vector" in text or "dense" in text:
            return "linear_system_stress"
        if "sparse" in text and "matrix" in text:
            return "sparse_linear_system"
        if "colliding" in text or "distinct" in text:
            return "element_distinctness"
        if "period" in text or "cyclic" in text:
            return "period_recovery"
        if "estimate" in text or "additive epsilon" in text or "mean" in text:
            return "mean_estimation"
        return "witness_search"

    def _formalize(self, public: dict[str, Any]) -> dict[str, Any]:
        return {"ambiguities": list(public.get("ambiguities", []))}

    def _analyze(self, kind: str, problem: dict[str, Any]) -> dict[str, Any]:
        table = {
            "witness_search": ("black_box_witness_search", "Theta(N/M)", "marked-item search"),
            "mean_estimation": (
                "bounded_mean_estimation",
                "Theta(1/epsilon^2)",
                "sampling variance",
            ),
            "period_recovery": (
                "periodic_group_structure",
                "superpolynomial in direct search",
                "period",
            ),
            "sparse_linear_system": (
                "sparse_linear_system",
                "poly(n,kappa,1/epsilon)",
                "linear solve",
            ),
            "element_distinctness": ("collision_query_structure", "Theta(N)", "collision queries"),
            "comparison_sorting": (
                "comparison_sorting",
                "Theta(N log N)",
                "comparison lower bound",
            ),
            "ordered_search": ("ordered_search", "Theta(log N)", "ordered comparison lower bound"),
            "oracle_interrogation": ("complete_oracle_recovery", "Theta(N)", "full output size"),
            "parity": ("parity_query_function", "Theta(N)", "polynomial/query lower bound"),
            "linear_system_stress": (
                "linear_system_full_output_stress",
                "classical input/readout cost",
                "loading/readout",
            ),
        }
        structure, baseline, bottleneck = table[kind]
        return {
            "formalized_problem": str(problem.get("statement", "")),
            "canonical_structure_ids": [structure],
            "absent_or_weak_structures": ["no_hidden_extra_structure"],
            "classical_baseline": baseline,
            "bottleneck": bottleneck,
            "complexity_model": str(problem.get("access_model", "query_model")),
        }

    def _matches(self, kind: str) -> list[dict[str, Any]]:
        mapping = {
            "witness_search": "amplitude_amplification",
            "mean_estimation": "amplitude_estimation",
            "period_recovery": "qft_period_finding",
            "sparse_linear_system": "quantum_linear_systems_state_output",
            "element_distinctness": "quantum_walk_element_distinctness",
            "ordered_search": "ordered_search",
            "oracle_interrogation": "oracle_interrogation",
            "parity": "parity_query",
        }
        if kind in mapping:
            primitive = mapping[kind]
            return [
                {
                    "primitive_id": primitive,
                    "strength": MatchStrength.PLAUSIBLE.value,
                    "prerequisites": ["represented access/output promises must hold"],
                }
            ]
        bait = "amplitude_amplification" if kind == "comparison_sorting" else None
        if bait is None:
            return []
        return [
            {
                "primitive_id": bait,
                "strength": MatchStrength.WEAK_ANALOGY.value,
                "prerequisites": ["missing structure for asymptotic speedup"],
            }
        ]

    def _barriers(self, kind: str) -> list[dict[str, Any]]:
        satisfied = {
            "mean_estimation": ("coherent_access",),
            "element_distinctness": ("output_contract",),
            "sparse_linear_system": ("state_preparation", "condition_number", "readout"),
        }
        if kind in satisfied:
            return [
                {
                    "barrier_id": barrier_id,
                    "description": "public promises/output satisfy this registered caveat",
                    "applicable": EvidenceState.NOT_APPLICABLE.value,
                }
                for barrier_id in satisfied[kind]
            ]
        table = {
            "comparison_sorting": (
                "comparison_lower_bound",
                "comparison model blocks asymptotic speedup",
            ),
            "ordered_search": (
                "ordered_access_lower_bound",
                "ordered access changes only constants here",
            ),
            "oracle_interrogation": (
                "full_output_information",
                "complete output requires linear information",
            ),
            "parity": (
                "polynomial_query_lower_bound",
                "parity has linear quantum query lower bound",
            ),
            "linear_system_stress": (
                "loading_condition_readout",
                "loading, condition number, and full readout dominate",
            ),
        }
        if kind not in table:
            return []
        barrier_id, description = table[kind]
        return [
            {
                "barrier_id": barrier_id,
                "description": description,
                "applicable": EvidenceState.SUPPORTED.value,
            }
        ]

    def _scheme(self, kind: str, problem: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        matches = self._matches(kind)
        selected = next((m["primitive_id"] for m in matches if m["strength"] == MatchStrength.PLAUSIBLE.value), None)
        if selected is None:
            return {
                "selected_candidate": None,
                "no_candidate_reason": "No represented primitive supports an asymptotic claim for this model.",
                "scheme_steps": [],
                "classical_baseline": str(analysis.get("classical_baseline", "UNKNOWN")),
                "quantum_query_complexity": None,
                "gate_complexity": None,
                "total_complexity": None,
                "claim_scope": ClaimScope.NONE.value,
                "expert_questions": ["Can additional structure be promised without changing the task?"],
                "self_assessment": "negative_or_out_of_scope",
            }
        q_complexity = {
            "amplitude_amplification": "query: O(sqrt(N/M))",
            "amplitude_estimation": "query: O(1/epsilon)",
            "qft_period_finding": "query/gate: polynomial under reversible evaluation",
            "quantum_linear_systems_state_output": "query/gate: polylog dimension with sparsity/kappa/epsilon factors",
            "quantum_walk_element_distinctness": "query: O(N^(2/3))",
            "ordered_search": "query: Theta(log N), constant-factor change only",
            "oracle_interrogation": "query: Theta(N), about factor-two improvement only",
            "parity_query": "query: Theta(N), no asymptotic class change",
        }[selected]
        return {
            "selected_candidate": selected,
            "no_candidate_reason": None,
            "scheme_steps": [
                "prepare represented input",
                "apply matched primitive",
                "return requested output",
            ],
            "classical_baseline": str(analysis.get("classical_baseline", "UNKNOWN")),
            "quantum_query_complexity": q_complexity,
            "gate_complexity": None,
            "total_complexity": None,
            "claim_scope": ClaimScope.QUERY.value,
            "expert_questions": ["Are oracle and preparation costs acceptable in the target setting?"],
            "claim_flags": [],
            "self_assessment": "plausible_query_level_hypothesis",
        }

    def _prior_art_status(self, inputs: dict[str, Any]) -> str:
        return PriorArtStatus.KNOWN_CASE_RECOVERY.value if has_public_source_support(inputs) else PriorArtStatus.UNKNOWN.value

    def _novelty_status(self, inputs: dict[str, Any]) -> str:
        return NoveltyStatus.NOT_GLOBALLY_NOVEL.value if has_public_source_support(inputs) else NoveltyStatus.UNASSESSED.value

    def _review_notes(self, kind: str) -> list[str]:
        if kind in {
            "comparison_sorting",
            "ordered_search",
            "oracle_interrogation",
            "parity",
            "linear_system_stress",
        }:
            return ["No contradiction: deterministic validator should block stronger claims."]
        return ["No contradiction found; caveats remain authoritative limitations."]


def has_public_source_support(inputs: dict[str, Any]) -> bool:
    plausible = {
        item.get("primitive_id")
        for item in inputs.get("primitive_matches", [])
        if isinstance(item, dict) and item.get("strength") == MatchStrength.PLAUSIBLE.value
    }
    source_ids: set[str] = set()
    for primitive in inputs.get("registry_public_view", []):
        if isinstance(primitive, dict) and primitive.get("primitive_id") in plausible:
            source_ids.update(str(source_id) for source_id in primitive.get("source_ids", []))
    catalog_ids = {
        str(source.get("source_id"))
        for source in inputs.get("source_catalog_public_view", [])
        if isinstance(source, dict) and source.get("source_id")
    }
    return bool(source_ids & catalog_ids)

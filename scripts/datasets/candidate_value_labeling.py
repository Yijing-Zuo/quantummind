from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

HIGH_PRIORITY_EXPERT_REVIEW = "HIGH_PRIORITY_EXPERT_REVIEW"
USEFUL_SUBROUTINE_CANDIDATE = "USEFUL_SUBROUTINE_CANDIDATE"
GENERIC_GROVERIZATION = "GENERIC_GROVERIZATION"
GENERIC_ESTIMATION_WRAPPER = "GENERIC_ESTIMATION_WRAPPER"
REGISTRY_GAP_INTERESTING = "REGISTRY_GAP_INTERESTING"
BLOCKED_BY_ACCESS_OR_OUTPUT = "BLOCKED_BY_ACCESS_OR_OUTPUT"
LOW_VALUE_DUPLICATE_OR_VARIANT = "LOW_VALUE_DUPLICATE_OR_VARIANT"
LOW_VALUE_FULL_OUTPUT = "LOW_VALUE_FULL_OUTPUT"
REJECT_OR_NO_SIGNAL = "REJECT_OR_NO_SIGNAL"
REVIEW_MANUALLY = "REVIEW_MANUALLY"

SCORES: dict[str, int] = {
    HIGH_PRIORITY_EXPERT_REVIEW: 5,
    USEFUL_SUBROUTINE_CANDIDATE: 4,
    REGISTRY_GAP_INTERESTING: 4,
    BLOCKED_BY_ACCESS_OR_OUTPUT: 3,
    GENERIC_ESTIMATION_WRAPPER: 2,
    GENERIC_GROVERIZATION: 2,
    LOW_VALUE_DUPLICATE_OR_VARIANT: 1,
    LOW_VALUE_FULL_OUTPUT: 1,
    REJECT_OR_NO_SIGNAL: 0,
    REVIEW_MANUALLY: 2,
}

ACCESS_OUTPUT_BARRIER_TERMS = (
    "access",
    "oracle construction",
    "oracle_construction",
    "output",
    "promise",
    "readout",
    "state preparation",
    "state_preparation",
    "spectral gap",
    "spectral_gap",
    "condition number",
    "condition_number",
    "precision",
    "full output",
    "full-output",
)
BOUNDARY_TERMS = ("query-level", "query model", "query-model", "subroutine", "not end-to-end", "not an end-to-end")
DUPLICATE_TERMS = (
    "quick kruskal",
    "kruskal",
    "serang",
    "a*",
    "a star",
    "astar",
    "bidirectional a*",
    "adaptive a*",
    "memory-bounded a*",
)
FULL_OUTPUT_TERMS = (
    "full_solution",
    "full sequence",
    "full_sequence",
    "full classical",
    "full_classical",
    "full output",
    "full-output",
    "all marked items",
    "sorted order",
    "sorted_order",
    "path_or_tree",
    "full_oracle_string",
    "full_classical_vector",
)
GENERIC_GROVER_TERMS = (
    "brute force",
    "brute-force",
    "naive",
    "generic search",
    "search-witness",
    "search witness",
    "predicate over candidates",
    "arbitrary witness",
    "find a witness",
    "marked item",
    "marked-item",
)
GENERIC_ESTIMATION_TERMS = (
    "generic bounded random variable",
    "bounded random variable",
    "estimate a bounded mean",
    "estimate the mean",
    "count estimate",
    "counting probe",
    "marked-fraction",
    "source-specific estimator",
)
REGISTRY_GAP_TERMS = (
    "graph walk",
    "graph_walk",
    "quantum_walk",
    "marked vertex",
    "backtracking",
    "minimum finding",
    "quantum_minimum",
    "counting",
    "quantum_counting",
    "qsvt",
    "hamiltonian",
    "phase estimation",
    "missing primitive",
)
GENERIC_QUESTION_TERMS = (
    "can the task be reformulated",
    "required access, output contract, and promises",
    "should an expert review",
    "is there a quantum speedup",
)


@dataclass(frozen=True)
class CandidateValueResult:
    label: str
    score: int
    reason: str
    features: tuple[str, ...]


def label_candidate_value(record: Mapping[str, Any]) -> CandidateValueResult:
    """Return a deterministic, non-authoritative triage label for one summary row."""

    selected = _text(record.get("selected_candidate"))
    verdict = _text(record.get("verdict")).upper()
    scope = _text(record.get("scope")).upper()
    route = _text(record.get("route")).upper()
    weak = _list_of_mappings(record.get("weak_analogy_opportunities"))
    limitations = _list_of_text(record.get("limitations"))
    expert_questions = _list_of_text(record.get("expert_questions"))
    claim_flags = _list_of_text(record.get("claim_flags"))
    barriers = _list_of_text(record.get("barriers"))
    b_failures = _list_of_text(record.get("b_failures"))
    b_unknowns = _list_of_text(record.get("b_unknowns"))
    text = _combined_text(record, limitations, expert_questions, claim_flags, barriers, weak)

    features: list[str] = []
    if selected:
        features.append(f"selected={selected}")
    if weak:
        features.append("weak_analogy")
    if verdict:
        features.append(f"verdict={verdict}")
    if scope:
        features.append(f"scope={scope}")

    has_candidate = bool(selected)
    has_weak = bool(weak)
    full_output = _has_any(text, FULL_OUTPUT_TERMS) or _looks_full_output(record)
    access_output_blocked = _has_access_output_barrier(text, weak, b_failures, b_unknowns)
    generic_parent_variant = _has_any(_name_text(record), DUPLICATE_TERMS) or _truthy(record.get("duplicate_hint"))
    generic_grover = selected == "amplitude_amplification" and _has_any(text, GENERIC_GROVER_TERMS)
    generic_estimation = selected in {"amplitude_estimation", "quantum_counting"} and _is_generic_estimation(record, text)
    boundary_clear = _has_any(text, BOUNDARY_TERMS) and _has_any(text, ("oracle", "assumption", "introduced assumption"))
    specific_questions = _has_specific_questions(expert_questions)
    assumptions_explicit = boundary_clear or _has_any(text, ("coherent", "oracle_model_assumption", "introduced assumptions"))
    registry_gap = _has_registry_gap_signal(text, weak)
    source_specific = _has_source_specific_signal(record, text)

    if not verdict and not route and not has_candidate and not has_weak:
        return _result(REVIEW_MANUALLY, features + ["missing_decision"], "missing decision/candidate signal")

    if has_candidate and generic_parent_variant:
        return _result(
            LOW_VALUE_DUPLICATE_OR_VARIANT,
            features + ["duplicate_or_variant_name"],
            "parent algorithm name or duplicate hint indicates a repeated variant",
        )

    if generic_grover:
        return _result(
            GENERIC_GROVERIZATION,
            features + ["generic_witness_search"],
            "selected amplitude amplification appears to be a generic witness-search wrapper",
        )

    if generic_estimation:
        return _result(
            GENERIC_ESTIMATION_WRAPPER,
            features + ["generic_estimation_wrapper"],
            "selected estimation/counting primitive appears to wrap a generic bounded variable or count estimate",
        )

    if not has_candidate and has_weak and registry_gap and specific_questions:
        return _result(
            REGISTRY_GAP_INTERESTING,
            features + ["specific_registry_gap"],
            "negative run exposes a specific weak analogy or registry-expansion opportunity",
        )

    if access_output_blocked and (has_candidate or has_weak):
        return _result(
            BLOCKED_BY_ACCESS_OR_OUTPUT,
            features + ["access_output_or_promise_barrier"],
            "candidate or weak analogy is blocked by access, output, promise, readout, or precision prerequisites",
        )

    if full_output and not (has_candidate and boundary_clear and source_specific):
        return _result(
            LOW_VALUE_FULL_OUTPUT,
            features + ["full_output_dominates"],
            "full-output contract or limitations dominate without a clear subroutine payoff",
        )

    if not has_candidate:
        if has_weak and registry_gap:
            return _result(
                REGISTRY_GAP_INTERESTING,
                features + ["registry_gap"],
                "weak analogy names an explicitly missing primitive family",
            )
        if has_weak:
            return _result(
                BLOCKED_BY_ACCESS_OR_OUTPUT,
                features + ["weak_analogy_but_blocked"],
                "weak analogy exists but prerequisites are not satisfied",
            )
        return _result(
            REJECT_OR_NO_SIGNAL,
            features + ["no_candidate_no_weak_signal"],
            "no selected candidate, meaningful weak analogy, or useful registry gap",
        )

    if not expert_questions:
        return _result(
            REVIEW_MANUALLY,
            features + ["missing_expert_questions"],
            "selected candidate lacks expert questions needed for review prioritization",
        )

    if verdict in {"POSITIVE", "CONDITIONAL"} and scope == "QUERY" and boundary_clear and specific_questions and source_specific:
        return _result(
            HIGH_PRIORITY_EXPERT_REVIEW,
            features + ["query_positive", "specific_questions", "clear_boundary"],
            "query-level positive has explicit boundaries and specific expert-review questions",
        )

    if assumptions_explicit and scope in {"QUERY", "NONE", ""}:
        return _result(
            USEFUL_SUBROUTINE_CANDIDATE,
            features + ["subroutine_candidate", "explicit_assumptions"],
            "selected candidate is useful as an assumption-bearing query/subroutine hypothesis",
        )

    return _result(
        REVIEW_MANUALLY,
        features + ["conflicting_or_incomplete_features"],
        "rules conflict or required review-prioritization fields are incomplete",
    )


def _result(label: str, features: Sequence[str], reason: str) -> CandidateValueResult:
    return CandidateValueResult(label=label, score=SCORES[label], reason=reason, features=tuple(dict.fromkeys(features)))


def _combined_text(
    record: Mapping[str, Any],
    limitations: Sequence[str],
    expert_questions: Sequence[str],
    claim_flags: Sequence[str],
    barriers: Sequence[str],
    weak: Sequence[Mapping[str, Any]],
) -> str:
    parts = [
        _name_text(record),
        _text(record.get("probe_type")),
        _text(record.get("input_model")),
        _text(record.get("access_model")),
        _text(record.get("output_contract")),
        _text(record.get("original_output_contract")),
        _text(record.get("probe_output_contract")),
        _text(record.get("statement")),
        " ".join(_list_of_text(record.get("promises"))),
        " ".join(_list_of_text(record.get("introduced_assumptions"))),
        " ".join(limitations),
        " ".join(expert_questions),
        " ".join(claim_flags),
        " ".join(barriers),
    ]
    for item in weak:
        parts.extend(
            [
                _text(item.get("primitive_id")),
                " ".join(_list_of_text(item.get("missing_access_or_output_or_promises"))),
                _text(item.get("why_not_selected")),
                _text(item.get("possible_reformulation_question")),
            ]
        )
    return " ".join(part for part in parts if part).lower()


def _name_text(record: Mapping[str, Any]) -> str:
    return " ".join(
        _text(record.get(key)) for key in ("algorithm_name", "parent_algorithm_name", "probe_id", "algorithm_id") if _text(record.get(key))
    ).lower()


def _is_generic_estimation(record: Mapping[str, Any], text: str) -> bool:
    if not _has_any(text, GENERIC_ESTIMATION_TERMS):
        return False
    return not (_has_source_specific_signal(record, text) and _has_specific_questions(_list_of_text(record.get("expert_questions"))))


def _has_source_specific_signal(record: Mapping[str, Any], text: str) -> bool:
    name = _name_text(record)
    if not name or _has_any(name, ("brute", "naive", "generic")):
        return False
    if _has_any(name, ("lawrence gibbs", "motifsampler", "hnsw", "karger", "tarjan", "cohen", "liang", "barsky")):
        return True
    return _has_any(
        text,
        (
            "source-specific",
            "estimator variance",
            "convergence",
            "sample complexity",
            "graph traversal",
            "frontier",
            "minimum spanning",
            "motif",
            "sampler",
        ),
    )


def _has_registry_gap_signal(text: str, weak: Sequence[Mapping[str, Any]]) -> bool:
    if _has_any(text, REGISTRY_GAP_TERMS):
        return True
    return any(_has_any(_text(item.get("primitive_id")).lower(), REGISTRY_GAP_TERMS) for item in weak)


def _has_access_output_barrier(
    text: str,
    weak: Sequence[Mapping[str, Any]],
    b_failures: Sequence[str],
    b_unknowns: Sequence[str],
) -> bool:
    del text
    if any(rule in {"B4", "B5", "B6", "B7"} or rule.startswith(("B4_", "B5_", "B6_", "B7_")) for rule in (*b_failures, *b_unknowns)):
        return True
    for item in weak:
        missing = " ".join(_list_of_text(item.get("missing_access_or_output_or_promises"))).lower()
        if _has_any(missing, ACCESS_OUTPUT_BARRIER_TERMS):
            return True
    return False


def _has_specific_questions(questions: Sequence[str]) -> bool:
    specific = 0
    for question in questions:
        lowered = question.lower()
        if _has_any(lowered, GENERIC_QUESTION_TERMS):
            continue
        tokens = [token for token in lowered.replace("?", " ").replace(",", " ").split() if token]
        if len(tokens) >= 6 and _has_any(lowered, ("oracle", "output", "variance", "spectral", "gap", "sampler", "predicate", "cost")):
            specific += 1
    return specific > 0


def _looks_full_output(record: Mapping[str, Any]) -> bool:
    current_output = _text(record.get("output_contract")).lower()
    if _has_any(current_output, FULL_OUTPUT_TERMS):
        return True
    probe_output = _text(record.get("probe_output_contract")).lower()
    original_output = _text(record.get("original_output_contract")).lower()
    return not probe_output and _has_any(original_output, FULL_OUTPUT_TERMS)


def _has_any(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list_of_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.replace("|", ";").split(";") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None]
    return []


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]

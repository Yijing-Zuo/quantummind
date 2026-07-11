from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import (
    CandidateCard,
    CheckOutcome,
    CheckResult,
    ClaimScope,
    DecisionCard,
    EvidenceState,
    MatchStrength,
    NoveltyStatus,
    PrimitiveSpec,
    PriorArtStatus,
    Route,
    RunState,
    SpeedupClass,
    Verdict,
)

CLAIM_BOUNDARY = (
    "QuantumMindLite produces structured hypotheses for expert investigation; it does not "
    "prove new algorithms, end-to-end speedups, novelty, or expert validation."
)

RULE_IDS = (
    "B1_SELECTED_MATCH_CONSISTENCY",
    "B2_REGISTRY_AND_STRUCTURE_COMPATIBLE",
    "B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE",
    "B4_ACCESS_MODEL_COMPATIBLE",
    "B5_OUTPUT_CONTRACT_COMPATIBLE",
    "B6_REQUIRED_PROMISES_REPRESENTED",
    "B7_APPLICABLE_CRITICAL_BARRIER",
    "B8_SCOPE_NON_ESCALATION",
    "B9_PRIOR_ART_AND_NOVELTY",
    "B10_GOLD_NOT_VISIBLE",
)

_SCOPE_RANK = {
    ClaimScope.NONE: 0,
    ClaimScope.QUERY: 1,
    ClaimScope.GATE: 2,
    ClaimScope.END_TO_END: 3,
}

FORBIDDEN_GOLD_KEYS = {
    "allowed_verdicts",
    "answer",
    "authors",
    "classification",
    "evidence",
    "evidence_digest",
    "evidence_mapping",
    "expected_primitive",
    "expected_route",
    "expected_scope",
    "expected_selected_primitive",
    "expected_speedup_class",
    "expected_verdict",
    "forbidden_claim_ids",
    "forbidden_overclaims",
    "gold",
    "gold_answer",
    "gold_digest",
    "maximum_claim_scope",
    "no_plausible_primitive",
    "official_url",
    "paper_title",
    "public_digest",
    "required_caveats",
    "required_caveat_ids",
    "required_structure",
    "required_structure_ids",
    "result_type",
    "source_status",
    "source_url",
    "theorem_identifier",
}


def build_decision(state: RunState, registry: dict[str, PrimitiveSpec]) -> DecisionCard:
    snapshot = deepcopy(state)
    checks = run_b_checks(snapshot, registry)
    verdict, scope, reasons = _verdict(snapshot.candidate_card, checks, registry)
    return DecisionCard(
        authoritative_verdict=verdict,
        maximum_supported_claim_scope=scope,
        b_check_results=checks,
        d_route=route_decision(verdict, reasons),
        concise_reasons=reasons,
        claim_boundary_statement=CLAIM_BOUNDARY,
    )


def run_b_checks(state: RunState, registry: dict[str, PrimitiveSpec]) -> list[CheckResult]:
    candidate = state.candidate_card or CandidateCard()
    selected = candidate.selected_candidate
    return [
        _selected_match_consistency(candidate, registry),
        _registry_and_structure_compatible(state, selected, registry),
        _asymptotic_speedup_certificate(state, candidate, selected, registry),
        _access_model_compatible(state, selected, registry),
        _output_contract_compatible(state, selected, registry),
        _required_promises_represented(state, selected, registry),
        _applicable_blocking_barrier(candidate),
        _scope_non_escalation(candidate, selected, registry),
        _prior_art_and_novelty(candidate),
        _gold_not_visible(state.model_dump(mode="json")),
    ]


def route_decision(verdict: Verdict, reasons: list[str]) -> Route:
    del reasons
    if verdict is Verdict.INVALID:
        return Route.RERUN
    if verdict is Verdict.NEGATIVE:
        return Route.STOP
    if verdict is Verdict.CONDITIONAL:
        return Route.EXPERT_REVIEW_WITH_WARNINGS
    return Route.EXPERT_REVIEW


def _result(rule_id: str, outcome: CheckOutcome, reason: str, path: str) -> CheckResult:
    return CheckResult(rule_id=rule_id, outcome=outcome, reason=reason, evidence_path=path)


def _registry_spec(selected: str | None, registry: dict[str, PrimitiveSpec]) -> PrimitiveSpec | None:
    return registry.get(selected) if selected else None


def _selected_match_consistency(candidate: CandidateCard, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    unknown_matches = sorted({match.primitive_id for match in candidate.primitive_matches if match.primitive_id not in registry})
    if unknown_matches:
        return _result(
            "B1_SELECTED_MATCH_CONSISTENCY",
            CheckOutcome.FAIL,
            "primitive match IDs absent from registry: " + ", ".join(unknown_matches),
            "candidate_card.primitive_matches",
        )
    if candidate.selected_candidate:
        exact = [
            match
            for match in candidate.primitive_matches
            if match.primitive_id == candidate.selected_candidate and match.strength is MatchStrength.PLAUSIBLE
        ]
        ok = len(exact) == 1 and candidate.selected_candidate in registry and candidate.no_candidate_reason is None
        reason = "selected_candidate must equal exactly one PLAUSIBLE registry primitive match"
    else:
        has_plausible = any(match.strength is MatchStrength.PLAUSIBLE for match in candidate.primitive_matches)
        final_claim = bool(
            candidate.scheme_steps
            or candidate.quantum_query_complexity
            or candidate.gate_complexity
            or candidate.total_complexity
            or candidate.claim_scope is not ClaimScope.NONE
        )
        ok = bool(candidate.no_candidate_reason) and not has_plausible and not final_claim
        reason = "no-candidate result requires a reason, zero PLAUSIBLE matches, scope NONE, and no scheme or complexity claims"
    return _result(
        "B1_SELECTED_MATCH_CONSISTENCY",
        CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        reason,
        "candidate_card.selected_candidate",
    )


def _registry_and_structure_compatible(state: RunState, selected: str | None, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    if selected is None:
        return _result("B2_REGISTRY_AND_STRUCTURE_COMPATIBLE", CheckOutcome.NOT_APPLICABLE, "no candidate", "candidate_card")
    spec = _registry_spec(selected, registry)
    if spec is None:
        return _result(
            "B2_REGISTRY_AND_STRUCTURE_COMPATIBLE",
            CheckOutcome.FAIL,
            f"selected primitive {selected!r} is absent from registry",
            "candidate_card.selected_candidate",
        )
    structures = set(state.analysis_card.canonical_structure_ids if state.analysis_card else [])
    missing = sorted(set(spec.required_structure_ids) - structures)
    return _result(
        "B2_REGISTRY_AND_STRUCTURE_COMPATIBLE",
        CheckOutcome.FAIL if missing else CheckOutcome.PASS,
        "missing required structures: " + ", ".join(missing) if missing else "registry structures are represented",
        "analysis_card.canonical_structure_ids",
    )


def _asymptotic_speedup_certificate(
    state: RunState,
    candidate: CandidateCard,
    selected: str | None,
    registry: dict[str, PrimitiveSpec],
) -> CheckResult:
    if selected is None:
        return _result("B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE", CheckOutcome.NOT_APPLICABLE, "no candidate", "candidate_card")
    spec = _registry_spec(selected, registry)
    if spec is None:
        return _result("B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE", CheckOutcome.FAIL, "no registry certificate", "registry")
    if spec.speedup_class is not SpeedupClass.ASYMPTOTIC:
        return _result(
            "B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE",
            CheckOutcome.FAIL,
            f"registry speedup class is {spec.speedup_class.value}, not ASYMPTOTIC",
            "registry.speedup_class",
        )
    missing = []
    if not candidate.scheme_steps:
        missing.append("scheme_steps")
    if not _known_text(candidate.classical_baseline) or not (state.analysis_card and _known_text(state.analysis_card.classical_baseline)):
        missing.append("classical_baseline")
    if not _has_relevant_quantum_complexity(candidate):
        missing.append("quantum_complexity")
    return _result(
        "B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE",
        CheckOutcome.UNKNOWN if missing else CheckOutcome.PASS,
        "missing certificate fields: " + ", ".join(missing) if missing else "registry and candidate contain an asymptotic certificate",
        "candidate_card.scheme_steps",
    )


def _access_model_compatible(state: RunState, selected: str | None, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    spec = _registry_spec(selected, registry)
    if selected is None or spec is None:
        return _result("B4_ACCESS_MODEL_COMPATIBLE", CheckOutcome.NOT_APPLICABLE, "no selected registry primitive", "problem_card")
    access = state.problem_card.access_model if state.problem_card else ""
    ok = access in spec.allowed_access_models
    return _result(
        "B4_ACCESS_MODEL_COMPATIBLE",
        CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        f"access {access!r} must satisfy OR-list {spec.allowed_access_models}",
        "problem_card.access_model",
    )


def _output_contract_compatible(state: RunState, selected: str | None, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    spec = _registry_spec(selected, registry)
    if selected is None or spec is None:
        return _result("B5_OUTPUT_CONTRACT_COMPATIBLE", CheckOutcome.NOT_APPLICABLE, "no selected registry primitive", "problem_card")
    problem_output = state.problem_card.output_contract if state.problem_card else ""
    ok = problem_output in spec.allowed_output_contracts
    return _result(
        "B5_OUTPUT_CONTRACT_COMPATIBLE",
        CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        f"output {problem_output!r} must satisfy {spec.allowed_output_contracts}",
        "problem_card.output_contract",
    )


def _required_promises_represented(state: RunState, selected: str | None, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    spec = _registry_spec(selected, registry)
    if selected is None or spec is None:
        return _result("B6_REQUIRED_PROMISES_REPRESENTED", CheckOutcome.NOT_APPLICABLE, "no selected registry primitive", "problem_card")
    required = set(spec.required_promises)
    represented = set(state.problem_card.promises if state.problem_card else [])
    missing = required - represented
    return _result(
        "B6_REQUIRED_PROMISES_REPRESENTED",
        CheckOutcome.UNKNOWN if missing else CheckOutcome.PASS,
        "missing required promises: " + ", ".join(sorted(missing)) if missing else "all registry promises are represented",
        "problem_card.promises",
    )


def _applicable_blocking_barrier(candidate: CandidateCard) -> CheckResult:
    supported = [
        barrier.barrier_id
        for barrier in candidate.barriers
        if barrier.applicable is EvidenceState.SUPPORTED and candidate.claim_scope in barrier.blocked_scopes
    ]
    unknown = [
        barrier.barrier_id
        for barrier in candidate.barriers
        if barrier.applicable is EvidenceState.UNKNOWN and candidate.claim_scope in barrier.blocked_scopes
    ]
    if supported:
        return _result(
            "B7_APPLICABLE_CRITICAL_BARRIER",
            CheckOutcome.FAIL,
            "supported blocking barrier(s): " + ", ".join(supported),
            "candidate_card.barriers",
        )
    return _result(
        "B7_APPLICABLE_CRITICAL_BARRIER",
        CheckOutcome.UNKNOWN if unknown else CheckOutcome.PASS,
        "unknown blocking barrier(s): " + ", ".join(unknown) if unknown else "no applicable blocking barrier",
        "candidate_card.barriers",
    )


def _scope_non_escalation(candidate: CandidateCard, selected: str | None, registry: dict[str, PrimitiveSpec]) -> CheckResult:
    if selected is None:
        ok = candidate.claim_scope is ClaimScope.NONE
        return _result(
            "B8_SCOPE_NON_ESCALATION",
            CheckOutcome.PASS if ok else CheckOutcome.FAIL,
            "no-candidate result must claim scope NONE",
            "candidate_card.claim_scope",
        )
    spec = _registry_spec(selected, registry)
    supported = spec.supported_claim_scope if spec else ClaimScope.NONE
    ok = _SCOPE_RANK[candidate.claim_scope] <= _SCOPE_RANK[supported]
    return _result(
        "B8_SCOPE_NON_ESCALATION",
        CheckOutcome.PASS if ok else CheckOutcome.FAIL,
        f"claimed {candidate.claim_scope.value} must not exceed {supported.value}",
        "candidate_card.claim_scope",
    )


def _prior_art_and_novelty(candidate: CandidateCard) -> CheckResult:
    prior = candidate.prior_art_status
    novelty = candidate.novelty_status
    global_claim = novelty is NoveltyStatus.GLOBAL_NOVELTY_CLAIM
    known = prior in {PriorArtStatus.KNOWN_CASE_RECOVERY, PriorArtStatus.DIRECT_PRIOR_ART}
    if known and global_claim:
        outcome = CheckOutcome.FAIL
        reason = "known-case or direct prior art cannot support global novelty"
    elif prior is PriorArtStatus.UNKNOWN and global_claim:
        outcome = CheckOutcome.UNKNOWN
        reason = "unknown literature status cannot support global novelty"
    else:
        outcome = CheckOutcome.PASS
        reason = "no forbidden global-novelty claim"
    return _result("B9_PRIOR_ART_AND_NOVELTY", outcome, reason, "candidate_card.novelty_status")


def _gold_not_visible(data: Any) -> CheckResult:
    found = sorted(_find_forbidden_keys(data))
    return _result(
        "B10_GOLD_NOT_VISIBLE",
        CheckOutcome.FAIL if found else CheckOutcome.PASS,
        "forbidden evaluator-only keys: " + ", ".join(found) if found else "no evaluator-only keys",
        "run_state",
    )


def _known_text(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip().upper() != "UNKNOWN")


def _has_relevant_quantum_complexity(candidate: CandidateCard) -> bool:
    if candidate.claim_scope is ClaimScope.QUERY:
        return _known_text(candidate.quantum_query_complexity)
    if candidate.claim_scope is ClaimScope.GATE:
        return _known_text(candidate.gate_complexity)
    if candidate.claim_scope is ClaimScope.END_TO_END:
        return _known_text(candidate.total_complexity)
    return False


def _find_forbidden_keys(data: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_GOLD_KEYS:
                found.add(str(key))
            found |= _find_forbidden_keys(value)
    elif isinstance(data, list):
        for item in data:
            found |= _find_forbidden_keys(item)
    return found


def _verdict(
    candidate: CandidateCard | None, checks: list[CheckResult], registry: dict[str, PrimitiveSpec]
) -> tuple[Verdict, ClaimScope, list[str]]:
    if candidate is None:
        return Verdict.INVALID, ClaimScope.NONE, ["missing CandidateCard"]
    outcomes = {item.rule_id: item.outcome for item in checks}
    invalid_failures = {
        "B1_SELECTED_MATCH_CONSISTENCY",
        "B2_REGISTRY_AND_STRUCTURE_COMPATIBLE",
        "B4_ACCESS_MODEL_COMPATIBLE",
        "B5_OUTPUT_CONTRACT_COMPATIBLE",
        "B8_SCOPE_NON_ESCALATION",
        "B9_PRIOR_ART_AND_NOVELTY",
        "B10_GOLD_NOT_VISIBLE",
    }
    if any(outcomes[rule] is CheckOutcome.FAIL for rule in invalid_failures):
        return Verdict.INVALID, ClaimScope.NONE, ["malformed, incompatible, or evaluator-leaked runtime state"]
    if candidate.no_candidate_reason:
        return Verdict.NEGATIVE, ClaimScope.NONE, [candidate.no_candidate_reason]
    if outcomes["B7_APPLICABLE_CRITICAL_BARRIER"] is CheckOutcome.FAIL:
        return Verdict.NEGATIVE, ClaimScope.NONE, [_reason(checks, "B7_APPLICABLE_CRITICAL_BARRIER")]
    if outcomes["B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE"] is CheckOutcome.FAIL:
        return Verdict.NEGATIVE, ClaimScope.NONE, [_reason(checks, "B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE")]
    conditional = {
        "B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE",
        "B6_REQUIRED_PROMISES_REPRESENTED",
        "B7_APPLICABLE_CRITICAL_BARRIER",
        "B9_PRIOR_ART_AND_NOVELTY",
    }
    if any(outcomes[rule] is CheckOutcome.UNKNOWN for rule in conditional):
        return Verdict.CONDITIONAL, ClaimScope.NONE, ["required evidence remains unknown or conditional"]
    selected = candidate.selected_candidate
    scope = candidate.claim_scope
    if selected in registry and _SCOPE_RANK[scope] > _SCOPE_RANK[registry[selected].supported_claim_scope]:
        scope = registry[selected].supported_claim_scope
    return Verdict.POSITIVE, scope, ["all ten registry-relative obligations pass for the claimed scope"]


def _reason(checks: list[CheckResult], rule_id: str) -> str:
    return next(item.reason for item in checks if item.rule_id == rule_id)

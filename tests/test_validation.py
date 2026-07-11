from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

from quantummindlite.evaluation import load_public_case
from quantummindlite.models import (
    BarrierAssessment,
    CandidateCard,
    CheckOutcome,
    ClaimScope,
    EvidenceState,
    MatchStrength,
    NoveltyStatus,
    PrimitiveMatch,
    PriorArtStatus,
    ProblemCard,
    Route,
    RunState,
    Verdict,
)
from quantummindlite.registry import load_registry
from quantummindlite.validation import RULE_IDS, build_decision, route_decision, run_b_checks
from quantummindlite.workflow import Orchestrator


def _positive_state(tmp_path: Path) -> RunState:
    result = Orchestrator().run(load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path)
    return result.state


def _candidate(state: RunState) -> CandidateCard:
    assert state.candidate_card is not None
    return state.candidate_card


def _problem_promises_absent(state: RunState) -> None:
    assert state.problem_card is not None
    state.problem_card.promises = []


def _wrong_structure(state: RunState) -> None:
    assert state.analysis_card is not None
    state.analysis_card.canonical_structure_ids = ["wrong_structure"]


def _access_mismatch(state: RunState) -> None:
    assert state.problem_card is not None
    state.problem_card.access_model = "sample_only"


def _selected_without_match(state: RunState) -> None:
    _candidate(state).selected_candidate = "amplitude_estimation"


def _selected_not_supported(state: RunState) -> None:
    _candidate(state).primitive_matches[0].strength = MatchStrength.NOT_SUPPORTED


def _empty_scheme_and_complexity(state: RunState) -> None:
    candidate = _candidate(state)
    candidate.scheme_steps.clear()
    candidate.quantum_query_complexity = None


def _output_mismatch(state: RunState) -> None:
    assert state.problem_card is not None
    state.problem_card.output_contract = "full_classical_vector"


def _unknown_prior_art_global_novelty(state: RunState) -> None:
    candidate = _candidate(state)
    candidate.prior_art_status = PriorArtStatus.UNKNOWN
    candidate.novelty_status = NoveltyStatus.GLOBAL_NOVELTY_CLAIM


def test_all_ten_b_rules_are_present(tmp_path: Path) -> None:
    checks = run_b_checks(_positive_state(tmp_path), load_registry())
    assert tuple(item.rule_id for item in checks) == RULE_IDS


def test_clean_positive_state_is_not_falsely_blocked(tmp_path: Path) -> None:
    decision = build_decision(_positive_state(tmp_path), load_registry())
    assert decision.authoritative_verdict is Verdict.POSITIVE
    assert decision.maximum_supported_claim_scope is ClaimScope.QUERY


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        (
            "selected candidate without matching PrimitiveMatch",
            _selected_without_match,
            Verdict.INVALID,
        ),
        (
            "selected NOT_SUPPORTED match",
            _selected_not_supported,
            Verdict.INVALID,
        ),
        (
            "wrong canonical structure",
            _wrong_structure,
            Verdict.INVALID,
        ),
        (
            "missing registry promise from ProblemCard",
            _problem_promises_absent,
            Verdict.CONDITIONAL,
        ),
        (
            "empty scheme and complexity",
            _empty_scheme_and_complexity,
            Verdict.CONDITIONAL,
        ),
        (
            "access mismatch",
            _access_mismatch,
            Verdict.INVALID,
        ),
        (
            "output mismatch",
            _output_mismatch,
            Verdict.INVALID,
        ),
        (
            "unknown prior art with global novelty claim",
            _unknown_prior_art_global_novelty,
            Verdict.CONDITIONAL,
        ),
    ],
)
def test_positive_theorem_premise_mutations_prevent_positive(
    name: str,
    mutate: Callable[[RunState], object],
    expected: Verdict,
    tmp_path: Path,
) -> None:
    state = _positive_state(tmp_path)
    mutate(state)
    decision = build_decision(state, load_registry())
    assert decision.authoritative_verdict is expected, name
    assert decision.authoritative_verdict is not Verdict.POSITIVE


def test_end_to_end_barrier_does_not_block_query_claim(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).barriers = [
        BarrierAssessment(
            barrier_id="end_to_end_only",
            description="blocks only end-to-end claims",
            applicable=EvidenceState.SUPPORTED,
            blocked_scopes=[ClaimScope.END_TO_END],
        )
    ]
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.POSITIVE


def test_query_barrier_blocks_query_claim(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).barriers = [
        BarrierAssessment(
            barrier_id="loading_condition_readout",
            description="blocks query claims",
            applicable=EvidenceState.SUPPORTED,
            blocked_scopes=[ClaimScope.QUERY],
        )
    ]
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.NEGATIVE


@pytest.mark.parametrize(
    ("case_id", "primitive_id"),
    [
        ("QM-PB-007", "ordered_search"),
        ("QM-PB-008", "oracle_interrogation"),
        ("QM-PB-009", "parity_query"),
    ],
)
def test_constant_factor_pathways_are_not_asymptotic_positive(case_id: str, primitive_id: str, tmp_path: Path) -> None:
    result = Orchestrator().run(load_public_case(case_id).model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == primitive_id
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE


def test_unknown_catalog_blocker_is_conditional(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).barriers = [
        BarrierAssessment(
            barrier_id="loading_condition_readout",
            description="unknown query blocker",
            applicable=EvidenceState.UNKNOWN,
            blocked_scopes=[ClaimScope.QUERY],
        )
    ]
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.CONDITIONAL


def test_supported_nonblocking_caveat_never_vetoes(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).barriers = [
        BarrierAssessment(
            barrier_id="precision_dependence",
            description="precision must be tracked",
            applicable=EvidenceState.SUPPORTED,
            blocked_scopes=[],
        )
    ]
    b7 = next(item for item in run_b_checks(state, load_registry()) if item.rule_id == "B7_APPLICABLE_CRITICAL_BARRIER")
    assert b7.outcome is CheckOutcome.PASS
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.POSITIVE


def test_no_candidate_is_negative_and_requires_none_scope() -> None:
    no_candidate = RunState(
        problem_card=ProblemCard(
            statement="x",
            input_model="x",
            access_model="comparison_oracle",
            output_contract="sorted_order",
        ),
        candidate_card=CandidateCard(no_candidate_reason="blocked"),
    )
    assert build_decision(no_candidate, load_registry()).authoritative_verdict is Verdict.NEGATIVE
    no_candidate.candidate_card = CandidateCard(no_candidate_reason="blocked", claim_scope=ClaimScope.QUERY)
    assert build_decision(no_candidate, load_registry()).authoritative_verdict is Verdict.INVALID


def test_b5_uses_problem_card_output_only(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).limitations.append("prose says the output is a full vector")
    b5 = next(item for item in run_b_checks(state, load_registry()) if item.rule_id == "B5_OUTPUT_CONTRACT_COMPATIBLE")
    assert b5.outcome is CheckOutcome.PASS


def test_b6_uses_problem_card_promises_only(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    assert state.problem_card is not None
    state.problem_card.promises = []
    _candidate(state).limitations.append("prose says marked_item_exists")
    b6 = next(item for item in run_b_checks(state, load_registry()) if item.rule_id == "B6_REQUIRED_PROMISES_REPRESENTED")
    assert b6.outcome is CheckOutcome.UNKNOWN


def test_gold_key_injection_is_invalid_and_state_is_not_mutated(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    before = deepcopy(state).model_dump(mode="json")
    state.messages.append({"gold": {"expected_primitive": "amplitude_amplification"}})
    decision = build_decision(state, load_registry())
    assert decision.authoritative_verdict is Verdict.INVALID
    del state.messages[-1]
    assert state.model_dump(mode="json") == before


def test_route_mapping_cannot_upgrade_hard_outcomes() -> None:
    assert route_decision(Verdict.INVALID, []) is Route.RERUN
    assert route_decision(Verdict.NEGATIVE, []) is Route.STOP
    assert route_decision(Verdict.CONDITIONAL, []) is Route.EXPERT_REVIEW_WITH_WARNINGS
    assert route_decision(Verdict.POSITIVE, ["known-case recovery"]) is Route.EXPERT_REVIEW


def test_selected_candidate_must_have_exactly_one_plausible_match(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    candidate = _candidate(state)
    candidate.primitive_matches = [
        PrimitiveMatch(primitive_id="amplitude_amplification", strength=MatchStrength.PLAUSIBLE),
        PrimitiveMatch(primitive_id="amplitude_amplification", strength=MatchStrength.PLAUSIBLE),
    ]
    candidate.selected_candidate = "amplitude_amplification"
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.INVALID


def test_known_case_cannot_claim_global_novelty(tmp_path: Path) -> None:
    state = _positive_state(tmp_path)
    _candidate(state).novelty_status = NoveltyStatus.GLOBAL_NOVELTY_CLAIM
    b9 = next(item for item in run_b_checks(state, load_registry()) if item.rule_id == "B9_PRIOR_ART_AND_NOVELTY")
    assert b9.outcome is CheckOutcome.FAIL
    assert build_decision(state, load_registry()).authoritative_verdict is Verdict.INVALID

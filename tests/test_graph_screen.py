from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest

from quantummindlite._graph_screen import (
    AccessUpgradeStatus,
    BaselineStatus,
    OracleStatus,
    OutputAlignment,
    ResearchDisposition,
    screen_evidence_graph,
)
from quantummindlite.evaluation import load_public_case
from quantummindlite.graph import (
    EvidenceGraph,
    GraphStatus,
    GraphVerifierReport,
    build_evidence_graph,
    verify_evidence_graph,
)
from quantummindlite.llm import MockLLMProvider
from quantummindlite.models import RunState, Verdict
from quantummindlite.workflow import Orchestrator


@dataclass(frozen=True)
class ScreenCase:
    orchestrator: Orchestrator
    state: RunState
    graph: EvidenceGraph
    report: GraphVerifierReport


@pytest.fixture
def screen_case(tmp_path: Path) -> ScreenCase:
    orchestrator = Orchestrator(provider=MockLLMProvider())
    public = load_public_case("QM-PB-001", orchestrator.resource_root)
    result = orchestrator.run(public.model_dump(mode="json"), output_dir=tmp_path, run_id="screen-case")
    graph = build_evidence_graph(
        result.state,
        result.decision,
        orchestrator.registry,
        run_id=result.run_id,
        barrier_catalog=orchestrator.barrier_catalog,
    )
    return ScreenCase(orchestrator, result.state, graph, verify_evidence_graph(graph))


def _features(report: GraphVerifierReport, *, selected: str, generic: bool = False) -> GraphVerifierReport:
    features = dict(report.features)
    features.update(
        selected=selected,
        generic_wrapper_motif=generic,
        generic_estimation_motif=False,
    )
    return report.model_copy(update={"features": features})


def _ready_for_expert(case: ScreenCase) -> tuple[RunState, GraphVerifierReport]:
    state = deepcopy(case.state)
    assert state.problem_card is not None
    assert state.analysis_card is not None
    assert state.candidate_card is not None
    state.problem_card.statement = (
        "Original output context: an exact or approximate numerical value for the marked fraction. "
        "Original bottleneck: estimating that fraction."
    )
    state.problem_card.access_model = "coherent_boolean_oracle"
    state.problem_card.output_contract = "additive_count_estimate"
    state.problem_card.promises = [
        "finite_search_space",
        "coherent_boolean_oracle_available",
        "count_precision_specified",
        "oracle_construction_provided",
    ]
    state.analysis_card.classical_baseline = "Best known classical baseline: Theta(1/epsilon^2)"
    state.candidate_card.selected_candidate = "quantum_counting"
    state.candidate_card.classical_baseline = "Best known classical baseline: Theta(1/epsilon^2)"
    state.candidate_card.claim_flags = ["ORACLE_CONSTRUCTION_PROVIDED"]
    return state, _features(case.report, selected="quantum_counting")


def _full_output_probe(case: ScreenCase, *, subroutine: bool) -> tuple[RunState, GraphVerifierReport]:
    state = deepcopy(case.state)
    assert state.problem_card is not None
    assert state.analysis_card is not None
    assert state.candidate_card is not None
    suffix = " This is a subroutine/query-model probe." if subroutine else ""
    state.problem_card.statement = (
        "Original output context: the graph-specific object requested by the application. "
        f"Original bottleneck: finding the complete object.{suffix}"
    )
    state.problem_card.access_model = "coherent_markov_chain_walk_oracle"
    state.problem_card.output_contract = "one_marked_vertex"
    state.problem_card.promises = ["oracle_construction_provided"]
    state.analysis_card.classical_baseline = "Best known classical baseline: Theta(N)"
    state.candidate_card.selected_candidate = "quantum_walk_marked_vertex_search"
    state.candidate_card.classical_baseline = "Best known classical baseline: Theta(N)"
    state.candidate_card.claim_flags = ["ORACLE_CONSTRUCTION_PROVIDED"]
    return state, _features(case.report, selected="quantum_walk_marked_vertex_search")


def test_keep_is_only_emitted_for_an_accepted_pass_graph(screen_case: ScreenCase) -> None:
    state, report = _ready_for_expert(screen_case)

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.research_disposition is ResearchDisposition.KEEP_FOR_EXPERT_REVIEW
    assert report.graph_status is GraphStatus.PASS
    assert report.claim_accepted is True


@pytest.mark.parametrize("invalidity", ["graph_fail", "invalid_verdict"])
def test_graph_failure_or_invalid_verdict_yields_invalid_state(
    screen_case: ScreenCase,
    invalidity: str,
) -> None:
    state, report = _ready_for_expert(screen_case)
    update = {"graph_status": GraphStatus.FAIL} if invalidity == "graph_fail" else {"authoritative_verdict": Verdict.INVALID}
    invalid = report.model_copy(update=update)

    screened = screen_evidence_graph(state, screen_case.graph, invalid, screen_case.orchestrator.registry)

    assert screened.research_disposition is ResearchDisposition.INVALID_STATE


def test_unaccepted_b_claim_is_never_kept(screen_case: ScreenCase) -> None:
    state, report = _ready_for_expert(screen_case)
    unaccepted = report.model_copy(update={"claim_accepted": False})

    screened = screen_evidence_graph(state, screen_case.graph, unaccepted, screen_case.orchestrator.registry)

    assert screened.research_disposition is ResearchDisposition.REFORMULATE
    assert "S0_B_CLAIM_NOT_ACCEPTED" in screened.hard_blockers


def test_full_output_to_witness_without_subroutine_is_rejected(screen_case: ScreenCase) -> None:
    state, report = _full_output_probe(screen_case, subroutine=False)

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.output_alignment is OutputAlignment.OUTPUT_MISMATCH
    assert screened.research_disposition is ResearchDisposition.REJECT_TASK_MISMATCH


def test_full_output_subroutine_probe_is_diagnostic_and_reformulated(screen_case: ScreenCase) -> None:
    state, report = _full_output_probe(screen_case, subroutine=True)

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.output_alignment is OutputAlignment.DIAGNOSTIC_ONLY
    assert screened.research_disposition is ResearchDisposition.REFORMULATE


def test_oracle_model_assumption_stays_black_box_and_unverified(screen_case: ScreenCase) -> None:
    state, report = _ready_for_expert(screen_case)
    assert state.problem_card is not None
    assert state.candidate_card is not None
    state.problem_card.promises = ["oracle_model_assumption"]
    state.candidate_card.claim_flags = []

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.oracle_status is OracleStatus.BLACK_BOX_ASSUMPTION
    assert screened.access_upgrade_status is AccessUpgradeStatus.UNVERIFIED
    assert screened.research_disposition is ResearchDisposition.REFORMULATE


def test_generic_amplitude_black_box_is_demoted(screen_case: ScreenCase) -> None:
    state = deepcopy(screen_case.state)
    assert state.problem_card is not None
    assert state.candidate_card is not None
    state.problem_card.promises.append("oracle_model_assumption")
    report = _features(screen_case.report, selected="amplitude_amplification", generic=True)

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.oracle_status is OracleStatus.BLACK_BOX_ASSUMPTION
    assert screened.research_disposition is ResearchDisposition.DEMOTE_GENERIC


def test_unverified_baseline_requires_literature_search(screen_case: ScreenCase) -> None:
    state, report = _ready_for_expert(screen_case)
    assert state.analysis_card is not None
    assert state.candidate_card is not None
    state.analysis_card.classical_baseline = "Theta(1/epsilon^2)"
    state.candidate_card.classical_baseline = "Theta(1/epsilon^2)"

    screened = screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert screened.baseline_status is BaselineStatus.BASELINE_UNVERIFIED
    assert screened.research_disposition is ResearchDisposition.LITERATURE_SEARCH_FIRST


def test_screening_does_not_mutate_inputs(screen_case: ScreenCase) -> None:
    state, report = _ready_for_expert(screen_case)
    state_before = state.model_dump(mode="json")
    graph_before = screen_case.graph.model_dump(mode="json")
    report_before = report.model_dump(mode="json")
    registry_before = deepcopy(screen_case.orchestrator.registry)

    screen_evidence_graph(state, screen_case.graph, report, screen_case.orchestrator.registry)

    assert state.model_dump(mode="json") == state_before
    assert screen_case.graph.model_dump(mode="json") == graph_before
    assert report.model_dump(mode="json") == report_before
    assert screen_case.orchestrator.registry == registry_before

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from quantummindlite.evaluation import load_public_case
from quantummindlite.graph import (
    EdgeType,
    EvidenceGraph,
    GraphCheckOutcome,
    GraphStatus,
    GraphVerifierReport,
    NodeType,
    build_evidence_graph,
    process_run_dir,
    verify_evidence_graph,
)
from quantummindlite.llm import MockLLMProvider
from quantummindlite.messages import ActionType
from quantummindlite.models import (
    CheckOutcome,
    CheckResult,
    ClaimScope,
    Verdict,
    WeakAnalogyOpportunity,
)
from quantummindlite.validation import RULE_IDS, build_decision
from quantummindlite.workflow import Orchestrator, WorkflowResult

_GRAPH_ARTIFACTS = (
    "evidence_graph.json",
    "graph_verifier_report.json",
    "graph_summary.json",
)
_SUMMARY_ADAPTER = TypeAdapter(dict[str, Any])


def _run_case(
    case_id: str,
    output_dir: Path,
    *,
    run_id: str | None = None,
) -> tuple[Orchestrator, WorkflowResult]:
    orchestrator = Orchestrator(provider=MockLLMProvider())
    public = load_public_case(case_id, orchestrator.resource_root)
    result = orchestrator.run(
        public.model_dump(mode="json"),
        output_dir=output_dir,
        run_id=run_id or case_id,
    )
    return orchestrator, result


def _build_graph(orchestrator: Orchestrator, result: WorkflowResult) -> EvidenceGraph:
    return build_evidence_graph(
        result.state,
        result.decision,
        orchestrator.registry,
        run_id=result.run_id,
        barrier_catalog=orchestrator.barrier_catalog,
    )


@pytest.fixture
def positive_case(tmp_path: Path) -> tuple[Orchestrator, WorkflowResult]:
    return _run_case("QM-PB-001", tmp_path)


def test_positive_graph_and_report_are_deterministic_with_ten_b_checks(
    positive_case: tuple[Orchestrator, WorkflowResult],
) -> None:
    orchestrator, result = positive_case
    first = _build_graph(orchestrator, result)
    second = _build_graph(orchestrator, result)
    first_report = verify_evidence_graph(first)

    assert first == second
    assert first_report == verify_evidence_graph(second)
    assert first_report.graph_status is GraphStatus.PASS
    assert first_report.claim_accepted is True

    b_nodes = [node for node in first.nodes if node.node_type is NodeType.B_CHECK]
    projected = [CheckResult.model_validate(node.payload) for node in b_nodes]
    assert len(result.decision.b_check_results) == len(b_nodes) == len(RULE_IDS) == 10
    assert {item.rule_id for item in projected} == set(RULE_IDS)


def test_minimal_support_excludes_weak_analogies(
    positive_case: tuple[Orchestrator, WorkflowResult],
) -> None:
    orchestrator, result = positive_case
    state = deepcopy(result.state)
    assert state.candidate_card is not None
    state.candidate_card.weak_analogy_opportunities.append(
        WeakAnalogyOpportunity(
            primitive_id="amplitude_estimation",
            missing_access_or_output_or_promises=["coherent estimation access is absent"],
            why_not_selected="Structural resemblance does not establish the prerequisites.",
            possible_reformulation_question="Can the missing coherent access be supplied?",
        )
    )
    decision = build_decision(state, orchestrator.registry)
    graph = build_evidence_graph(
        state,
        decision,
        orchestrator.registry,
        run_id=result.run_id,
        barrier_catalog=orchestrator.barrier_catalog,
    )
    report = verify_evidence_graph(graph)
    weak_ids = {node.node_id for node in graph.nodes if node.node_type is NodeType.WEAK_ANALOGY}

    assert weak_ids
    assert weak_ids.isdisjoint(report.minimal_support_subgraph["nodes"])
    assert report.claim_accepted is True


@pytest.mark.parametrize("edge_type", [EdgeType.SUPPORTS_MATCH, EdgeType.SUPPORTS_CLAIM])
def test_missing_critical_support_edge_fails_closed(
    positive_case: tuple[Orchestrator, WorkflowResult],
    edge_type: EdgeType,
) -> None:
    orchestrator, result = positive_case
    graph = _build_graph(orchestrator, result)
    critical = [edge for edge in graph.edges if edge.edge_type is edge_type]
    assert len(critical) == 1
    tampered = graph.model_copy(update={"edges": [edge for edge in graph.edges if edge.edge_id != critical[0].edge_id]})

    report = verify_evidence_graph(tampered)
    outcomes = {check.rule_id: check.outcome for check in report.graph_checks}
    assert outcomes["G1_CLAIM_SUPPORT_PATH"] is GraphCheckOutcome.FAIL
    assert outcomes["G4_CONTRADICTION_FREE_STATE"] is GraphCheckOutcome.FAIL
    assert report.graph_status is GraphStatus.FAIL
    assert report.claim_accepted is False


def test_graph_id_changes_with_semantic_content(
    positive_case: tuple[Orchestrator, WorkflowResult],
) -> None:
    orchestrator, result = positive_case
    original = _build_graph(orchestrator, result)
    state = deepcopy(result.state)
    assert state.candidate_card is not None
    state.candidate_card.classical_baseline += " under a stricter comparison model"
    decision = build_decision(state, orchestrator.registry)
    changed = build_evidence_graph(
        state,
        decision,
        orchestrator.registry,
        run_id=result.run_id,
        barrier_catalog=orchestrator.barrier_catalog,
    )

    assert changed.graph_id != original.graph_id


@pytest.mark.parametrize("case_id", ["QM-PB-006", "QM-PB-007", "QM-PB-008", "QM-PB-009"])
def test_negative_cases_are_not_upgraded(case_id: str, tmp_path: Path) -> None:
    orchestrator, result = _run_case(case_id, tmp_path)
    report = verify_evidence_graph(_build_graph(orchestrator, result))

    assert result.decision.authoritative_verdict is Verdict.NEGATIVE
    assert result.decision.maximum_supported_claim_scope is ClaimScope.NONE
    assert report.authoritative_verdict is Verdict.NEGATIVE
    assert report.authoritative_scope is ClaimScope.NONE
    assert report.claim_accepted is False


def test_scope_escalation_is_invalid_and_attributed(
    positive_case: tuple[Orchestrator, WorkflowResult],
) -> None:
    orchestrator, result = positive_case
    state = deepcopy(result.state)
    assert state.candidate_card is not None
    state.candidate_card.claim_scope = ClaimScope.END_TO_END
    decision = build_decision(state, orchestrator.registry)
    b8 = next(item for item in decision.b_check_results if item.rule_id == "B8_SCOPE_NON_ESCALATION")

    assert decision.authoritative_verdict is Verdict.INVALID
    assert decision.maximum_supported_claim_scope is ClaimScope.NONE
    assert b8.outcome is CheckOutcome.FAIL
    assert b8.evidence_path == "candidate_card.claim_scope"

    graph = build_evidence_graph(
        state,
        decision,
        orchestrator.registry,
        run_id=result.run_id,
        barrier_catalog=orchestrator.barrier_catalog,
    )
    report = verify_evidence_graph(graph)
    g4 = next(item for item in report.graph_checks if item.rule_id == "G4_CONTRADICTION_FREE_STATE")
    assert report.claim_accepted is False
    assert g4.outcome is GraphCheckOutcome.FAIL
    assert g4.culprit_field == "candidate_card.claim_scope"
    assert g4.owner_action is ActionType.GENERATE_SCHEME


def test_process_run_dir_rejects_stale_decision(tmp_path: Path) -> None:
    orchestrator, result = _run_case("QM-PB-001", tmp_path)
    stale = result.decision.model_copy(update={"authoritative_verdict": Verdict.NEGATIVE})
    (result.run_dir / "decision.json").write_text(stale.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="stale or tampered decision"):
        process_run_dir(result.run_dir, root=orchestrator.resource_root)


def test_process_run_dir_write_modes_and_artifact_round_trip(tmp_path: Path) -> None:
    dry_orchestrator, dry_result = _run_case("QM-PB-001", tmp_path, run_id="dry-run")
    process_run_dir(dry_result.run_dir, root=dry_orchestrator.resource_root, write=False)
    assert not any((dry_result.run_dir / name).exists() for name in _GRAPH_ARTIFACTS)

    orchestrator, result = _run_case("QM-PB-001", tmp_path, run_id="write-run")
    graph, report, summary = process_run_dir(
        result.run_dir,
        root=orchestrator.resource_root,
        write=True,
    )
    graph_path, report_path, summary_path = (result.run_dir / name for name in _GRAPH_ARTIFACTS)
    assert all(path.exists() for path in (graph_path, report_path, summary_path))
    assert EvidenceGraph.model_validate_json(graph_path.read_text(encoding="utf-8")) == graph
    assert GraphVerifierReport.model_validate_json(report_path.read_text(encoding="utf-8")) == report
    assert _SUMMARY_ADAPTER.validate_json(summary_path.read_text(encoding="utf-8")) == summary

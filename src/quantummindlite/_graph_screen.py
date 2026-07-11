from __future__ import annotations

from enum import Enum

from pydantic import Field

from .graph import EvidenceGraph, GraphStatus, GraphVerifierReport
from .models import EvidenceState, PrimitiveSpec, RunState, StrictModel, Verdict

SCREENING_VERSION = "QAEG-screen-v0.1"


class OutputType(str, Enum):
    WITNESS = "WITNESS"
    SCALAR = "SCALAR"
    FULL_RESULT = "FULL_RESULT"
    DECISION = "DECISION"
    GENERATOR = "GENERATOR"
    UNKNOWN = "UNKNOWN"


class OutputAlignment(str, Enum):
    EXACT_OUTPUT_MATCH = "EXACT_OUTPUT_MATCH"
    SUFFICIENT_SUBPROBLEM = "SUFFICIENT_SUBPROBLEM"
    RECONSTRUCTABLE = "RECONSTRUCTABLE"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    OUTPUT_MISMATCH = "OUTPUT_MISMATCH"
    UNKNOWN = "UNKNOWN"


class AccessUpgradeStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    JUSTIFIED = "JUSTIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class OracleStatus(str, Enum):
    EXPLICIT_CONSTRUCTION = "EXPLICIT_CONSTRUCTION"
    PARTIAL_CONSTRUCTION = "PARTIAL_CONSTRUCTION"
    BLACK_BOX_ASSUMPTION = "BLACK_BOX_ASSUMPTION"
    HIDDEN_HARDNESS_RISK = "HIDDEN_HARDNESS_RISK"
    CIRCULAR_ORACLE = "CIRCULAR_ORACLE"
    UNKNOWN = "UNKNOWN"


class BaselineStatus(str, Enum):
    BEST_VISIBLE = "BEST_VISIBLE"
    BASELINE_UNVERIFIED = "BASELINE_UNVERIFIED"
    BASELINE_DOMINATED = "BASELINE_DOMINATED"
    UNKNOWN = "UNKNOWN"


class ResearchDisposition(str, Enum):
    INVALID_STATE = "INVALID_STATE"
    SOURCE_REPAIR_REQUIRED = "SOURCE_REPAIR_REQUIRED"
    REJECT_TASK_MISMATCH = "REJECT_TASK_MISMATCH"
    DEMOTE_GENERIC = "DEMOTE_GENERIC"
    DEMOTE_TO_BENCHMARK = "DEMOTE_TO_BENCHMARK"
    REFORMULATE = "REFORMULATE"
    LITERATURE_SEARCH_FIRST = "LITERATURE_SEARCH_FIRST"
    KEEP_FOR_EXPERT_REVIEW = "KEEP_FOR_EXPERT_REVIEW"


class ScreeningReport(StrictModel):
    screening_version: str = SCREENING_VERSION
    graph_id: str
    run_id: str
    research_disposition: ResearchDisposition
    screening_reasons: list[str]
    hard_blockers: list[str] = Field(default_factory=list)
    unknown_obligations: list[str] = Field(default_factory=list)
    original_output_type: OutputType
    candidate_output_type: OutputType
    output_alignment: OutputAlignment
    access_provided: str
    access_required: list[str] = Field(default_factory=list)
    access_upgrade_status: AccessUpgradeStatus
    oracle_status: OracleStatus
    baseline_status: BaselineStatus
    candidate_universe: str


_FULL_OUTPUT_PREFIXES = (
    "the graph-specific object requested",
    "pattern occurrence positions",
    "a path, path cost, or predecessor structure",
    "the requested geometric structure",
    "a minimum spanning tree or forest",
    "the matrix product or bilinear multiplication output",
    "the requested string matching, alignment, indexing, distance, or transformation result",
    "the optimal value, witness, schedule, segmentation, or table-derived solution",
    "an optimal or approximate feasible solution",
    "a state estimate, map, path, configuration sequence",
    "the requested matrix, decomposition, solution vector",
    "nearest-neighbor or approximate nearest-neighbor identifiers",
    "a transformed image, segmentation, quantization",
    "a maintained data structure representation",
    "a solved linear system",
)
_SCALAR_OUTPUT_PREFIXES = (
    "an exact or approximate numerical value",
    "a sample, estimate, or approximate value",
)


def screen_evidence_graph(
    state: RunState,
    graph: EvidenceGraph,
    graph_report: GraphVerifierReport,
    registry: dict[str, PrimitiveSpec],
) -> ScreeningReport:
    """Screen scientific review value without changing graph or B/D outcomes."""

    problem = state.problem_card
    candidate = state.candidate_card
    selected = candidate.selected_candidate if candidate else None
    spec = registry.get(selected) if selected else None
    text = _screenable_text(state)
    flags = {item.upper() for item in candidate.claim_flags} if candidate else set()
    original_output = _original_output_type(problem.statement if problem else "")
    candidate_output = _candidate_output_type(problem.output_contract if problem else "")
    alignment = _output_alignment(original_output, candidate_output, text)
    access = _access_status(state, spec, flags)
    oracle = _oracle_status(state, flags, text)
    baseline = _baseline_status(state, flags, text)
    blockers = _hard_blockers(graph, graph_report, alignment, oracle, flags)
    unknowns = _unknown_obligations(alignment, access, oracle, baseline)
    if graph.graph_id != graph_report.graph_id or graph.run_id != graph_report.run_id:
        disposition, trigger = ResearchDisposition.INVALID_STATE, "S0_GRAPH_REPORT_ID_MISMATCH"
    else:
        disposition, trigger = _disposition(graph_report, alignment, access, oracle, baseline, flags)
    reasons = [
        trigger,
        f"S1_OUTPUT_{alignment.value}",
        f"S2_ACCESS_{access.value}",
        f"S3_ORACLE_{oracle.value}",
        f"S4_BASELINE_{baseline.value}",
    ]
    if disposition is ResearchDisposition.KEEP_FOR_EXPERT_REVIEW and not (
        graph_report.graph_status is GraphStatus.PASS and graph_report.claim_accepted
    ):
        raise ValueError("KEEP_FOR_EXPERT_REVIEW requires an accepted PASS graph")
    return ScreeningReport(
        graph_id=graph.graph_id,
        run_id=graph.run_id,
        research_disposition=disposition,
        screening_reasons=list(dict.fromkeys(reasons)),
        hard_blockers=blockers,
        unknown_obligations=unknowns,
        original_output_type=original_output,
        candidate_output_type=candidate_output,
        output_alignment=alignment,
        access_provided=problem.access_model if problem else "UNKNOWN",
        access_required=spec.allowed_access_models if spec else [],
        access_upgrade_status=access,
        oracle_status=oracle,
        baseline_status=baseline,
        candidate_universe=_candidate_universe(state, flags),
    )


def _original_output_type(statement: str) -> OutputType:
    marker = "original output context:"
    lowered = statement.lower()
    if marker not in lowered:
        return OutputType.UNKNOWN
    context = lowered.split(marker, 1)[1].split("original bottleneck", 1)[0].strip()
    if not context or " it does not output" in context or len(context) < 24:
        return OutputType.UNKNOWN
    if context.startswith(_SCALAR_OUTPUT_PREFIXES):
        return OutputType.SCALAR
    if context.startswith(_FULL_OUTPUT_PREFIXES):
        return OutputType.FULL_RESULT
    if context.startswith("a decision result") and not any(word in context for word in ("witness", "count", "value")):
        return OutputType.DECISION
    if "generator" in context:
        return OutputType.GENERATOR
    return OutputType.UNKNOWN


def _candidate_output_type(output_contract: str) -> OutputType:
    if output_contract in {"one_witness", "one_solution_leaf", "one_marked_vertex", "argmin_item"}:
        return OutputType.WITNESS
    if output_contract in {"additive_estimate", "additive_count_estimate", "exact_value"}:
        return OutputType.SCALAR
    if output_contract in {"decision", "decision_bit"}:
        return OutputType.DECISION
    return OutputType.UNKNOWN


def _output_alignment(original: OutputType, candidate: OutputType, text: str) -> OutputAlignment:
    if OutputType.UNKNOWN in {original, candidate}:
        return OutputAlignment.UNKNOWN
    if original is candidate or original is OutputType.SCALAR and candidate is OutputType.SCALAR:
        return OutputAlignment.EXACT_OUTPUT_MATCH
    if "output_reconstruction_proved" in text:
        return OutputAlignment.RECONSTRUCTABLE
    if "sufficient_subproblem_proved" in text:
        return OutputAlignment.SUFFICIENT_SUBPROBLEM
    if "subroutine/query-model probe" in text or "subroutine probe" in text:
        return OutputAlignment.DIAGNOSTIC_ONLY
    return OutputAlignment.OUTPUT_MISMATCH


def _access_status(state: RunState, spec: PrimitiveSpec | None, flags: set[str]) -> AccessUpgradeStatus:
    problem = state.problem_card
    if not problem or not spec:
        return AccessUpgradeStatus.UNKNOWN
    if problem.access_model not in spec.allowed_access_models:
        return AccessUpgradeStatus.UNVERIFIED
    if "oracle_model_assumption" in problem.promises or "ACCESS_MODEL_MISMATCH" in flags:
        return AccessUpgradeStatus.UNVERIFIED
    if "oracle_construction_provided" in problem.promises or "ORACLE_CONSTRUCTION_PROVIDED" in flags:
        return AccessUpgradeStatus.JUSTIFIED
    return AccessUpgradeStatus.CONSISTENT


def _oracle_status(state: RunState, flags: set[str], text: str) -> OracleStatus:
    candidate = state.candidate_card
    problem = state.problem_card
    if not candidate or not candidate.selected_candidate:
        return OracleStatus.UNKNOWN
    if flags & {"CIRCULAR_ORACLE", "ORACLE_REQUIRES_KNOWN_SOLUTION"}:
        return OracleStatus.CIRCULAR_ORACLE
    risks = ("requires solving the original", "requires solving a global", "oracle hides the original computational burden")
    if any(item in text for item in risks):
        return OracleStatus.HIDDEN_HARDNESS_RISK
    barriers = {item.barrier_id: item.applicable for item in candidate.barriers}
    if problem and "oracle_model_assumption" in problem.promises or barriers.get("oracle_construction") is EvidenceState.SUPPORTED:
        return OracleStatus.BLACK_BOX_ASSUMPTION
    if flags & {"ORACLE_CONSTRUCTION_PROVIDED", "EXPLICIT_ORACLE_CONSTRUCTION"}:
        return OracleStatus.EXPLICIT_CONSTRUCTION
    if flags & {"PARTIAL_ORACLE_CONSTRUCTION", "ORACLE_SKETCH_ONLY"}:
        return OracleStatus.PARTIAL_CONSTRUCTION
    return OracleStatus.UNKNOWN


def _baseline_status(state: RunState, flags: set[str], text: str) -> BaselineStatus:
    analysis = state.analysis_card
    candidate = state.candidate_card
    baselines = [analysis.classical_baseline if analysis else "", candidate.classical_baseline if candidate else ""]
    if not any(item and item != "UNKNOWN" for item in baselines):
        return BaselineStatus.UNKNOWN
    if flags & {"BASELINE_DOMINATED", "BASELINE_NOT_COMPARABLE"} or "baseline is not comparable" in text:
        return BaselineStatus.BASELINE_DOMINATED
    if "best known" in " ".join(baselines).lower():
        return BaselineStatus.BEST_VISIBLE
    return BaselineStatus.BASELINE_UNVERIFIED


def _disposition(
    report: GraphVerifierReport,
    output: OutputAlignment,
    access: AccessUpgradeStatus,
    oracle: OracleStatus,
    baseline: BaselineStatus,
    flags: set[str],
) -> tuple[ResearchDisposition, str]:
    if report.graph_status is GraphStatus.FAIL or report.authoritative_verdict is Verdict.INVALID:
        return ResearchDisposition.INVALID_STATE, "S0_INVALID_GRAPH_STATE"
    if flags & {"SOURCE_MISMATCH_CONFIRMED", "WRONG_SOURCE_RECORD"}:
        return ResearchDisposition.SOURCE_REPAIR_REQUIRED, "S6_CONFIRMED_SOURCE_MISMATCH"
    if output is OutputAlignment.OUTPUT_MISMATCH or oracle is OracleStatus.CIRCULAR_ORACLE:
        return ResearchDisposition.REJECT_TASK_MISMATCH, "S1_TASK_OR_ORACLE_MISMATCH"
    selected = str(report.features.get("selected", ""))
    generic_shell = selected in {"amplitude_amplification", "amplitude_estimation"} and oracle in {
        OracleStatus.BLACK_BOX_ASSUMPTION,
        OracleStatus.HIDDEN_HARDNESS_RISK,
    }
    if report.features.get("generic_wrapper_motif") or report.features.get("generic_estimation_motif") or generic_shell:
        return ResearchDisposition.DEMOTE_GENERIC, "S5_GENERIC_WRAPPER"
    if "BENCHMARK_ONLY" in flags:
        return ResearchDisposition.DEMOTE_TO_BENCHMARK, "S5_BENCHMARK_ONLY"
    unresolved = (
        not report.claim_accepted
        or output in {OutputAlignment.UNKNOWN, OutputAlignment.DIAGNOSTIC_ONLY}
        or access in {AccessUpgradeStatus.UNKNOWN, AccessUpgradeStatus.UNVERIFIED}
        or oracle
        in {
            OracleStatus.UNKNOWN,
            OracleStatus.BLACK_BOX_ASSUMPTION,
            OracleStatus.HIDDEN_HARDNESS_RISK,
            OracleStatus.PARTIAL_CONSTRUCTION,
        }
    )
    if unresolved:
        return ResearchDisposition.REFORMULATE, "S7_UNRESOLVED_REFORMULATION"
    if baseline is not BaselineStatus.BEST_VISIBLE:
        return ResearchDisposition.LITERATURE_SEARCH_FIRST, "S4_BASELINE_REVIEW_REQUIRED"
    return ResearchDisposition.KEEP_FOR_EXPERT_REVIEW, "S8_READY_FOR_EXPERT_REVIEW"


def _hard_blockers(
    graph: EvidenceGraph,
    report: GraphVerifierReport,
    output: OutputAlignment,
    oracle: OracleStatus,
    flags: set[str],
) -> list[str]:
    blockers: list[str] = []
    if graph.graph_id != report.graph_id or graph.run_id != report.run_id:
        blockers.append("S0_GRAPH_REPORT_ID_MISMATCH")
    if report.graph_status is GraphStatus.FAIL:
        blockers.append("S0_GRAPH_FAIL")
    if not report.claim_accepted:
        blockers.append("S0_B_CLAIM_NOT_ACCEPTED")
    if output is OutputAlignment.OUTPUT_MISMATCH:
        blockers.append("S1_OUTPUT_MISMATCH")
    if oracle is OracleStatus.CIRCULAR_ORACLE:
        blockers.append("S3_CIRCULAR_ORACLE")
    if flags & {"SOURCE_MISMATCH_CONFIRMED", "WRONG_SOURCE_RECORD"}:
        blockers.append("S6_SOURCE_MISMATCH")
    return blockers


def _unknown_obligations(
    output: OutputAlignment,
    access: AccessUpgradeStatus,
    oracle: OracleStatus,
    baseline: BaselineStatus,
) -> list[str]:
    unknowns: list[str] = []
    if output in {OutputAlignment.UNKNOWN, OutputAlignment.DIAGNOSTIC_ONLY}:
        unknowns.append("S1_OUTPUT_RECOVERABILITY")
    if access in {AccessUpgradeStatus.UNKNOWN, AccessUpgradeStatus.UNVERIFIED}:
        unknowns.append("S2_ACCESS_UPGRADE")
    if oracle not in {OracleStatus.EXPLICIT_CONSTRUCTION}:
        unknowns.append("S3_ORACLE_CONSTRUCTION")
    if baseline is not BaselineStatus.BEST_VISIBLE:
        unknowns.append("S4_BEST_BASELINE")
    return unknowns


def _candidate_universe(state: RunState, flags: set[str]) -> str:
    problem = state.problem_card
    if not problem:
        return "UNKNOWN"
    if "CANDIDATE_UNIVERSE_UNSPECIFIED" in flags or any("candidate universe" in item.lower() for item in problem.ambiguities):
        return "UNSPECIFIED"
    return problem.input_model


def _screenable_text(state: RunState) -> str:
    problem = state.problem_card
    candidate = state.candidate_card
    parts = [problem.statement, *problem.ambiguities] if problem else []
    if candidate:
        parts.extend([*candidate.scheme_steps, *candidate.limitations, *candidate.consistency_review_notes, *candidate.claim_flags])
    return "\n".join(parts).lower()


__all__ = [
    "AccessUpgradeStatus",
    "BaselineStatus",
    "OracleStatus",
    "OutputAlignment",
    "OutputType",
    "ResearchDisposition",
    "SCREENING_VERSION",
    "ScreeningReport",
    "screen_evidence_graph",
]

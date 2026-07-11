from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph import (
    GRAPH_VERSION,
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    GraphVerifierReport,
)
from .models import BarrierSpec, DecisionCard, PrimitiveSpec, RunState
from .registry import load_runtime_registry, resource_root
from .storage import RunStore, digest_json
from .validation import build_decision


def build_evidence_graph(
    state: RunState,
    decision: DecisionCard,
    registry: dict[str, PrimitiveSpec],
    *,
    run_id: str = "unknown-run",
    barrier_catalog: dict[str, BarrierSpec] | None = None,
) -> EvidenceGraph:
    """Compile an existing run without invoking an LLM or changing B/D."""

    from ._graph_projection import project_evidence_graph

    return project_evidence_graph(
        state,
        decision,
        registry,
        run_id=run_id,
        barrier_catalog=barrier_catalog,
    )


def process_run_dir(
    run_dir: Path,
    *,
    root: Path | None = None,
    write: bool = True,
) -> tuple[EvidenceGraph, GraphVerifierReport, dict[str, Any]]:
    from ._graph_verify import verify_evidence_graph

    base = resource_root(root)
    registry, barriers = load_runtime_registry(base)
    state = RunState.model_validate_json((run_dir / "state.json").read_text(encoding="utf-8"))
    saved = DecisionCard.model_validate_json((run_dir / "decision.json").read_text(encoding="utf-8"))
    if saved != build_decision(state, registry):
        raise ValueError(f"stale or tampered decision.json in {run_dir}")
    graph = build_evidence_graph(
        state,
        saved,
        registry,
        run_id=run_dir.name,
        barrier_catalog=barriers,
    )
    report = verify_evidence_graph(graph)
    summary = graph_summary(run_dir, graph, report)
    if write:
        store = RunStore(run_dir=run_dir, run_id=run_dir.name)
        store.write_json("evidence_graph.json", graph.model_dump(mode="json"))
        store.write_json("graph_verifier_report.json", report.model_dump(mode="json"))
        store.write_json("graph_summary.json", summary)
    return graph, report, summary


def graph_summary(
    run_dir: Path,
    graph: EvidenceGraph,
    report: GraphVerifierReport,
) -> dict[str, Any]:
    from .graph import GraphCheckOutcome

    return {
        "run_dir": str(run_dir),
        "shard": run_dir.parent.name,
        "run": run_dir.name,
        "graph_status": report.graph_status.value,
        "claim_accepted": report.claim_accepted,
        "verdict": report.authoritative_verdict.value,
        "scope": report.authoritative_scope.value,
        **report.features,
        "failed_graph_rules": ";".join(item.rule_id for item in report.graph_checks if item.outcome is GraphCheckOutcome.FAIL),
        "unknown_graph_rules": ";".join(item.rule_id for item in report.graph_checks if item.outcome is GraphCheckOutcome.UNKNOWN),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "support_node_count": len(report.minimal_support_subgraph["nodes"]),
        "support_edge_count": len(report.minimal_support_subgraph["edges"]),
    }


def graph_digest(run_id: str, nodes: list[GraphNode], edges: list[GraphEdge]) -> str:
    content = {
        "version": GRAPH_VERSION,
        "run_id": run_id,
        "nodes": [node.model_dump(mode="json") for node in sorted(nodes, key=lambda item: item.node_id)],
        "edges": [edge.model_dump(mode="json") for edge in sorted(edges, key=lambda item: item.edge_id)],
    }
    return "qaeg:" + digest_json(content)

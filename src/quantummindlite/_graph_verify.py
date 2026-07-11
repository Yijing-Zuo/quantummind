from __future__ import annotations

from typing import Any

from ._graph_compile import graph_digest
from .graph import (
    GENERIC_SEARCH_STRUCTURES,
    GENERIC_STRUCTURES,
    GRAPH_VERSION,
    EdgeType,
    EvidenceGraph,
    GraphCheckOutcome,
    GraphCheckResult,
    GraphNode,
    GraphStatus,
    GraphVerifierReport,
    NodeType,
)
from .messages import ActionType
from .models import (
    CheckOutcome,
    ClaimScope,
    EvidenceState,
    MatchStrength,
    NoveltyStatus,
    PriorArtStatus,
    Verdict,
)
from .validation import RULE_IDS


def verify_evidence_graph(graph: EvidenceGraph) -> GraphVerifierReport:
    """Verify graph nodes and edges rather than trusting a metadata cache."""

    nodes = {node.node_id: node for node in graph.nodes}
    claims = [node for node in graph.nodes if node.node_type is NodeType.CLAIM]
    claim = claims[0] if len(claims) == 1 else None
    verdict = Verdict(claim.payload["authoritative_verdict"]) if claim else Verdict.INVALID
    scope = ClaimScope(claim.payload["authoritative_scope"]) if claim else ClaimScope.NONE
    checks = [
        _support_path(graph, claim),
        _obligations(graph, claim, verdict),
        _barriers(graph, claim, verdict),
        _integrity(graph, claim, nodes),
        _novelty(graph),
        _generic_motif(graph, claim, verdict),
    ]
    hard = checks[:5]
    if any(item.outcome is GraphCheckOutcome.FAIL for item in hard):
        status = GraphStatus.FAIL
    elif any(item.outcome is GraphCheckOutcome.UNKNOWN for item in hard):
        status = GraphStatus.WARN
    else:
        status = GraphStatus.PASS
    accepted = verdict is Verdict.POSITIVE and status is GraphStatus.PASS and all(item.outcome is GraphCheckOutcome.PASS for item in hard)
    return GraphVerifierReport(
        graph_id=graph.graph_id,
        run_id=graph.run_id,
        graph_status=status,
        claim_accepted=accepted,
        authoritative_verdict=verdict,
        authoritative_scope=scope,
        minimal_support_subgraph=minimal_support(graph),
        graph_checks=checks,
        features=_features(graph, claim),
    )


def minimal_support(graph: EvidenceGraph) -> dict[str, list[str]]:
    claims = [node.node_id for node in graph.nodes if node.node_type is NodeType.CLAIM]
    if len(claims) != 1:
        return {"nodes": [], "edges": []}
    keep = {claims[0]}
    used: set[str] = set()
    incoming = {
        EdgeType.SUPPORTS_MATCH,
        EdgeType.SUPPORTS_CLAIM,
        EdgeType.GROUNDS_CLAIM,
        EdgeType.OBLIGATION_FOR,
        EdgeType.SATISFIES,
        EdgeType.BLOCKS_SCOPE,
        EdgeType.BOUNDS_SCOPE,
        EdgeType.SUPPORTS_COMPLEXITY,
        EdgeType.BOUNDS_NOVELTY,
        EdgeType.CHECKS_CLAIM,
    }
    outgoing = {EdgeType.INSTANTIATES, EdgeType.DECIDED_AS}
    changed = True
    while changed:
        changed = False
        for edge in graph.edges:
            other: str | None = None
            if edge.target in keep and edge.edge_type in incoming:
                other = edge.source
            elif edge.source in keep and edge.edge_type in outgoing:
                other = edge.target
            if other:
                used.add(edge.edge_id)
                if other not in keep:
                    keep.add(other)
                    changed = True
    return {"nodes": sorted(keep), "edges": sorted(used)}


def _support_path(graph: EvidenceGraph, claim: GraphNode | None) -> GraphCheckResult:
    rule = "G1_CLAIM_SUPPORT_PATH"
    if not claim:
        return _check(rule, GraphCheckOutcome.FAIL, "graph must contain exactly one claim")
    verdict = Verdict(claim.payload["authoritative_verdict"])
    selected = claim.payload.get("selected_candidate")
    if not selected or verdict is Verdict.NEGATIVE:
        return _check(
            rule,
            GraphCheckOutcome.NOT_APPLICABLE,
            "no accepted asymptotic claim requires a support path",
        )
    edges = {(edge.source, edge.target, edge.edge_type) for edge in graph.edges}
    matches = [
        node
        for node in graph.nodes
        if node.node_type is NodeType.PRIMITIVE_MATCH
        and node.payload.get("primitive_id") == selected
        and node.status == MatchStrength.PLAUSIBLE.value
        and (node.node_id, claim.node_id, EdgeType.SUPPORTS_CLAIM) in edges
    ]
    primitives = [
        node
        for node in graph.nodes
        if node.node_type is NodeType.REGISTRY_PRIMITIVE
        and node.label == selected
        and node.payload.get("known")
        and (node.node_id, claim.node_id, EdgeType.GROUNDS_CLAIM) in edges
    ]
    missing: list[str] = []
    if len(matches) != 1:
        missing.append("exactly one plausible selected match")
    if len(primitives) != 1:
        missing.append("known registry primitive")
    if matches and primitives:
        link = (matches[0].node_id, primitives[0].node_id, EdgeType.INSTANTIATES)
        if link not in edges:
            missing.append("match-to-primitive edge")
    required = primitives[0].payload.get("required_structure_ids", []) if primitives else []
    for structure in required:
        structure_nodes = [node for node in graph.nodes if node.node_type is NodeType.STRUCTURE and node.label == structure]
        if not matches or not any((node.node_id, matches[0].node_id, EdgeType.SUPPORTS_MATCH) in edges for node in structure_nodes):
            missing.append(f"structure path:{structure}")
    support = [
        node
        for node in graph.nodes
        if node.node_type in {NodeType.SCHEME, NodeType.COMPLEXITY}
        and node.status == "SATISFIED"
        and (node.node_id, claim.node_id, EdgeType.SUPPORTS_COMPLEXITY) in edges
    ]
    if len(support) != 4:
        missing.append("scheme and scope-relevant complexity certificate")
    if not missing:
        return _check(rule, GraphCheckOutcome.PASS, "selected claim has a complete graph support path")
    outcome = GraphCheckOutcome.UNKNOWN if verdict is Verdict.CONDITIONAL else GraphCheckOutcome.FAIL
    return _check(
        rule,
        outcome,
        "missing " + ", ".join(missing),
        "candidate_card",
        claim.owner_action,
    )


def _obligations(
    graph: EvidenceGraph,
    claim: GraphNode | None,
    verdict: Verdict,
) -> GraphCheckResult:
    rule = "G2_SCOPE_DEPENDENT_OBLIGATIONS"
    if not claim or not claim.payload.get("selected_candidate") or verdict is Verdict.NEGATIVE:
        return _check(rule, GraphCheckOutcome.NOT_APPLICABLE, "no accepted asymptotic claim")
    obligations = [node for node in graph.nodes if node.node_type is NodeType.OBLIGATION]
    expected = {
        "selection",
        "registry",
        "structures",
        "complexity_certificate",
        "access_model",
        "output_contract",
        "promises",
        "scope",
    }
    by_key = {node.payload.get("key"): node for node in obligations}
    missing = sorted(key for key in expected if key not in by_key)
    unresolved = sorted(key for key in expected if key in by_key and by_key[key].status != "SATISFIED")
    if missing:
        return _check(
            rule,
            GraphCheckOutcome.FAIL,
            "obligation nodes missing: " + ", ".join(missing),
            "registry",
        )
    if unresolved:
        outcome = GraphCheckOutcome.UNKNOWN if all(by_key[key].status == "UNKNOWN" for key in unresolved) else GraphCheckOutcome.FAIL
        culprit = ";".join(str(by_key[key].field_path) for key in unresolved if by_key[key].field_path)
        return _check(
            rule,
            outcome,
            "unresolved obligations: " + ", ".join(unresolved),
            culprit,
            _field_owner(graph, culprit),
        )
    return _check(rule, GraphCheckOutcome.PASS, "all registry-derived obligations are satisfied")


def _barriers(
    graph: EvidenceGraph,
    claim: GraphNode | None,
    verdict: Verdict,
) -> GraphCheckResult:
    rule = "G3_BARRIER_DOMINANCE"
    if not claim:
        return _check(rule, GraphCheckOutcome.FAIL, "claim node missing")
    blocking = [edge for edge in graph.edges if edge.target == claim.node_id and edge.edge_type is EdgeType.BLOCKS_SCOPE]
    supported = [_node(graph, edge.source).label for edge in blocking if edge.status == EvidenceState.SUPPORTED.value]
    unknown = [_node(graph, edge.source).label for edge in blocking if edge.status == EvidenceState.UNKNOWN.value]
    if verdict is Verdict.NEGATIVE:
        return _check(rule, GraphCheckOutcome.PASS, "negative boundary preserves any blocking barrier")
    if supported:
        return _check(
            rule,
            GraphCheckOutcome.FAIL,
            "supported barriers block the claim: " + ", ".join(supported),
            "candidate_card.barriers",
            _field_owner(graph, "candidate_card.barriers"),
        )
    if unknown:
        return _check(
            rule,
            GraphCheckOutcome.UNKNOWN,
            "unresolved barriers may block the claim: " + ", ".join(unknown),
            "candidate_card.barriers",
            _field_owner(graph, "candidate_card.barriers"),
        )
    return _check(rule, GraphCheckOutcome.PASS, "no represented barrier blocks the claimed scope")


def _integrity(
    graph: EvidenceGraph,
    claim: GraphNode | None,
    nodes: dict[str, GraphNode],
) -> GraphCheckResult:
    problems: list[str] = []
    if len(nodes) != len(graph.nodes):
        problems.append("duplicate node IDs")
    if len({edge.edge_id for edge in graph.edges}) != len(graph.edges):
        problems.append("duplicate edge IDs")
    if any(edge.source not in nodes or edge.target not in nodes for edge in graph.edges):
        problems.append("dangling edge endpoint")
    if graph.graph_version != GRAPH_VERSION:
        problems.append("unsupported graph version")
    if graph.graph_id != graph_digest(graph.run_id, graph.nodes, graph.edges):
        problems.append("graph digest mismatch")
    b_checks = {node.label: node for node in graph.nodes if node.node_type is NodeType.B_CHECK}
    if set(b_checks) != set(RULE_IDS) or len(b_checks) != len(RULE_IDS):
        problems.append("B1-B10 projection incomplete")
    decisions = [node for node in graph.nodes if node.node_type is NodeType.DECISION]
    decision = decisions[0] if len(decisions) == 1 else None
    if decision:
        saved_checks = {item["rule_id"]: item["outcome"] for item in decision.payload.get("b_check_results", [])}
        projected = {rule: node.status for rule, node in b_checks.items()}
        if saved_checks != projected:
            problems.append("B-check node content differs from DecisionCard")
        if claim and (
            claim.payload.get("authoritative_verdict") != decision.payload.get("authoritative_verdict")
            or claim.payload.get("authoritative_scope") != decision.payload.get("maximum_supported_claim_scope")
            or claim.payload.get("route") != decision.payload.get("d_route")
        ):
            problems.append("claim boundary differs from DecisionCard")
    else:
        problems.append("decision node missing or duplicated")
    if sum(node.node_type is NodeType.PRIOR_ART for node in graph.nodes) != 1:
        problems.append("prior-art boundary missing or duplicated")
    if sum(node.node_type is NodeType.NOVELTY for node in graph.nodes) != 1:
        problems.append("novelty boundary missing or duplicated")
    if not claim:
        problems.append("claim node missing or duplicated")
    elif claim.payload.get("authoritative_verdict") == Verdict.INVALID.value:
        problems.append("authoritative B verdict is INVALID")
    elif not claim.payload.get("selected_candidate") and claim.payload.get("has_final_claim"):
        problems.append("no-candidate state contains final claim fields")
    if problems:
        culprit = _first_failed_path(b_checks) or "run_state"
        return _check(
            "G4_CONTRADICTION_FREE_STATE",
            GraphCheckOutcome.FAIL,
            "; ".join(problems),
            culprit,
            _field_owner(graph, culprit),
            "rebuild the graph from a valid state/decision pair",
        )
    return _check(
        "G4_CONTRADICTION_FREE_STATE",
        GraphCheckOutcome.PASS,
        "graph digest, endpoints, B projection, and claim state are consistent",
    )


def _novelty(graph: EvidenceGraph) -> GraphCheckResult:
    prior = next(
        (node.status for node in graph.nodes if node.node_type is NodeType.PRIOR_ART),
        None,
    )
    novelty = next(
        (node.status for node in graph.nodes if node.node_type is NodeType.NOVELTY),
        None,
    )
    known = {
        PriorArtStatus.KNOWN_CASE_RECOVERY.value,
        PriorArtStatus.DIRECT_PRIOR_ART.value,
    }
    if novelty == NoveltyStatus.GLOBAL_NOVELTY_CLAIM.value and prior in known:
        return _check(
            "G5_NOVELTY_SCOPE_BOUNDED",
            GraphCheckOutcome.FAIL,
            "known prior art cannot support a global novelty claim",
            "candidate_card.novelty_status",
            _field_owner(graph, "candidate_card.novelty_status"),
        )
    if novelty == NoveltyStatus.GLOBAL_NOVELTY_CLAIM.value and prior == PriorArtStatus.UNKNOWN.value:
        return _check(
            "G5_NOVELTY_SCOPE_BOUNDED",
            GraphCheckOutcome.UNKNOWN,
            "global novelty remains unsupported while prior art is unknown",
            "candidate_card.novelty_status",
            _field_owner(graph, "candidate_card.novelty_status"),
        )
    return _check(
        "G5_NOVELTY_SCOPE_BOUNDED",
        GraphCheckOutcome.PASS,
        "novelty wording stays within the represented prior-art boundary",
    )


def _generic_motif(
    graph: EvidenceGraph,
    claim: GraphNode | None,
    verdict: Verdict,
) -> GraphCheckResult:
    selected = claim.payload.get("selected_candidate") if claim else None
    structures = {node.label for node in graph.nodes if node.node_type is NodeType.STRUCTURE}
    generic = (
        selected == "amplitude_amplification"
        and verdict in {Verdict.POSITIVE, Verdict.CONDITIONAL}
        and not (structures - GENERIC_SEARCH_STRUCTURES)
    )
    if generic:
        return _check(
            "G6_GENERIC_WRAPPER_MOTIF",
            GraphCheckOutcome.INFO,
            "valid but generic black-box witness-search wrapper",
        )
    return _check(
        "G6_GENERIC_WRAPPER_MOTIF",
        GraphCheckOutcome.PASS,
        "no generic Grover wrapper motif detected",
    )


def _features(graph: EvidenceGraph, claim: GraphNode | None) -> dict[str, Any]:
    selected = claim.payload.get("selected_candidate") if claim else None
    scope = claim.payload.get("claim_scope") if claim else ClaimScope.NONE.value
    structures = {node.label for node in graph.nodes if node.node_type is NodeType.STRUCTURE}
    obligations = [node for node in graph.nodes if node.node_type is NodeType.OBLIGATION and node.status != "SATISFIED"]
    barriers = [node for node in graph.nodes if node.node_type is NodeType.BARRIER]
    b_checks = [node for node in graph.nodes if node.node_type is NodeType.B_CHECK]

    def blocking(node: GraphNode, status: str) -> bool:
        return node.status == status and scope in node.payload.get("blocked_scopes", [])

    return {
        "route": claim.payload.get("route") if claim else None,
        "claim_scope": scope,
        "selected": selected or "NO_CANDIDATE",
        "missing_obligations": ";".join(sorted(str(node.payload.get("key")) for node in obligations)),
        "blocking_barriers": ";".join(sorted(node.label for node in barriers if blocking(node, EvidenceState.SUPPORTED.value))),
        "unknown_blocking_barriers": ";".join(sorted(node.label for node in barriers if blocking(node, EvidenceState.UNKNOWN.value))),
        "generic_wrapper_motif": selected == "amplitude_amplification" and not (structures - GENERIC_SEARCH_STRUCTURES),
        "generic_estimation_motif": selected == "amplitude_estimation" and not (structures - GENERIC_STRUCTURES),
        "nontrivial_structure_count": len(structures - GENERIC_STRUCTURES),
        "weak_analogy_count": sum(node.node_type is NodeType.WEAK_ANALOGY for node in graph.nodes),
        "expert_questions_count": claim.payload.get("expert_questions_count", 0) if claim else 0,
        "limitations_count": claim.payload.get("limitations_count", 0) if claim else 0,
        "b_failures": ";".join(node.label for node in b_checks if node.status == CheckOutcome.FAIL.value),
        "b_unknowns": ";".join(node.label for node in b_checks if node.status == CheckOutcome.UNKNOWN.value),
    }


def _first_failed_path(checks: dict[str, GraphNode]) -> str | None:
    for rule in RULE_IDS:
        node = checks.get(rule)
        if node and node.status == CheckOutcome.FAIL.value:
            return node.field_path
    return None


def _field_owner(graph: EvidenceGraph, field_paths: str) -> ActionType | None:
    paths = set(field_paths.split(";"))
    return next(
        (
            node.owner_action
            for node in graph.nodes
            if node.owner_action
            and node.field_path
            and any(node.field_path.startswith(path) or path.startswith(node.field_path) for path in paths)
        ),
        None,
    )


def _node(graph: EvidenceGraph, node_id: str) -> GraphNode:
    return next(node for node in graph.nodes if node.node_id == node_id)


def _check(
    rule_id: str,
    outcome: GraphCheckOutcome,
    reason: str,
    culprit: str | None = None,
    owner: ActionType | None = None,
    repair: str | None = None,
) -> GraphCheckResult:
    return GraphCheckResult(
        rule_id=rule_id,
        outcome=outcome,
        reason=reason,
        culprit_field=culprit,
        owner_action=owner,
        repair_suggestion=repair,
    )

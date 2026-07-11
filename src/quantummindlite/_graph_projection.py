from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha1
from typing import Any

from ._graph_compile import graph_digest
from .graph import EdgeType, EvidenceGraph, GraphEdge, GraphNode, NodeType
from .messages import ActionType
from .models import (
    BarrierSpec,
    CandidateCard,
    CheckOutcome,
    ClaimScope,
    DecisionCard,
    EvidenceState,
    PrimitiveSpec,
    RunState,
)
from .validation import RULE_IDS


class _Builder:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}

    def node(
        self,
        node_type: NodeType,
        label: str,
        *,
        key: str | None = None,
        path: str | None = None,
        owner: ActionType | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        node_id = _id(node_type.value.lower(), key or label)
        node = GraphNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            field_path=path,
            owner_action=owner,
            status=status,
            payload=payload or {},
        )
        if node_id in self.nodes and self.nodes[node_id] != node:
            raise ValueError(f"graph node ID collision: {node_id}")
        self.nodes[node_id] = node
        return node_id

    def edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        *,
        status: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        edge_id = _id("edge", source, edge_type.value, target)
        self.edges[edge_id] = GraphEdge(
            edge_id=edge_id,
            source=source,
            target=target,
            edge_type=edge_type,
            status=status,
            rule_id=rule_id,
        )


def project_evidence_graph(
    state: RunState,
    decision: DecisionCard,
    registry: dict[str, PrimitiveSpec],
    *,
    run_id: str,
    barrier_catalog: dict[str, BarrierSpec] | None,
) -> EvidenceGraph:
    b = _Builder(run_id)
    candidate = state.candidate_card or CandidateCard()
    selected = candidate.selected_candidate
    spec = registry.get(selected or "")
    run_node = b.node(NodeType.RUN, run_id, key=run_id)
    claim = _claim_node(b, state, candidate, decision)
    b.edge(run_node, claim, EdgeType.CONTAINS, status=decision.authoritative_verdict.value)
    facts, structures = _context_nodes(b, state, run_node, claim)
    primitives = _match_nodes(b, state, candidate, registry, structures, claim)
    if selected:
        primitive = primitives.get(selected) or _primitive_node(b, selected, registry)
        primitives[selected] = primitive
        b.edge(primitive, claim, EdgeType.GROUNDS_CLAIM, status="KNOWN" if spec else "UNKNOWN")
    _weak_nodes(b, state, candidate, registry, primitives, claim)
    complexity = _complexity_nodes(b, state, candidate, claim) if selected else []
    _obligation_nodes(
        b,
        decision,
        candidate,
        spec,
        primitives,
        facts,
        structures,
        complexity,
        claim,
    )
    _barrier_nodes(b, state, candidate, spec, barrier_catalog or {}, claim)
    _novelty_nodes(b, state, candidate, claim)
    _decision_nodes(b, decision, claim)
    nodes = sorted(b.nodes.values(), key=lambda item: item.node_id)
    edges = sorted(b.edges.values(), key=lambda item: item.edge_id)
    return EvidenceGraph(
        graph_id=graph_digest(run_id, nodes, edges),
        run_id=run_id,
        nodes=nodes,
        edges=edges,
    )


def _claim_node(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    decision: DecisionCard,
) -> str:
    selected = candidate.selected_candidate
    has_claim = bool(
        candidate.scheme_steps
        or candidate.quantum_query_complexity
        or candidate.gate_complexity
        or candidate.total_complexity
        or candidate.claim_scope is not ClaimScope.NONE
    )
    return b.node(
        NodeType.CLAIM,
        f"{selected or 'NO_CANDIDATE'}@{candidate.claim_scope.value}",
        key="final",
        path="candidate_card",
        owner=_owner(state, "selected_candidate", selected),
        status=decision.authoritative_verdict.value,
        payload={
            "selected_candidate": selected,
            "claim_scope": candidate.claim_scope.value,
            "authoritative_verdict": decision.authoritative_verdict.value,
            "authoritative_scope": decision.maximum_supported_claim_scope.value,
            "route": decision.d_route.value,
            "has_final_claim": has_claim,
            "no_candidate_reason": candidate.no_candidate_reason,
            "expert_questions_count": len(candidate.expert_questions),
            "limitations_count": len(candidate.limitations),
        },
    )


def _context_nodes(
    b: _Builder,
    state: RunState,
    run_node: str,
    claim: str,
) -> tuple[dict[str, str], dict[str, str]]:
    facts: dict[str, str] = {}
    if state.problem_card:
        problem = state.problem_card
        values = {
            "input_model": problem.input_model,
            "access_model": problem.access_model,
            "output_contract": problem.output_contract,
            **{f"promise:{item}": item for item in problem.promises},
        }
        for key, value in values.items():
            path = "problem_card.promises" if key.startswith("promise:") else f"problem_card.{key}"
            facts[key] = b.node(
                NodeType.PROBLEM_FACT,
                f"{key}={value}",
                key=f"{key}:{value}",
                path=path,
                status="SUPPORTED",
                payload={"field": key, "value": value},
            )
            b.edge(run_node, facts[key], EdgeType.CONTAINS)
    structures: dict[str, str] = {}
    if state.analysis_card:
        analysis = state.analysis_card
        for value in analysis.canonical_structure_ids:
            structures[value] = b.node(
                NodeType.STRUCTURE,
                value,
                path="analysis_card.canonical_structure_ids",
                owner=_owner(state, "canonical_structure_ids", value),
                status="SUPPORTED",
            )
            b.edge(run_node, structures[value], EdgeType.CONTAINS)
        for index, value in enumerate(analysis.absent_or_weak_structures):
            node = b.node(
                NodeType.ABSENT_STRUCTURE,
                _short(value),
                key=f"{index}:{value}",
                path="analysis_card.absent_or_weak_structures",
                owner=_owner(state, "absent_or_weak_structures", value),
                status="ABSENT_OR_WEAK",
                payload={"text": value},
            )
            b.edge(node, claim, EdgeType.WEAKENS_CLAIM, status="ABSENT_OR_WEAK")
    return facts, structures


def _match_nodes(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    registry: dict[str, PrimitiveSpec],
    structures: dict[str, str],
    claim: str,
) -> dict[str, str]:
    primitives: dict[str, str] = {}
    for index, match in enumerate(candidate.primitive_matches):
        spec = registry.get(match.primitive_id)
        primitive = primitives.setdefault(
            match.primitive_id,
            _primitive_node(b, match.primitive_id, registry),
        )
        node = b.node(
            NodeType.PRIMITIVE_MATCH,
            f"{match.primitive_id}:{match.strength.value}",
            key=f"{index}:{match.primitive_id}:{match.strength.value}",
            path="candidate_card.primitive_matches",
            owner=_owner(state, "primitive_matches", match.primitive_id),
            status=match.strength.value,
            payload=match.model_dump(mode="json"),
        )
        b.edge(node, primitive, EdgeType.INSTANTIATES, status=match.strength.value)
        for required in spec.required_structure_ids if spec else []:
            if required in structures:
                b.edge(structures[required], node, EdgeType.SUPPORTS_MATCH, status="SUPPORTED")
        if match.primitive_id == candidate.selected_candidate:
            b.edge(node, claim, EdgeType.SUPPORTS_CLAIM, status=match.strength.value)
    return primitives


def _weak_nodes(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    registry: dict[str, PrimitiveSpec],
    primitives: dict[str, str],
    claim: str,
) -> None:
    for index, weak in enumerate(candidate.weak_analogy_opportunities):
        primitive = primitives.setdefault(
            weak.primitive_id,
            _primitive_node(b, weak.primitive_id, registry),
        )
        node = b.node(
            NodeType.WEAK_ANALOGY,
            weak.primitive_id,
            key=f"{index}:{weak.primitive_id}",
            path="candidate_card.weak_analogy_opportunities",
            owner=_owner(state, "weak_analogy_opportunities", weak.primitive_id),
            status="WEAK_ANALOGY",
            payload=weak.model_dump(mode="json"),
        )
        b.edge(node, primitive, EdgeType.CANNOT_SUPPORT)
        b.edge(node, claim, EdgeType.CANNOT_SUPPORT)


def _complexity_nodes(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    claim: str,
) -> list[str]:
    analysis = state.analysis_card
    quantum_field = {
        ClaimScope.QUERY: "quantum_query_complexity",
        ClaimScope.GATE: "gate_complexity",
        ClaimScope.END_TO_END: "total_complexity",
        ClaimScope.NONE: "quantum_query_complexity",
    }[candidate.claim_scope]
    values = (
        (NodeType.SCHEME, "scheme_steps", candidate.scheme_steps, "candidate_card.scheme_steps"),
        (
            NodeType.COMPLEXITY,
            "candidate_classical_baseline",
            candidate.classical_baseline,
            "candidate_card.classical_baseline",
        ),
        (
            NodeType.COMPLEXITY,
            "analysis_classical_baseline",
            analysis.classical_baseline if analysis else None,
            "analysis_card.classical_baseline",
        ),
        (
            NodeType.COMPLEXITY,
            quantum_field,
            getattr(candidate, quantum_field),
            f"candidate_card.{quantum_field}",
        ),
    )
    nodes: list[str] = []
    for node_type, label, value, path in values:
        known = bool(value) if isinstance(value, list) else _known_text(value)
        status = "SATISFIED" if known else "UNKNOWN"
        owner_key = label.removeprefix("candidate_").removeprefix("analysis_")
        node = b.node(
            node_type,
            label,
            path=path,
            owner=_owner(state, owner_key, value),
            status=status,
            payload={"value": value},
        )
        b.edge(node, claim, EdgeType.SUPPORTS_COMPLEXITY, status=status, rule_id=RULE_IDS[2])
        nodes.append(node)
    return nodes


def _obligation_nodes(
    b: _Builder,
    decision: DecisionCard,
    candidate: CandidateCard,
    spec: PrimitiveSpec | None,
    primitives: dict[str, str],
    facts: dict[str, str],
    structures: dict[str, str],
    complexity: list[str],
    claim: str,
) -> None:
    selected = candidate.selected_candidate
    if not selected:
        return
    checks = {item.rule_id: item for item in decision.b_check_results}
    requirements: list[tuple[str, Any, int, str, Sequence[str | None]]] = [
        ("selection", selected, 0, "candidate_card.selected_candidate", []),
        ("registry", selected, 1, "registry", [primitives.get(selected)]),
        (
            "structures",
            spec.required_structure_ids if spec else [],
            1,
            "analysis_card.canonical_structure_ids",
            [structures.get(item) for item in (spec.required_structure_ids if spec else [])],
        ),
        ("complexity_certificate", candidate.claim_scope.value, 2, "candidate_card.scheme_steps", complexity),
        (
            "access_model",
            spec.allowed_access_models if spec else [],
            3,
            "problem_card.access_model",
            [facts.get("access_model")],
        ),
        (
            "output_contract",
            spec.allowed_output_contracts if spec else [],
            4,
            "problem_card.output_contract",
            [facts.get("output_contract")],
        ),
        (
            "promises",
            spec.required_promises if spec else [],
            5,
            "problem_card.promises",
            [facts.get(f"promise:{item}") for item in (spec.required_promises if spec else [])],
        ),
        (
            "scope",
            spec.supported_claim_scope.value if spec else ClaimScope.NONE.value,
            7,
            "candidate_card.claim_scope",
            [],
        ),
    ]
    for key, required, rule_index, path, evidence in requirements:
        check = checks[RULE_IDS[rule_index]]
        status = _obligation_status(check.outcome)
        node = b.node(
            NodeType.OBLIGATION,
            key,
            path=path,
            status=status,
            payload={"key": key, "required": required, "rule_id": check.rule_id},
        )
        b.edge(node, claim, EdgeType.OBLIGATION_FOR, status=status, rule_id=check.rule_id)
        for source in (item for item in evidence if item):
            b.edge(source, node, EdgeType.SATISFIES, status=status, rule_id=check.rule_id)


def _barrier_nodes(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    spec: PrimitiveSpec | None,
    catalog: dict[str, BarrierSpec],
    claim: str,
) -> None:
    findings = {item.barrier_id: item for item in candidate.barriers}
    barrier_ids = [*findings]
    barrier_ids.extend(item for item in (spec.common_barriers if spec else []) if item not in findings)
    for barrier_id in barrier_ids:
        finding = findings.get(barrier_id)
        catalog_item = catalog.get(barrier_id)
        blocked = finding.blocked_scopes if finding else (catalog_item.blocked_scopes if catalog_item else [])
        status = finding.applicable.value if finding else EvidenceState.UNKNOWN.value
        node = b.node(
            NodeType.BARRIER,
            barrier_id,
            path="candidate_card.barriers" if finding else "registry.common_barriers",
            owner=_owner(state, "barriers", barrier_id) if finding else None,
            status=status,
            payload={
                "blocked_scopes": [scope.value for scope in blocked],
                "registry_default": finding is None,
            },
        )
        edge_type = EdgeType.BLOCKS_SCOPE if candidate.claim_scope in blocked else EdgeType.BOUNDS_SCOPE
        b.edge(node, claim, edge_type, status=status, rule_id=RULE_IDS[6])


def _novelty_nodes(
    b: _Builder,
    state: RunState,
    candidate: CandidateCard,
    claim: str,
) -> None:
    items = (
        (NodeType.PRIOR_ART, candidate.prior_art_status.value, "prior_art_status"),
        (NodeType.NOVELTY, candidate.novelty_status.value, "novelty_status"),
    )
    for node_type, value, key in items:
        path = f"candidate_card.{key}"
        node = b.node(
            node_type,
            value,
            path=path,
            owner=_owner(state, key, value),
            status=value,
        )
        b.edge(node, claim, EdgeType.BOUNDS_NOVELTY, status=value, rule_id=RULE_IDS[8])


def _decision_nodes(b: _Builder, decision: DecisionCard, claim: str) -> None:
    for check in decision.b_check_results:
        node = b.node(
            NodeType.B_CHECK,
            check.rule_id,
            path=check.evidence_path,
            status=check.outcome.value,
            payload=check.model_dump(mode="json"),
        )
        b.edge(node, claim, EdgeType.CHECKS_CLAIM, status=check.outcome.value, rule_id=check.rule_id)
    node = b.node(
        NodeType.DECISION,
        decision.authoritative_verdict.value,
        key="final",
        path="decision",
        status=decision.d_route.value,
        payload=decision.model_dump(mode="json"),
    )
    b.edge(claim, node, EdgeType.DECIDED_AS, status=decision.authoritative_verdict.value)


def _primitive_node(
    b: _Builder,
    primitive_id: str,
    registry: dict[str, PrimitiveSpec],
) -> str:
    spec = registry.get(primitive_id)
    return b.node(
        NodeType.REGISTRY_PRIMITIVE,
        primitive_id,
        path="registry",
        status=spec.speedup_class.value if spec else "UNKNOWN",
        payload={"known": spec is not None, **(spec.model_dump(mode="json") if spec else {})},
    )


def _owner(state: RunState, key: str, marker: Any = None) -> ActionType | None:
    for message in reversed(state.messages):
        payload = message.get("payload")
        if not isinstance(payload, dict) or key not in payload:
            continue
        if marker is not None and not _payload_matches(payload[key], marker):
            continue
        try:
            return ActionType(str(message.get("action")))
        except ValueError:
            continue
    return None


def _payload_matches(value: Any, marker: Any) -> bool:
    if value == marker:
        return True
    if not isinstance(value, list):
        return False
    if marker in value:
        return True
    return any(isinstance(item, dict) and marker in {item.get("primitive_id"), item.get("barrier_id")} for item in value)


def _obligation_status(outcome: CheckOutcome) -> str:
    return {
        CheckOutcome.PASS: "SATISFIED",
        CheckOutcome.FAIL: "CONTRADICTED",
        CheckOutcome.UNKNOWN: "UNKNOWN",
        CheckOutcome.NOT_APPLICABLE: "NOT_APPLICABLE",
    }[outcome]


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{sha1(':'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _known_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() != "UNKNOWN"


def _short(text: str, length: int = 96) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= length else compact[: length - 1] + "…"

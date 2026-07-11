from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from .messages import ActionType
from .models import ClaimScope, StrictModel, Verdict

GRAPH_VERSION = "QAEG-v0.2"
GENERIC_SEARCH_STRUCTURES = frozenset(
    {
        "black_box_witness_search",
        "boolean_predicate_search",
        "oracle_query_model",
        "unstructured_search",
        "witness_output",
    }
)
GENERIC_ESTIMATION_STRUCTURES = frozenset({"bounded_mean_estimation", "marked_set_cardinality_estimation"})
GENERIC_STRUCTURES = GENERIC_SEARCH_STRUCTURES | GENERIC_ESTIMATION_STRUCTURES


class NodeType(str, Enum):
    RUN = "Run"
    PROBLEM_FACT = "ProblemFact"
    STRUCTURE = "Structure"
    ABSENT_STRUCTURE = "AbsentStructure"
    REGISTRY_PRIMITIVE = "RegistryPrimitive"
    PRIMITIVE_MATCH = "PrimitiveMatch"
    WEAK_ANALOGY = "WeakAnalogy"
    OBLIGATION = "Obligation"
    BARRIER = "Barrier"
    SCHEME = "Scheme"
    COMPLEXITY = "ComplexityTerm"
    PRIOR_ART = "PriorArt"
    NOVELTY = "NoveltyStatus"
    CLAIM = "Claim"
    B_CHECK = "BCheck"
    DECISION = "Decision"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    SUPPORTS_MATCH = "SUPPORTS_MATCH"
    INSTANTIATES = "INSTANTIATES_PRIMITIVE"
    SUPPORTS_CLAIM = "SUPPORTS_CLAIM"
    GROUNDS_CLAIM = "GROUNDS_CLAIM"
    CANNOT_SUPPORT = "CANNOT_SUPPORT_CLAIM"
    WEAKENS_CLAIM = "WEAKENS_CLAIM"
    OBLIGATION_FOR = "OBLIGATION_FOR_CLAIM"
    SATISFIES = "SATISFIES_OBLIGATION"
    BLOCKS_SCOPE = "BLOCKS_CLAIM_SCOPE"
    BOUNDS_SCOPE = "BOUNDS_STRONGER_SCOPES"
    SUPPORTS_COMPLEXITY = "SUPPORTS_COMPLEXITY_CERTIFICATE"
    BOUNDS_NOVELTY = "BOUNDS_NOVELTY"
    CHECKS_CLAIM = "CHECKS_CLAIM"
    DECIDED_AS = "DECIDED_AS"


class GraphStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class GraphCheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INFO = "INFO"


class GraphNode(StrictModel):
    node_id: str
    node_type: NodeType
    label: str
    field_path: str | None = None
    owner_action: ActionType | None = None
    status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(StrictModel):
    edge_id: str
    source: str
    target: str
    edge_type: EdgeType
    status: str | None = None
    rule_id: str | None = None


class EvidenceGraph(StrictModel):
    graph_id: str
    run_id: str
    graph_version: str = GRAPH_VERSION
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphCheckResult(StrictModel):
    rule_id: str
    outcome: GraphCheckOutcome
    reason: str
    culprit_field: str | None = None
    owner_action: ActionType | None = None
    repair_suggestion: str | None = None


class GraphVerifierReport(StrictModel):
    graph_id: str
    run_id: str
    graph_status: GraphStatus
    claim_accepted: bool
    authoritative_verdict: Verdict
    authoritative_scope: ClaimScope
    minimal_support_subgraph: dict[str, list[str]]
    graph_checks: list[GraphCheckResult]
    features: dict[str, Any] = Field(default_factory=dict)


from ._graph_compile import (  # noqa: E402
    build_evidence_graph as build_evidence_graph,
)
from ._graph_compile import (  # noqa: E402
    graph_summary as graph_summary,
)
from ._graph_compile import (  # noqa: E402
    process_run_dir as process_run_dir,
)
from ._graph_verify import minimal_support as minimal_support  # noqa: E402
from ._graph_verify import verify_evidence_graph as verify_evidence_graph  # noqa: E402

__all__ = [
    "EdgeType",
    "EvidenceGraph",
    "GraphCheckOutcome",
    "GraphCheckResult",
    "GraphEdge",
    "GraphNode",
    "GraphStatus",
    "GraphVerifierReport",
    "NodeType",
    "build_evidence_graph",
    "graph_summary",
    "minimal_support",
    "process_run_dir",
    "verify_evidence_graph",
]

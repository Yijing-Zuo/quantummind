from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

EXTRACTION_VERSION = "algorithm-wiki-adapter-v1"

PUBLIC_FIELDS = (
    "statement",
    "input_model",
    "access_model",
    "output_contract",
    "promises",
    "size_parameters",
    "ambiguities",
)

INPUT_MODELS = (
    "algorithm_wiki_algorithm_record",
    "explicit_sequence_problem",
    "explicit_graph_problem",
    "explicit_string_problem",
    "explicit_matrix_problem",
    "explicit_number_theory_problem",
    "explicit_combinatorial_problem",
    "explicit_geometry_problem",
    "explicit_dynamic_programming_problem",
    "explicit_data_structure_problem",
    "explicit_optimization_problem",
    "explicit_numerical_problem",
    "explicit_image_processing_problem",
    "explicit_robotics_problem",
    "explicit_parallel_algorithm_problem",
    "finite_candidate_set_problem",
    "implicit_backtracking_tree_problem",
    "marked_markov_chain_search_problem",
    "marked_set_counting_problem",
    "query_model_subroutine_problem",
    "unknown_input_model",
)

ACCESS_MODELS = (
    "explicit_input_instance",
    "random_access_array",
    "random_access_string",
    "adjacency_list_query",
    "edge_list_input",
    "dense_matrix_access",
    "sparse_matrix_oracle",
    "explicit_numeric_parameters",
    "offline_batch_queries",
    "function_evaluation_oracle_classical",
    "explicit_geometric_objects",
    "coherent_boolean_oracle",
    "coherent_estimation_oracle",
    "coherent_value_oracle",
    "coherent_backtracking_tree_oracle",
    "coherent_markov_chain_walk_oracle",
    "local_graph_transition_oracle",
    "unknown_access_model",
)

OUTPUT_CONTRACTS = (
    "exact_value",
    "yes_no_decision",
    "one_witness",
    "multiple_witnesses",
    "count_or_number",
    "estimate",
    "sorted_order",
    "path_or_tree",
    "assignment_or_schedule",
    "approximation_solution",
    "additive_estimate",
    "argmin_item",
    "minimum_value_and_argmin",
    "one_solution_leaf",
    "one_marked_vertex",
    "additive_count_estimate",
    "relative_count_estimate",
    "state_or_expectation",
    "data_structure_output",
    "full_solution",
    "full_sequence_output",
    "full_classical_output",
    "unknown_output_contract",
)

READINESS_LABELS = (
    "READY_PUBLIC_BLIND",
    "READY_PUBLIC_NAMED_ONLY",
    "REVIEW_NEEDED",
    "INSUFFICIENT_INFORMATION",
    "DUPLICATE_VARIANT",
    "BAD_SOURCE",
)

DOMAINS = (
    "sorting",
    "graph",
    "matrix_linear_algebra",
    "numerical_analysis",
    "image_processing",
    "robotics",
    "string",
    "computational_geometry",
    "combinatorics",
    "data_structures",
    "optimization",
    "dynamic_programming",
    "randomized_sampling",
    "parallel_algorithms",
    "unknown",
)

LEAKAGE_TERMS = (
    "quantum",
    "qubit",
    "grover",
    "shor",
    "hhl",
    "qft",
    "amplitude amplification",
    "amplitude estimation",
    "quantum walk",
    "hamiltonian simulation",
    "expected_primitive",
    "expected_verdict",
    "gold",
    "evidence",
    "paperbench",
    "QM-PB",
    "hidden",
)


@dataclass(frozen=True)
class AlgorithmWikiRawRecord:
    algorithm_id: str
    name: str
    year: str
    time_complexity: str
    space_complexity: str
    computational_model: str
    randomized: str
    randomized_type: str
    approximate: str
    approximation_factor: str
    parameter_definitions: str
    span_depth: str
    work: str
    number_of_processors: str
    link: str
    row_index: int
    raw_digest: str
    source_dataset: str = "AlgorithmWiki"

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


@dataclass(frozen=True)
class AlgorithmWikiMetadata:
    algorithm_id: str
    canonical_name: str
    blind_name: str
    year: str
    domain: str
    family: str
    variation: str
    problem_name: str
    algorithm_family: str
    time_complexity: str
    space_complexity: str
    computational_model: str
    randomized: str
    approximate: str
    approximation_factor: str
    parameter_definitions: str
    span_depth: str
    work: str
    number_of_processors: str
    source_link: str
    source_link_type: str
    page_url: str
    page_fetch_status: str
    page_digest: str
    extracted_description: str
    inferred_problem_statement: str
    inferred_input_model: str
    inferred_access_model: str
    inferred_output_contract: str
    inferred_size_parameters: list[str]
    inferred_promises: list[str]
    inferred_ambiguities: list[str]
    quality_score: int
    quality_flags: list[str]
    readiness: str
    review_reasons: list[str]
    extraction_version: str = EXTRACTION_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


@dataclass(frozen=True)
class AlgorithmWikiPreCard:
    algorithm_id: str
    canonical_name: str
    public_summary: str
    classical_algorithm_summary: str
    likely_problem: str
    input_semantics: str
    output_semantics: str
    classical_baseline: str
    bottleneck_hint: str
    structural_hints: list[str]
    barrier_hints: list[str]
    source_metadata: dict[str, Any]
    readiness: str
    review_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


@dataclass(frozen=True)
class PublicProblemCard:
    statement: str
    input_model: str
    access_model: str
    output_contract: str
    promises: list[str] = field(default_factory=list)
    size_parameters: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> PublicProblemCard:
        validate_public_mapping(data)
        return cls(
            statement=str(data["statement"]),
            input_model=str(data["input_model"]),
            access_model=str(data["access_model"]),
            output_contract=str(data["output_contract"]),
            promises=[str(item) for item in data["promises"]],
            size_parameters=[str(item) for item in data["size_parameters"]],
            ambiguities=[str(item) for item in data["ambiguities"]],
        )

    def to_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in PUBLIC_FIELDS}


@dataclass(frozen=True)
class CombinedAuditCard:
    algorithm_id: str
    public_problem_card: PublicProblemCard | None
    metadata: AlgorithmWikiMetadata
    precard: AlgorithmWikiPreCard

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "warning": "Human audit card only. Do not pass this combined file to live agents.",
            "public_problem_card": self.public_problem_card.to_dict() if self.public_problem_card else None,
            "metadata": self.metadata.to_dict(),
            "precard": self.precard.to_dict(),
        }


def normalize_whitespace(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return "\n".join(line.strip() for line in normalized.strip().splitlines()).strip()


def strip_html(text: str) -> str:
    without_blocks = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    without_breaks = re.sub(r"(?i)<br\s*/?>", "\n", without_blocks)
    without_paragraphs = re.sub(r"(?i)</p\s*>", "\n", without_breaks)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_paragraphs)
    return html.unescape(without_tags)


def short_sha256(value: str | bytes | dict[str, Any] | list[Any], length: int = 16) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def safe_yaml_dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False, default_flow_style=False, width=1000)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(safe_yaml_dump(data), encoding="utf-8")


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                records.append(data)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def canonicalize_name(name: str) -> str:
    lowered = normalize_whitespace(name).lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"['`]", "", lowered)
    lowered = re.sub(r"\([^)]*\)", " ", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return normalize_whitespace(lowered)


def infer_source_link_type(link: str) -> str:
    lowered = link.strip().lower()
    if not lowered:
        return "unknown"
    if "doi.org" in lowered or lowered.startswith("doi:") or re.match(r"^10\.\d{4,9}/", lowered):
        return "doi"
    if "arxiv.org" in lowered or "arxiv:" in lowered:
        return "arxiv"
    if "dl.acm.org" in lowered or "acm.org" in lowered:
        return "acm"
    if "siam.org" in lowered:
        return "siam"
    if "sciencedirect.com" in lowered:
        return "sciencedirect"
    if "citeseerx" in lowered:
        return "citeseerx"
    if lowered.endswith(".pdf") or ".pdf?" in lowered or "/pdf/" in lowered:
        return "pdf"
    return "unknown"


def public_card_digest(card: PublicProblemCard) -> str:
    return short_sha256(card.to_dict())


def leakage_matches(text: str) -> list[str]:
    found: list[str] = []
    for term in LEAKAGE_TERMS:
        if re.search(_leakage_pattern(term), text, flags=re.IGNORECASE):
            found.append(term.lower())
    return found


def validate_public_mapping(data: dict[str, Any], canonical_name: str = "", blind: bool = False) -> None:
    keys = tuple(data.keys())
    if keys != PUBLIC_FIELDS:
        missing = sorted(set(PUBLIC_FIELDS) - set(keys))
        extra = sorted(set(keys) - set(PUBLIC_FIELDS))
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if extra:
            detail.append("extra: " + ", ".join(extra))
        if not detail:
            detail.append("field order differs from public schema")
        raise ValueError("public card must contain exactly the seven public fields (" + "; ".join(detail) + ")")
    if not isinstance(data["statement"], str) or not str(data["statement"]).strip():
        raise ValueError("statement must be a nonempty string")
    if data["input_model"] not in INPUT_MODELS:
        raise ValueError(f"unknown input_model: {data['input_model']!r}")
    if data["access_model"] not in ACCESS_MODELS:
        raise ValueError(f"unknown access_model: {data['access_model']!r}")
    if data["output_contract"] not in OUTPUT_CONTRACTS:
        raise ValueError(f"unknown output_contract: {data['output_contract']!r}")
    for field_name in ("promises", "size_parameters", "ambiguities"):
        value = data[field_name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field_name} must be a list of strings")
    yaml_text = safe_yaml_dump({field_name: data[field_name] for field_name in PUBLIC_FIELDS})
    leaks = leakage_matches(yaml_text)
    if leaks:
        raise ValueError("public card leakage terms found: " + ", ".join(leaks))
    if blind and blind_name_leak(canonical_name, yaml_text):
        raise ValueError("blind public card contains the canonical algorithm name")


def blind_name_leak(canonical_name: str, public_text: str) -> bool:
    clean_name = canonicalize_name(canonical_name)
    if len(clean_name) < 4:
        return False
    clean_public = canonicalize_name(public_text)
    if clean_name in clean_public:
        return True
    tokens = [token for token in clean_name.split() if len(token) >= 4 and token not in {"algorithm", "method"}]
    return len(tokens) >= 2 and all(re.search(rf"\b{re.escape(token)}\b", clean_public) for token in tokens)


def metadata_from_mapping(data: dict[str, Any]) -> AlgorithmWikiMetadata:
    return AlgorithmWikiMetadata(
        algorithm_id=str(data["algorithm_id"]),
        canonical_name=str(data.get("canonical_name", "")),
        blind_name=str(data.get("blind_name", "")),
        year=str(data.get("year", "")),
        domain=str(data.get("domain", "unknown")),
        family=str(data.get("family", "")),
        variation=str(data.get("variation", "")),
        problem_name=str(data.get("problem_name", "")),
        algorithm_family=str(data.get("algorithm_family", "")),
        time_complexity=str(data.get("time_complexity", "")),
        space_complexity=str(data.get("space_complexity", "")),
        computational_model=str(data.get("computational_model", "")),
        randomized=str(data.get("randomized", "")),
        approximate=str(data.get("approximate", "")),
        approximation_factor=str(data.get("approximation_factor", "")),
        parameter_definitions=str(data.get("parameter_definitions", "")),
        span_depth=str(data.get("span_depth", "")),
        work=str(data.get("work", "")),
        number_of_processors=str(data.get("number_of_processors", "")),
        source_link=str(data.get("source_link", "")),
        source_link_type=str(data.get("source_link_type", "unknown")),
        page_url=str(data.get("page_url", "")),
        page_fetch_status=str(data.get("page_fetch_status", "disabled")),
        page_digest=str(data.get("page_digest", "")),
        extracted_description=str(data.get("extracted_description", "")),
        inferred_problem_statement=str(data.get("inferred_problem_statement", "")),
        inferred_input_model=str(data.get("inferred_input_model", "unknown_input_model")),
        inferred_access_model=str(data.get("inferred_access_model", "unknown_access_model")),
        inferred_output_contract=str(data.get("inferred_output_contract", "unknown_output_contract")),
        inferred_size_parameters=[str(item) for item in data.get("inferred_size_parameters", [])],
        inferred_promises=[str(item) for item in data.get("inferred_promises", [])],
        inferred_ambiguities=[str(item) for item in data.get("inferred_ambiguities", [])],
        quality_score=int(data.get("quality_score", 0)),
        quality_flags=[str(item) for item in data.get("quality_flags", [])],
        readiness=str(data.get("readiness", "REVIEW_NEEDED")),
        review_reasons=[str(item) for item in data.get("review_reasons", [])],
        extraction_version=str(data.get("extraction_version", EXTRACTION_VERSION)),
    )


def stable_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _leakage_pattern(term: str) -> str:
    escaped = re.escape(term)
    if " " in term:
        return r"\b" + re.sub(r"\\\s+", r"\\s+", escaped) + r"\b"
    if re.fullmatch(r"[A-Za-z0-9_]+", term):
        return rf"\b{escaped}\b"
    return escaped

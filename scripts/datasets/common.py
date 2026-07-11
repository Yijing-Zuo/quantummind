from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

EXTRACTION_VERSION = "taco-adapter-v1"

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
    "taco_competitive_programming_problem",
    "explicit_sequence_problem",
    "explicit_graph_problem",
    "explicit_string_problem",
    "explicit_matrix_problem",
    "explicit_number_theory_problem",
    "explicit_combinatorial_problem",
    "explicit_geometry_problem",
    "explicit_dynamic_programming_problem",
    "explicit_data_structure_problem",
    "explicit_query_batch_problem",
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
    "full_solution",
    "full_sequence_output",
    "full_classical_output",
    "unknown_output_contract",
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
class TacoMetadata:
    algorithm_id: str
    source_dataset: str
    source_split: str
    source_index: int
    source: str
    url: str
    original_name: str
    difficulty: str
    raw_tags: list[str]
    tags: list[str]
    skill_types: list[str]
    expected_time_complexity: str
    expected_auxiliary_space: str
    time_limit: str
    memory_limit: str
    picture_num: int
    statement_digest: str
    public_card_digest: str
    extraction_version: str
    quality_score: int
    quality_flags: list[str]
    inferred_domain: str
    inferred_input_model: str
    inferred_access_model: str
    inferred_output_contract: str
    inferred_size_parameters: list[str]
    excluded_from_public: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CombinedAlgorithmCard:
    algorithm_id: str
    public_problem_card: PublicProblemCard
    metadata: TacoMetadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "warning": "Human audit card only. Do not pass this combined file to the live Agent.",
            "public_problem_card": self.public_problem_card.to_dict(),
            "metadata": self.metadata.to_dict(),
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


def remove_markdown_images(text: str) -> str:
    without_md = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", text)
    return re.sub(r"(?is)<img\b[^>]*>", " ", without_md)


def replace_markdown_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", text)


def clean_statement_text(text: str, original_name: str = "") -> str:
    cleaned = normalize_whitespace(strip_html(replace_markdown_links(remove_markdown_images(text))))
    if original_name:
        escaped = re.escape(normalize_whitespace(original_name))
        cleaned = re.sub(rf"(?is)^#*\s*{escaped}\s*\n+", "", cleaned).strip()
        cleaned = re.sub(rf"(?is)^#*\s*{escaped}\s*[:.-]\s*", "", cleaned).strip()
    return cleaned


def split_sections(text: str) -> dict[str, str]:
    headings = ("Input", "Output", "Constraints", "Example", "Examples", "Explanation", "Note")
    heading_pattern = "|".join(re.escape(item) for item in headings)
    matches = list(re.finditer(rf"(?im)^\s*(?:[-=*_]{{2,}}\s*)?(?:#+\s*)?({heading_pattern})\s*:?\s*(?:[-=*_]{{2,}})?\s*$", text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = match.group(1).lower()
        if key == "examples":
            key = "example"
        if key not in sections:
            sections[key] = normalize_whitespace(text[start:end])
    return sections


def has_input_output_evidence(text: str, input_output: Any = None, starter_code: str = "") -> bool:
    sections = split_sections(text)
    if "input" in sections and "output" in sections:
        return True
    if parse_input_output(input_output):
        return True
    return bool(starter_code and re.search(r"\b(def|class)\s+\w+", starter_code))


def parse_input_output(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    parsed: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value, parse_int=str)
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    useful = {}
    for key in ("inputs", "outputs", "fn_name", "examples"):
        if key in parsed:
            useful[key] = parsed[key]
    return useful


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


def public_card_digest(card: PublicProblemCard) -> str:
    return short_sha256(card.to_dict())


def leakage_matches(text: str) -> list[str]:
    found: list[str] = []
    for term in LEAKAGE_TERMS:
        pattern = _leakage_pattern(term)
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(term)
    return found


def assert_no_public_leakage(text: str) -> None:
    matches = leakage_matches(text)
    if matches:
        raise ValueError("public card leakage terms found: " + ", ".join(matches))


def validate_public_mapping(data: dict[str, Any]) -> None:
    keys = tuple(data.keys())
    if keys != PUBLIC_FIELDS:
        missing = sorted(set(PUBLIC_FIELDS) - set(keys))
        extra = sorted(set(keys) - set(PUBLIC_FIELDS))
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if extra:
            detail.append("extra: " + ", ".join(extra))
        if keys != PUBLIC_FIELDS and not detail:
            detail.append("field order differs from public schema")
        raise ValueError("public card must contain exactly the seven public fields (" + "; ".join(detail) + ")")
    if not isinstance(data["statement"], str) or not data["statement"].strip():
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
    assert_no_public_leakage(safe_yaml_dump({field_name: data[field_name] for field_name in PUBLIC_FIELDS}))


def metadata_from_mapping(data: dict[str, Any]) -> TacoMetadata:
    return TacoMetadata(
        algorithm_id=str(data["algorithm_id"]),
        source_dataset=str(data.get("source_dataset", "TACO")),
        source_split=str(data["source_split"]),
        source_index=int(data["source_index"]),
        source=str(data.get("source", "")),
        url=str(data.get("url", "")),
        original_name=str(data.get("original_name", "")),
        difficulty=str(data.get("difficulty", "")),
        raw_tags=[str(item) for item in data.get("raw_tags", [])],
        tags=[str(item) for item in data.get("tags", [])],
        skill_types=[str(item) for item in data.get("skill_types", [])],
        expected_time_complexity=str(data.get("expected_time_complexity", "")),
        expected_auxiliary_space=str(data.get("expected_auxiliary_space", "")),
        time_limit=str(data.get("time_limit", "")),
        memory_limit=str(data.get("memory_limit", "")),
        picture_num=int(data.get("picture_num", 0) or 0),
        statement_digest=str(data["statement_digest"]),
        public_card_digest=str(data["public_card_digest"]),
        extraction_version=str(data.get("extraction_version", EXTRACTION_VERSION)),
        quality_score=int(data.get("quality_score", 0)),
        quality_flags=[str(item) for item in data.get("quality_flags", [])],
        inferred_domain=str(data.get("inferred_domain", "")),
        inferred_input_model=str(data.get("inferred_input_model", "")),
        inferred_access_model=str(data.get("inferred_access_model", "")),
        inferred_output_contract=str(data.get("inferred_output_contract", "")),
        inferred_size_parameters=[str(item) for item in data.get("inferred_size_parameters", [])],
        excluded_from_public=[str(item) for item in data.get("excluded_from_public", [])],
    )


def _leakage_pattern(term: str) -> str:
    escaped = re.escape(term)
    if " " in term:
        return r"\b" + re.sub(r"\\\s+", r"\\s+", escaped) + r"\b"
    if re.fullmatch(r"[A-Za-z0-9_]+", term):
        return rf"\b{escaped}\b"
    return escaped

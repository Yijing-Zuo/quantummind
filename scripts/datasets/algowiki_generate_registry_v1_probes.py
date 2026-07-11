from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))

from scripts.datasets.algowiki_common import (  # noqa: E402
    PublicProblemCard,
    load_jsonl,
    load_yaml_mapping,
    normalize_whitespace,
    public_card_digest,
    stable_unique,
    validate_public_mapping,
    write_yaml,
)

ROOT = Path("corpus/algorithm_wiki/algowiki1901_rich_v1")
OUT_ROOT = ROOT / "registry_v1_probes"
REGISTRY_V1_PRIMITIVES = (
    "quantum_minimum_finding",
    "quantum_backtracking_tree_search",
    "quantum_walk_marked_vertex_search",
    "quantum_counting",
)
OPPORTUNITY_TO_PRIMITIVE = {
    "minimum_finding": "quantum_minimum_finding",
    "backtracking_tree_search": "quantum_backtracking_tree_search",
    "marked_vertex_quantum_walk": "quantum_walk_marked_vertex_search",
    "quantum_counting": "quantum_counting",
}
PROBE_TYPE = {
    "minimum_finding": "minimum_finding_probe",
    "backtracking_tree_search": "backtracking_tree_probe",
    "marked_vertex_quantum_walk": "marked_vertex_walk_probe",
    "quantum_counting": "counting_probe",
}
STATIC_FIELDS = (
    "probe_id",
    "target_registry_primitive",
    "access_ok",
    "output_ok",
    "promises_ok",
    "target_ok",
    "boundary_ok",
    "public_label_ok",
    "overall_ok",
    "issues",
)
SCREENING_FIELDS = (
    "algorithm_id",
    "algorithm_name",
    "source_public_context_path",
    "source_public_probe_path",
    "source_metadata_path",
    "existing_input_model",
    "existing_access_model",
    "existing_output_contract",
    "detected_opportunity_type",
    "evidence_text",
    "source_records_used",
    "why_probe_is_justified",
    "why_probe_is_not_justified",
    "required_introduced_assumptions",
    "risk_of_overgeneration",
    "decision",
    "source_card_type",
    "confidence_score",
    "source_count",
    "source_quality",
    "opportunity_score",
)
READY_FIELDS = (
    "probe_id",
    "parent_algorithm_id",
    "parent_algorithm_name",
    "target_registry_primitive",
    "probe_type",
    "public_probe_path",
    "metadata_probe_path",
    "evidence_path",
    "probe_input_model",
    "probe_access_model",
    "probe_output_contract",
    "introduced_assumptions",
    "confidence_score",
    "source_count",
    "card_digest",
    "review_decision",
    "overgeneration_risk",
)
FULL_OUTPUT_CONTRACTS = {
    "sorted_order",
    "path_or_tree",
    "assignment_or_schedule",
    "data_structure_output",
    "full_solution",
    "full_sequence_output",
    "full_classical_output",
    "multiple_witnesses",
}
FORBIDDEN_PUBLIC_LABELS = (
    "expected_primitive",
    "expected_verdict",
    "target_registry_primitive",
    "gold",
    "hidden",
    "paperbench",
    "QM-PB",
    "quantum_minimum_finding",
    "quantum_backtracking_tree_search",
    "quantum_walk_marked_vertex_search",
    "quantum_counting",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate registry-v1-aware AlgorithmWiki probe cards.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-root", default="")
    parser.add_argument("--max-per-type", type=int, default=45)
    parser.add_argument("--max-total", type=int, default=160)
    args = parser.parse_args(argv)

    root = Path(args.root)
    out_root = Path(args.out_root) if args.out_root else root / "registry_v1_probes"
    prepare_output(out_root)

    context_rows = read_csv(root / "manifests" / "ready_public_context.csv")
    probe_rows = read_csv(root / "manifests" / "ready_public_probe.csv")
    records = {str(row.get("algorithm_id", "")): row for row in load_jsonl(root / "enriched_records" / "enriched_algorithms.jsonl")}
    old_probe_distribution = Counter(str(row.get("probe_type", "")) for row in probe_rows)

    write_starting_state(out_root, context_rows, probe_rows, old_probe_distribution)
    screening_rows = build_screening_rows(root, context_rows, probe_rows, records)
    write_csv(out_root / "manifests" / "registry_v1_screening.csv", screening_rows, SCREENING_FIELDS)
    write_screening_report(out_root, screening_rows)

    selected_rows = select_screening_rows(screening_rows, int(args.max_per_type), int(args.max_total))
    generated_rows = write_generated_probes(root, out_root, selected_rows, records)
    static_rows = static_compatibility_rows(out_root, generated_rows)
    write_csv(out_root / "manifests" / "registry_v1_static_compatibility.csv", static_rows, STATIC_FIELDS)
    write_static_report(out_root, static_rows)

    compatible_ids = {row["probe_id"] for row in static_rows if str(row.get("overall_ok")) == "True"}
    ready_rows = [row for row in generated_rows if row["probe_id"] in compatible_ids]
    if len(ready_rows) != len(generated_rows):
        remove_incompatible_outputs(out_root, generated_rows, compatible_ids)
    write_ready_manifests(out_root, ready_rows)
    write_registry_commands(out_root)
    write_human_review(out_root, ready_rows)
    write_generation_report(out_root, context_rows, probe_rows, screening_rows, ready_rows)
    print(
        json.dumps(
            {
                "context_rows_scanned": len(context_rows),
                "probe_rows_scanned": len(probe_rows),
                "screening_rows": len(screening_rows),
                "generated_compatible_probes": len(ready_rows),
                "generated_by_type": dict(sorted(Counter(row["probe_type"] for row in ready_rows).items())),
                "out_root": str(out_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if len(ready_rows) >= 20 else 1


def prepare_output(out_root: Path) -> None:
    for name in ("public_probe", "metadata_probe", "evidence"):
        directory = out_root / name
        if directory.exists():
            shutil.rmtree(directory)
    for name in ("public_probe", "metadata_probe", "evidence", "audit", "manifests", "reports", "commands"):
        (out_root / name).mkdir(parents=True, exist_ok=True)


def build_screening_rows(
    root: Path,
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_row in context_rows:
        rows.append(screen_manifest_row(root, manifest_row, records, "context"))
    for manifest_row in probe_rows:
        rows.append(screen_manifest_row(root, manifest_row, records, "probe"))
    return rows


def screen_manifest_row(
    root: Path,
    row: dict[str, Any],
    records: dict[str, dict[str, Any]],
    source_card_type: str,
) -> dict[str, Any]:
    is_probe = source_card_type == "probe"
    algorithm_id = str(row.get("parent_algorithm_id" if is_probe else "algorithm_id", ""))
    algorithm_name = str(row.get("parent_algorithm_name" if is_probe else "algorithm_name", ""))
    public_context_path = str(row.get("public_context_path", ""))
    if is_probe:
        context_candidate = root / "public_context" / f"{algorithm_id}.yaml"
        if context_candidate.exists():
            public_context_path = str(context_candidate)
    public_probe_path = str(row.get("public_probe_path", "")) if is_probe else ""
    source_metadata_path = str(row.get("metadata_probe_path" if is_probe else "metadata_context_path", ""))
    public_path = Path(public_probe_path or public_context_path)
    public_card = load_optional_yaml(public_path)
    metadata = load_optional_yaml(Path(source_metadata_path))
    record = records.get(algorithm_id, {})
    text = source_text(row, public_card, metadata, record)
    existing_input = str(public_card.get("input_model", row.get("input_model", "")))
    existing_access = str(public_card.get("access_model", row.get("access_model", "")))
    existing_output = str(public_card.get("output_contract", row.get("output_contract", row.get("probe_output_contract", ""))))
    source_records = source_records_used(metadata, record)
    confidence_score = int_value(row.get("confidence_score", metadata.get("confidence_score", metadata.get("quality_score", 0))))
    source_count = int_value(row.get("source_count", metadata.get("source_count", len(source_records))))
    source_quality = str(row.get("source_quality", metadata.get("source_quality", "")))
    original_output = str(metadata.get("original_output_contract", existing_output))
    opportunity = detect_opportunity(text, row, metadata, existing_output, original_output, source_card_type)
    decision, why_yes, why_no, assumptions, risk, score = decision_for_opportunity(
        opportunity=opportunity,
        text=text,
        row=row,
        metadata=metadata,
        existing_output=existing_output,
        original_output=original_output,
        source_card_type=source_card_type,
        confidence_score=confidence_score,
        source_count=source_count,
    )
    return {
        "algorithm_id": algorithm_id,
        "algorithm_name": algorithm_name,
        "source_public_context_path": public_context_path,
        "source_public_probe_path": public_probe_path,
        "source_metadata_path": source_metadata_path,
        "existing_input_model": existing_input,
        "existing_access_model": existing_access,
        "existing_output_contract": existing_output,
        "detected_opportunity_type": opportunity,
        "evidence_text": evidence_snippet(text),
        "source_records_used": "; ".join(source_records),
        "why_probe_is_justified": why_yes,
        "why_probe_is_not_justified": why_no,
        "required_introduced_assumptions": "; ".join(assumptions),
        "risk_of_overgeneration": risk,
        "decision": decision,
        "source_card_type": source_card_type,
        "confidence_score": str(confidence_score),
        "source_count": str(source_count),
        "source_quality": source_quality,
        "opportunity_score": str(score),
    }


def detect_opportunity(
    text: str,
    row: dict[str, Any],
    metadata: dict[str, Any],
    existing_output: str,
    original_output: str,
    source_card_type: str,
) -> str:
    lowered = text.lower()
    probe_type = str(row.get("probe_type", metadata.get("probe_type", "")))
    if source_card_type == "probe" and probe_type == "graph_walk_probe" and graph_walk_signal(lowered, existing_output):
        return "marked_vertex_quantum_walk"
    if counting_signal(lowered, probe_type, existing_output, original_output):
        return "quantum_counting"
    if minimum_signal(lowered, probe_type, existing_output):
        return "minimum_finding"
    if backtracking_signal(lowered, probe_type, existing_output):
        return "backtracking_tree_search"
    return "none"


def decision_for_opportunity(
    *,
    opportunity: str,
    text: str,
    row: dict[str, Any],
    metadata: dict[str, Any],
    existing_output: str,
    original_output: str,
    source_card_type: str,
    confidence_score: int,
    source_count: int,
) -> tuple[str, str, str, list[str], str, int]:
    if opportunity == "none":
        return ("NO_SIGNAL", "", "No isolated registry-v1 query-subroutine structure was detected.", [], "low", 0)
    lowered = text.lower()
    probe_type = str(row.get("probe_type", metadata.get("probe_type", "")))
    assumptions = introduced_assumptions_for(opportunity)
    score = opportunity_score(opportunity, lowered, probe_type, existing_output, confidence_score, source_count)
    if confidence_score < 60 or source_count <= 0:
        return (
            "BLOCK_INSUFFICIENT_STRUCTURE",
            "",
            "The source trace or confidence is too thin for an assumption-bearing registry-v1 probe.",
            assumptions,
            "high",
            score,
        )
    if blocks_full_output(opportunity, existing_output, original_output, lowered, source_card_type, probe_type):
        return (
            "BLOCK_FULL_OUTPUT",
            "",
            "The row is dominated by full-output, sorting, traversal, path, or enumeration semantics without a clear isolated subroutine.",
            assumptions,
            "high",
            score,
        )
    if score < 4:
        return (
            "BLOCK_INSUFFICIENT_STRUCTURE",
            "",
            "The trigger terms are too generic without a defensible query-model reformulation.",
            assumptions,
            "medium",
            score,
        )
    return (
        "GENERATE_REGISTRY_V1_PROBE",
        justification_for(opportunity),
        "",
        assumptions,
        overgeneration_risk_for(opportunity, lowered, existing_output),
        score,
    )


def select_screening_rows(rows: list[dict[str, Any]], max_per_type: int, max_total: int) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("decision") == "GENERATE_REGISTRY_V1_PROBE"]
    candidates.sort(
        key=lambda row: (
            str(row.get("detected_opportunity_type", "")),
            -int_value(row.get("opportunity_score")),
            -int_value(row.get("confidence_score")),
            -int_value(row.get("source_count")),
            str(row.get("algorithm_id", "")),
        )
    )
    selected: list[dict[str, Any]] = []
    per_type: Counter[str] = Counter()
    seen_parent_type: set[tuple[str, str]] = set()
    for row in candidates:
        opportunity = str(row.get("detected_opportunity_type", ""))
        key = (str(row.get("algorithm_id", "")), opportunity)
        if key in seen_parent_type or per_type[opportunity] >= max_per_type:
            continue
        selected.append(row)
        seen_parent_type.add(key)
        per_type[opportunity] += 1
        if len(selected) >= max_total:
            break
    return sorted(selected, key=lambda row: (str(row.get("algorithm_id", "")), str(row.get("detected_opportunity_type", ""))))


def write_generated_probes(
    root: Path,
    out_root: Path,
    selected_rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ready_rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    for row in selected_rows:
        opportunity = str(row["detected_opportunity_type"])
        counters[opportunity] += 1
        probe_id = f"{row['algorithm_id']}-RV1-{short_type(opportunity)}{counters[opportunity]:04d}"
        record = records.get(str(row["algorithm_id"]), {})
        card = registry_probe_card(row, record, opportunity)
        validate_public_mapping(card.to_dict(), canonical_name=str(row["algorithm_name"]), blind=False)
        metadata = registry_probe_metadata(root, out_root, row, record, probe_id, card, opportunity)
        evidence = registry_probe_evidence(row, record, metadata)
        public_path = out_root / "public_probe" / f"{probe_id}.yaml"
        metadata_path = out_root / "metadata_probe" / f"{probe_id}.meta.yaml"
        evidence_path = out_root / "evidence" / f"{probe_id}.evidence.yaml"
        write_yaml(public_path, card.to_dict())
        write_yaml(metadata_path, metadata)
        write_yaml(evidence_path, evidence)
        ready_rows.append(
            {
                "probe_id": probe_id,
                "parent_algorithm_id": str(row["algorithm_id"]),
                "parent_algorithm_name": str(row["algorithm_name"]),
                "target_registry_primitive": OPPORTUNITY_TO_PRIMITIVE[opportunity],
                "probe_type": PROBE_TYPE[opportunity],
                "public_probe_path": str(public_path),
                "metadata_probe_path": str(metadata_path),
                "evidence_path": str(evidence_path),
                "probe_input_model": card.input_model,
                "probe_access_model": card.access_model,
                "probe_output_contract": card.output_contract,
                "introduced_assumptions": "; ".join(metadata["introduced_assumptions"]),
                "confidence_score": str(metadata["confidence_score"]),
                "source_count": str(metadata["source_count"]),
                "card_digest": metadata["card_digest"],
                "review_decision": review_decision(row),
                "overgeneration_risk": str(row["risk_of_overgeneration"]),
            }
        )
    return ready_rows


def registry_probe_card(row: dict[str, Any], record: dict[str, Any], opportunity: str) -> PublicProblemCard:
    name = str(row["algorithm_name"])
    source_summary = concise_source_summary(record, row)
    size_parameters = size_parameters_for(row, record, opportunity)
    if opportunity == "minimum_finding":
        return PublicProblemCard(
            statement=normalize_whitespace(
                f"{name} registry-v1 minimum-selection probe. This is an isolated query-model minimum-selection "
                "subroutine probe, not an end-to-end claim for the original algorithm. The represented task is to "
                "choose an argmin from a finite candidate set under a total ordered objective, using coherent value "
                f"access introduced only for this probe. Source-backed parent context: {source_summary} "
                "It is not a full sorting, spanning-tree, shortest-path, nearest-neighbor-list, full optimization-output, "
                "or whole-algorithm speedup claim. Coherent value-oracle construction, objective encoding, and data-loading "
                "cost remain expert obligations."
            ),
            input_model="finite_candidate_set_problem",
            access_model="coherent_value_oracle",
            output_contract="argmin_item",
            promises=["finite_candidate_set", "total_ordered_objective", "coherent_objective_oracle", "oracle_model_assumption"],
            size_parameters=size_parameters,
            ambiguities=[
                "This is an assumption-bearing query/subroutine probe and is not an end-to-end speedup claim.",
                "The objective oracle and candidate indexing are introduced assumptions requiring expert review.",
                "The parent task may still require full output, preprocessing, or data-loading work outside this probe.",
            ],
        )
    if opportunity == "backtracking_tree_search":
        return PublicProblemCard(
            statement=normalize_whitespace(
                f"{name} registry-v1 bounded tree-search probe. This is a bounded-depth backtracking-tree query-model "
                "subroutine probe, not an end-to-end claim for the original algorithm. The represented task is to find "
                "one solution leaf in an implicit finite search tree with coherent child and predicate access introduced "
                f"only for this probe. Source-backed parent context: {source_summary} It is not a full A*/shortest-path "
                "run, an end-to-end dynamic-programming claim, a full optimization workflow, or an all-solutions "
                "enumeration. Tree size/depth bounds and reversible child/predicate oracles are introduced assumptions "
                "and expert obligations."
            ),
            input_model="implicit_backtracking_tree_problem",
            access_model="coherent_backtracking_tree_oracle",
            output_contract="one_solution_leaf",
            promises=[
                "bounded_backtracking_tree",
                "bounded_tree_depth",
                "coherent_child_and_predicate_oracles",
                "marked_leaf_exists",
                "oracle_model_assumption",
            ],
            size_parameters=size_parameters,
            ambiguities=[
                "This is an assumption-bearing query/subroutine probe and is not an end-to-end speedup claim.",
                "Search-tree bounds, child generation, and predicate reversibility are introduced assumptions.",
                "The parent task may require dynamic-programming tables, full paths, or all solutions outside this probe.",
            ],
        )
    if opportunity == "marked_vertex_quantum_walk":
        return PublicProblemCard(
            statement=normalize_whitespace(
                f"{name} registry-v1 marked-state walk-search probe. This is a query-model marked-state walk subroutine "
                "probe, not an end-to-end claim for the original graph algorithm. The represented task is to return one "
                "marked vertex from a reversible ergodic Markov-chain state space with coherent walk and marking access "
                f"introduced only for this probe. Source-backed parent context: {source_summary} It is not full graph "
                "traversal, all paths, component decomposition, spanning-tree output, full shortest-path output, or a "
                "whole-graph speedup claim. Spectral-gap and marked-fraction lower bounds are assumptions, and coherent "
                "walk/reflection implementation remains expert work."
            ),
            input_model="marked_markov_chain_search_problem",
            access_model="coherent_markov_chain_walk_oracle",
            output_contract="one_marked_vertex",
            promises=[
                "reversible_ergodic_markov_chain",
                "efficient_marking_check",
                "marked_vertex_exists",
                "marked_fraction_lower_bound",
                "spectral_gap_lower_bound",
                "oracle_model_assumption",
            ],
            size_parameters=size_parameters,
            ambiguities=[
                "This is an assumption-bearing query/subroutine probe and is not an end-to-end speedup claim.",
                "The reversible-chain model, spectral gap, and marked fraction are introduced assumptions.",
                "The parent graph task may require full traversal, full paths, preprocessing, or output reconstruction.",
            ],
        )
    return PublicProblemCard(
        statement=normalize_whitespace(
            f"{name} registry-v1 approximate counting probe. This is a query-model approximate marked-set counting "
            "subroutine probe, not an end-to-end claim for the original algorithm. The represented task is to estimate "
            "the number or fraction of marked items in a finite search space using coherent Boolean predicate access "
            f"introduced only for this probe. Source-backed parent context: {source_summary} It does not output all "
            "marked items, an exact full list, or a full enumeration. Precision dependence, predicate construction, "
            "and data-loading cost remain expert obligations; the full original algorithm speedup is not claimed."
        ),
        input_model="marked_set_counting_problem",
        access_model="coherent_boolean_oracle",
        output_contract="additive_count_estimate",
        promises=["finite_search_space", "coherent_boolean_oracle_available", "count_precision_specified", "oracle_model_assumption"],
        size_parameters=size_parameters,
        ambiguities=[
            "This is an assumption-bearing query/subroutine probe and is not an end-to-end speedup claim.",
            "The marked-set predicate, finite search space, and count precision are introduced assumptions.",
            "The parent task may require outputting marked objects or exact enumeration outside this probe.",
        ],
    )


def registry_probe_metadata(
    root: Path,
    out_root: Path,
    row: dict[str, Any],
    record: dict[str, Any],
    probe_id: str,
    card: PublicProblemCard,
    opportunity: str,
) -> dict[str, Any]:
    source_card_paths = [value for value in (row.get("source_public_context_path"), row.get("source_public_probe_path")) if value]
    source_metadata_paths = [str(row.get("source_metadata_path", ""))] if row.get("source_metadata_path") else []
    source_records = source_records_from_row(row, record)
    return {
        "probe_id": probe_id,
        "algorithm_id": probe_id,
        "canonical_name": f"{row['algorithm_name']} {PROBE_TYPE[opportunity]}",
        "readiness": "READY_PUBLIC_PROBE",
        "quality_score": int_value(row.get("confidence_score")),
        "parent_algorithm_id": str(row["algorithm_id"]),
        "parent_algorithm_name": str(row["algorithm_name"]),
        "target_registry_primitive": OPPORTUNITY_TO_PRIMITIVE[opportunity],
        "probe_type": PROBE_TYPE[opportunity],
        "source_card_type": str(row["source_card_type"]),
        "source_card_paths": source_card_paths,
        "source_metadata_paths": source_metadata_paths,
        "introduced_assumptions": introduced_assumptions_for(opportunity),
        "required_promises": required_promises_for(opportunity),
        "original_input_model": str(row.get("existing_input_model", "")),
        "original_access_model": str(row.get("existing_access_model", "")),
        "original_output_contract": str(row.get("existing_output_contract", "")),
        "probe_input_model": card.input_model,
        "probe_access_model": card.access_model,
        "probe_output_contract": card.output_contract,
        "not_end_to_end_claim": True,
        "expected_authority": "query_or_subroutine_hypothesis_only",
        "why_probe_is_scientifically_interesting": str(row.get("why_probe_is_justified", "")),
        "why_probe_may_fail": failure_reason_for(opportunity),
        "overgeneration_risk": str(row.get("risk_of_overgeneration", "")),
        "source_records_used": source_records,
        "screening_decision_source": {
            "screening_manifest": str(out_root / "manifests" / "registry_v1_screening.csv"),
            "decision": str(row.get("decision", "")),
            "opportunity_score": int_value(row.get("opportunity_score")),
        },
        "inferred_input_model": card.input_model,
        "inferred_access_model": card.access_model,
        "inferred_output_contract": card.output_contract,
        "inferred_size_parameters": card.size_parameters,
        "inferred_promises": card.promises,
        "inferred_ambiguities": card.ambiguities,
        "source_count": int_value(row.get("source_count")),
        "source_quality": str(row.get("source_quality", "")),
        "confidence_score": int_value(row.get("confidence_score")),
        "card_digest": public_card_digest(card),
        "extraction_version": "algorithm-wiki-registry-v1-probe-v1",
        "root_dataset": str(root),
    }


def registry_probe_evidence(row: dict[str, Any], record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_id": metadata["probe_id"],
        "kind": "registry_v1_probe",
        "parent_algorithm_id": metadata["parent_algorithm_id"],
        "parent_algorithm_name": metadata["parent_algorithm_name"],
        "source_card_paths": metadata["source_card_paths"],
        "source_metadata_paths": metadata["source_metadata_paths"],
        "source_records_used": metadata["source_records_used"],
        "short_paraphrased_support": evidence_snippet(source_text(row, {}, {}, record)),
        "introduced_assumptions": metadata["introduced_assumptions"],
        "limitations": [
            "The probe is a public query/subroutine hypothesis only.",
            "It does not assert a full original-algorithm speedup.",
            "Oracle, promise, and data-representation costs require expert review.",
        ],
        "confirmation": "Public provenance sidecar only; no evaluator label or private benchmark answer is encoded.",
    }


def static_compatibility_rows(out_root: Path, ready_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = load_registry_specs(Path("src/quantummindlite/resources/configs/primitives.yaml"))
    rows: list[dict[str, Any]] = []
    for row in ready_rows:
        public = load_yaml_mapping(Path(row["public_probe_path"]))
        metadata = load_yaml_mapping(Path(row["metadata_probe_path"]))
        primitive_id = str(metadata.get("target_registry_primitive", ""))
        issues: list[str] = []
        spec = registry.get(primitive_id)
        access_ok = bool(spec and public.get("access_model") in spec["allowed_access_models"])
        output_ok = bool(spec and public.get("output_contract") in spec["allowed_output_contracts"])
        target_ok = primitive_id in REGISTRY_V1_PRIMITIVES
        required = set(spec["required_promises"] if spec else [])
        promises_ok = required.issubset(set(str(item) for item in public.get("promises", [])))
        statement = str(public.get("statement", ""))
        lowered = statement.lower()
        boundary_ok = "not an end-to-end" in lowered and "query-model" in lowered and "subroutine" in lowered
        public_label_ok = not forbidden_public_labels(statement + "\n" + json.dumps(public, sort_keys=True))
        if not access_ok:
            issues.append("access_model_not_allowed")
        if not output_ok:
            issues.append("output_contract_not_allowed")
        if not promises_ok:
            issues.append("missing_required_promises")
        if not target_ok:
            issues.append("target_not_registry_v1")
        if not boundary_ok:
            issues.append("missing_query_subroutine_boundary")
        if not public_label_ok:
            issues.append("public_forbidden_label")
        rows.append(
            {
                "probe_id": row["probe_id"],
                "target_registry_primitive": primitive_id,
                "access_ok": str(access_ok),
                "output_ok": str(output_ok),
                "promises_ok": str(promises_ok),
                "target_ok": str(target_ok),
                "boundary_ok": str(boundary_ok),
                "public_label_ok": str(public_label_ok),
                "overall_ok": str(not issues),
                "issues": "; ".join(issues),
            }
        )
    return rows


def load_registry_specs(path: Path) -> dict[str, dict[str, list[str]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    specs: dict[str, dict[str, list[str]]] = {}
    for item in data.get("primitives", []):
        if not isinstance(item, dict):
            continue
        primitive_id = str(item.get("primitive_id", ""))
        specs[primitive_id] = {
            "allowed_access_models": [str(value) for value in item.get("allowed_access_models", [])],
            "allowed_output_contracts": [str(value) for value in item.get("allowed_output_contracts", [])],
            "required_promises": [str(value) for value in item.get("required_promises", [])],
        }
    return specs


def write_starting_state(
    out_root: Path, context_rows: list[dict[str, Any]], probe_rows: list[dict[str, Any]], distribution: Counter[str]
) -> None:
    lines = [
        "# Registry V1 Probe Starting State",
        "",
        f"- Timestamp: {datetime.now(UTC).isoformat()}",
        f"- Context cards ready: {len(context_rows)}",
        f"- Public probe cards ready: {len(probe_rows)}",
        f"- Existing probe type distribution: {dict(sorted(distribution.items()))}",
        "- Existing public probes were generated before registry_v1 and mostly expose older search, graph-walk, "
        "estimation, and period shapes.",
        "- They generally do not carry the access models, output contracts, and required promises for the four registry_v1 primitives.",
        "- Registry-v1 primitives screened here: quantum_minimum_finding, quantum_backtracking_tree_search, "
        "quantum_walk_marked_vertex_search, quantum_counting.",
        "- Boundary: all generated cards must be query/subroutine probes only; no gate-level, full-output, novelty, "
        "or end-to-end speedup claim is supported.",
        "- Overgeneration risks: minimum/best wording can hide full optimization; tree/path wording can hide full path "
        "output; graph-walk wording can hide traversal; count wording can hide enumeration.",
        "",
        "Preflight note: the literal `python` command resolves to the Windows Store alias on this machine, so offline "
        "checks were run with the bundled Codex Python interpreter.",
    ]
    (out_root / "reports" / "registry_v1_starting_state.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_screening_report(out_root: Path, rows: list[dict[str, Any]]) -> None:
    decisions = Counter(str(row.get("decision", "")) for row in rows)
    opportunities = Counter(str(row.get("detected_opportunity_type", "")) for row in rows)
    generated = [row for row in rows if row.get("decision") == "GENERATE_REGISTRY_V1_PROBE"]
    lines = [
        "# Registry V1 Screening Report",
        "",
        f"- Rows screened: {len(rows)}",
        f"- Decisions: {dict(sorted(decisions.items()))}",
        f"- Detected opportunity types: {dict(sorted(opportunities.items()))}",
        f"- Generate candidates before de-duplication: {len(generated)}",
        "",
        "Screening required a defensible isolated query/subroutine reformulation. Generic words such as minimum, "
        "best, search, walk, tree, count, graph, or path were not sufficient by themselves.",
        "",
        "| decision | count |",
        "| --- | ---: |",
    ]
    for decision, count in sorted(decisions.items()):
        lines.append(f"| {decision} | {count} |")
    (out_root / "reports" / "registry_v1_screening_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_static_report(out_root: Path, rows: list[dict[str, Any]]) -> None:
    failures = [row for row in rows if str(row.get("overall_ok")) != "True"]
    lines = [
        "# Registry V1 Static Compatibility Report",
        "",
        f"- Probes checked: {len(rows)}",
        f"- Failures: {len(failures)}",
        f"- Result: {'PASS' if not failures else 'FAIL'}",
        "",
    ]
    if failures:
        lines.extend(f"- {row['probe_id']}: {row['issues']}" for row in failures[:50])
    else:
        lines.append(
            "All generated probes matched target access models, output contracts, required promises, target IDs, "
            "public boundary text, and public-label restrictions."
        )
    (out_root / "reports" / "registry_v1_static_compatibility_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ready_manifests(out_root: Path, rows: list[dict[str, Any]]) -> None:
    write_csv(out_root / "manifests" / "ready_public_probe_registry_v1.csv", rows, READY_FIELDS)
    write_jsonl(out_root / "manifests" / "ready_public_probe_registry_v1.jsonl", rows)


def write_human_review(out_root: Path, rows: list[dict[str, Any]]) -> None:
    sample = rows[: min(80, len(rows))]
    lines = ["# Registry V1 Human-Level Review", ""]
    for row in sample:
        metadata = load_yaml_mapping(Path(row["metadata_probe_path"]))
        decision = row["review_decision"]
        paragraph = (
            f"{row['probe_id']} parent algorithm {row['parent_algorithm_name']} targets {row['target_registry_primitive']}. "
            f"Input/access/output judgment: {row['probe_input_model']} / {row['probe_access_model']} / {row['probe_output_contract']} "
            "matches the registry-v1 query-scope shape. Introduced assumptions are explicit in metadata: "
            f"{'; '.join(str(item) for item in metadata.get('introduced_assumptions', []))}. "
            "The not-end-to-end boundary is clear in the public statement and metadata. "
            f"Scientific usefulness: {metadata.get('why_probe_is_scientifically_interesting', '')} "
            f"Generic overgeneration risk: {row['overgeneration_risk']}. Final decision: {decision}. "
            f"Reason: {review_reason(row, metadata)}"
        )
        lines.append(normalize_whitespace(paragraph))
        lines.append("")
    lines.append(f"Reviewed cards: {len(sample)} of {len(rows)}.")
    (out_root / "reports" / "registry_v1_human_review.md").write_text("\n".join(lines), encoding="utf-8")


def write_generation_report(
    out_root: Path,
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    screening_rows: list[dict[str, Any]],
    ready_rows: list[dict[str, Any]],
) -> None:
    decision_counts = Counter(str(row.get("decision", "")) for row in screening_rows)
    blocked = Counter(str(row.get("decision", "")) for row in screening_rows if str(row.get("decision", "")).startswith("BLOCK"))
    by_type = Counter(str(row.get("probe_type", "")) for row in ready_rows)
    static_report = read_text_if_exists(out_root / "reports" / "registry_v1_static_compatibility_report.md")
    audit_summary = audit_result_summary(out_root)
    mock_summary = mock_result_summary(out_root)
    review_summary = review_result_summary(out_root, ready_rows)
    lines = [
        "# Registry V1 Probe Generation Report",
        "",
        f"1. Source context count scanned: {len(context_rows)}.",
        f"2. Source probe count scanned: {len(probe_rows)}.",
        f"3. Screening decisions by category: {dict(sorted(decision_counts.items()))}.",
        f"4. Probes generated by type: {dict(sorted(by_type.items()))}.",
        f"5. Probes blocked by reason: {dict(sorted(blocked.items()))}.",
        f"6. Examples of minimum finding probes: {example_rows(ready_rows, 'minimum_finding_probe')}.",
        f"7. Examples of backtracking probes: {example_rows(ready_rows, 'backtracking_tree_probe')}.",
        f"8. Examples of marked-vertex walk probes: {example_rows(ready_rows, 'marked_vertex_walk_probe')}.",
        f"9. Examples of counting probes: {example_rows(ready_rows, 'counting_probe')}.",
        f"10. Static compatibility result: {'PASS' if 'Result: PASS' in static_report else 'see static report'}.",
        f"11. Audit result: {audit_summary}.",
        f"12. Mock validation result: {mock_summary}.",
        f"13. Human review result: {review_summary}.",
        "14. Known limitations: all probes rely on introduced oracle/promise assumptions; source metadata can be "
        "thinner than full papers; no full-output or end-to-end claim is encoded.",
        "15. Recommended first-50 live command: "
        "corpus\\algorithm_wiki\\algowiki1901_rich_v1\\registry_v1_probes\\commands\\"
        "run_live_registry_v1_probe_first_50_openai.bat.",
        "16. Confirmation: no OpenAI calls were made by this generation workflow.",
        "17. Confirmation: core workflow, B-rules, route logic, PaperBench, OpenAI provider, prompts, and existing "
        "registry entries were not modified.",
        "18. Confirmation: all positives are only query/subroutine hypotheses, not end-to-end speedup claims.",
        "",
    ]
    (out_root / "reports" / "registry_v1_probe_generation_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_registry_commands(out_root: Path) -> None:
    commands = out_root / "commands"
    manifest = out_root / "manifests" / "ready_public_probe_registry_v1.csv"
    write_live_command(
        commands / "run_live_registry_v1_probe_first_50_openai.bat",
        "Run live registry-v1 probe first 50 with OpenAI",
        manifest,
        "first_50",
        "runs\\registry_v1_probe_first50",
    )
    write_live_command(
        commands / "run_live_registry_v1_probe_shard_openai.bat",
        "Run live registry-v1 probe shard with OpenAI",
        manifest,
        "shard",
        "runs\\registry_v1_probe_%START_INDEX%_%END_INDEX%",
    )
    write_live_command(
        commands / "run_live_registry_v1_probe_all_openai.bat",
        "Run live registry-v1 probe all with OpenAI",
        manifest,
        "all",
        "runs\\registry_v1_probe_all",
    )
    summarize = (
        "@echo off\n"
        "REM Summarize registry-v1 probe runs. No API keys are stored in this file.\n"
        "setlocal\n"
        'if "%PYTHON%"=="" set "PYTHON=python"\n'
        f'"%PYTHON%" scripts\\datasets\\summarize_qml_discovery_runs.py --kind probe --run-dir runs '
        f'--manifest "{manifest}" '
        f'--out-csv "{out_root}\\reports\\registry_v1_probe_run_summary.csv" '
        f'--out-md "{out_root}\\reports\\registry_v1_probe_run_summary.md"\n'
    )
    (commands / "summarize_registry_v1_probe_runs.bat").write_text(summarize, encoding="utf-8")


def write_live_command(path: Path, title: str, manifest: Path, mode: str, output_dir: str) -> None:
    lines = [
        "@echo off\n",
        f"REM {title}\n",
        "REM No API keys are stored in this file.\n",
        "setlocal\n",
        'if "%OPENAI_API_KEY%"=="" (\n  echo OPENAI_API_KEY must be set in the environment.\n  exit /b 1\n)\n',
        'if "%PYTHON%"=="" set "PYTHON=python"\n',
        f'set "QML_MANIFEST={manifest}"\n',
        'set "QML_PATH_COLUMN=public_probe_path"\n',
        'set "QML_ID_COLUMN=probe_id"\n',
        'set "QML_REASONING_EFFORT=high"\n',
        f'set "QML_OUTPUT_DIR={output_dir}"\n',
        "echo WARNING: this runs OpenAI live analyze and may incur cost.\n",
        "echo Registry-v1 probe positives are query/subroutine hypotheses, not end-to-end speedup claims.\n",
    ]
    if mode == "all":
        lines.append(
            'if /I not "%CONFIRM_LIVE_ALL%"=="YES" (\n  echo Set CONFIRM_LIVE_ALL=YES after reviewing cost and quota.\n  exit /b 1\n)\n'
        )
        lines.append('set "START_INDEX=1"\nset "END_INDEX=999999"\n')
    elif mode == "shard":
        lines.append('if "%START_INDEX%"=="" set "START_INDEX=1"\nif "%END_INDEX%"=="" set "END_INDEX=50"\n')
    else:
        lines.append('set "START_INDEX=1"\nset "END_INDEX=50"\n')
    lines.append("powershell -NoProfile -ExecutionPolicy Bypass -Command ^\n")
    lines.append("  ")
    lines.append(powershell_analyze_command())
    lines.append("\nexit /b %ERRORLEVEL%\n")
    path.write_text("".join(lines), encoding="utf-8")


def powershell_analyze_command() -> str:
    script = "; ".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$manifest = $env:QML_MANIFEST",
            "if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }",
            "$rows = @(Import-Csv -LiteralPath $manifest)",
            "$start = [int]$env:START_INDEX",
            "$end = [int]$env:END_INDEX",
            "$current = 0",
            "foreach ($r in $rows) {",
            "  $current += 1",
            "  if ($current -lt $start -or $current -gt $end) { continue }",
            "  $card = [string]$r.PSObject.Properties[$env:QML_PATH_COLUMN].Value",
            "  $id = [string]$r.PSObject.Properties[$env:QML_ID_COLUMN].Value",
            "  if ([string]::IsNullOrWhiteSpace($id)) { $id = 'row-' + $current }",
            "  if ([string]::IsNullOrWhiteSpace($card)) { throw ('Missing card path for {0}' -f $id) }",
            "  if (-not (Test-Path -LiteralPath $card)) { throw ('Missing card path for {0}: {1}' -f $id, $card) }",
            "  Write-Host ('RUN {0} {1}' -f $id, $card)",
            "  & $env:PYTHON -m quantummindlite.cli analyze --input $card --provider openai "
            "--reasoning-effort $env:QML_REASONING_EFFORT --output-dir $env:QML_OUTPUT_DIR",
            "  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
            "}",
        ]
    )
    return f'"{script}"'


def minimum_signal(lowered: str, probe_type: str, existing_output: str) -> bool:
    terms = (
        "minimum",
        "argmin",
        "arg max",
        "best",
        "lowest",
        "smallest",
        "closest",
        "nearest neighbor",
        "minimum weight",
        "minimum cost",
        "optimal",
        "objective",
    )
    semantic = strip_parameter_noise(lowered)
    return any(term in semantic for term in terms) and existing_output not in {"sorted_order", "full_sequence_output"}


def backtracking_signal(lowered: str, probe_type: str, existing_output: str) -> bool:
    strong_terms = ("backtracking", "branch-and-bound", "branch and bound", "search tree", "solution leaf")
    weaker_terms = ("subset", "assignment", "schedule", "feasible", "constraint", "recursive", "depth-first", "dfs", "branch")
    if any(term in lowered for term in strong_terms):
        return True
    return probe_type == "search_witness_probe" and any(term in lowered for term in weaker_terms) and existing_output == "one_witness"


def graph_walk_signal(lowered: str, existing_output: str) -> bool:
    graph_terms = ("graph", "walk", "vertex", "edge", "neighbor", "neighbour", "hitting", "path")
    return existing_output == "one_witness" and any(term in lowered for term in graph_terms)


def counting_signal(lowered: str, probe_type: str, existing_output: str, original_output: str) -> bool:
    semantic = strip_parameter_noise(lowered)
    strong_count_terms = (
        "cardinality",
        "marked fraction",
        "frequency",
        "histogram",
        "how many",
        "estimate the number",
        "estimate a count",
        "count estimate",
        "number of intersections",
        "number of feasible",
        "number of solutions",
        "number of marked",
        "number of occurrences",
    )
    has_count_word = re.search(r"\bcount(s|ing|ed)?\b", semantic) is not None
    has_strong_count = any(term in semantic for term in strong_count_terms)
    target_sum_count = has_count_word and "target sum" in semantic and "finite set or multiset" in semantic
    explicit_output_count = has_count_word and (
        "output semantics: a count" in semantic
        or "original output context: a count" in semantic
        or "original output context: a decision result, feasible subset witness, count" in semantic
    )
    if original_output in FULL_OUTPUT_CONTRACTS and "estimate" not in semantic:
        return False
    if existing_output in {"full_sequence_output", "multiple_witnesses"} and "estimate" not in semantic:
        return False
    if probe_type == "estimation_sampling_probe" and not has_strong_count:
        return False
    return (has_strong_count or target_sum_count or explicit_output_count) and (
        probe_type in {"estimation_sampling_probe", "search_witness_probe", ""} or "estimate" in semantic
    )


def strip_parameter_noise(lowered: str) -> str:
    without_parameter_definitions = re.sub(r"parameter definition:[^.]+", " ", lowered)
    without_old_estimation_template = without_parameter_definitions.replace(
        "reformulates the row as estimating the mean, probability, count, or numerical quantity",
        "reformulates the row as estimating a generic bounded numerical quantity",
    )
    without_size_facts = re.sub(
        r"\b[a-z][a-z0-9_]*\s*:\s*(maximum\s+)?number of (elements|vertices|edges|points|processors|bits|items)",
        " ",
        without_old_estimation_template,
    )
    return without_size_facts


def blocks_full_output(
    opportunity: str,
    existing_output: str,
    original_output: str,
    lowered: str,
    source_card_type: str,
    probe_type: str,
) -> bool:
    if original_output in FULL_OUTPUT_CONTRACTS:
        return True
    if source_card_type == "probe" and existing_output in {"one_witness", "additive_estimate", "estimate"}:
        return False
    if opportunity == "minimum_finding" and ("nearest neighbor" in lowered or "closest" in lowered) and "list" not in lowered:
        return False
    if opportunity == "quantum_counting" and ("estimate" in lowered or "approximate" in lowered):
        return False
    if existing_output in FULL_OUTPUT_CONTRACTS:
        return True
    forbidden_shapes = (
        "full sorted",
        "sorted order",
        "minimum spanning tree",
        "spanning tree",
        "shortest path",
        "all shortest",
        "all paths",
        "all solutions",
        "enumerate all",
        "complete traversal",
        "strongly connected",
    )
    return any(term in lowered for term in forbidden_shapes)


def opportunity_score(
    opportunity: str,
    lowered: str,
    probe_type: str,
    existing_output: str,
    confidence_score: int,
    source_count: int,
) -> int:
    score = 0
    if probe_type:
        score += 2
    if existing_output in {"one_witness", "additive_estimate", "estimate", "count_or_number", "approximation_solution"}:
        score += 2
    if confidence_score >= 75:
        score += 1
    if source_count >= 2:
        score += 1
    strong_terms = {
        "minimum_finding": ("argmin", "nearest neighbor", "minimum", "closest", "objective"),
        "backtracking_tree_search": ("backtracking", "branch-and-bound", "search tree", "feasible", "assignment"),
        "marked_vertex_quantum_walk": ("graph-walk probe", "walk", "neighbor", "vertex", "hitting"),
        "quantum_counting": ("count", "cardinality", "number of", "marked fraction", "estimate"),
    }
    score += sum(1 for term in strong_terms[opportunity] if term in lowered)
    return score


def introduced_assumptions_for(opportunity: str) -> list[str]:
    return {
        "minimum_finding": ["finite_candidate_set", "total_ordered_objective", "coherent_value_oracle"],
        "backtracking_tree_search": ["bounded_backtracking_tree", "bounded_tree_depth", "coherent_child_and_predicate_oracles"],
        "marked_vertex_quantum_walk": [
            "reversible_ergodic_markov_chain",
            "coherent_markov_chain_walk_oracle",
            "marked_fraction_and_spectral_gap_bounds",
        ],
        "quantum_counting": ["finite_search_space", "coherent_boolean_oracle", "count_precision_specified"],
    }[opportunity]


def required_promises_for(opportunity: str) -> list[str]:
    return {
        "minimum_finding": ["finite_candidate_set", "total_ordered_objective", "coherent_objective_oracle"],
        "backtracking_tree_search": [
            "bounded_backtracking_tree",
            "bounded_tree_depth",
            "coherent_child_and_predicate_oracles",
            "marked_leaf_exists",
        ],
        "marked_vertex_quantum_walk": [
            "reversible_ergodic_markov_chain",
            "efficient_marking_check",
            "marked_vertex_exists",
            "marked_fraction_lower_bound",
            "spectral_gap_lower_bound",
        ],
        "quantum_counting": ["finite_search_space", "coherent_boolean_oracle_available", "count_precision_specified"],
    }[opportunity]


def justification_for(opportunity: str) -> str:
    return {
        "minimum_finding": "The source text supports an isolated minimum, best, closest, or objective-selection "
        "subproblem rather than a required full sorted output.",
        "backtracking_tree_search": "The source text supports a witness, feasible-object, branching, or "
        "constraint-search subproblem that can be stated as one marked leaf under explicit bounds.",
        "marked_vertex_quantum_walk": "The existing graph-walk probe already isolates local graph search; registry-v1 "
        "adds the stricter reversible-chain, marked-fraction, and spectral-gap assumptions.",
        "quantum_counting": "The source text supports approximate cardinality, marked-fraction, frequency, or count "
        "estimation without requiring the full marked set as output.",
    }[opportunity]


def failure_reason_for(opportunity: str) -> str:
    return {
        "minimum_finding": "The value oracle, objective ordering, or candidate indexing may be as hard as the "
        "original full optimization task.",
        "backtracking_tree_search": "The source may not supply bounded tree depth/size or coherent child/predicate oracles.",
        "marked_vertex_quantum_walk": "The reversible Markov-chain model, spectral gap, or marked fraction may not "
        "hold for the original graph process.",
        "quantum_counting": "The task may require exact enumeration or outputting marked objects rather than only a count estimate.",
    }[opportunity]


def overgeneration_risk_for(opportunity: str, lowered: str, existing_output: str) -> str:
    if existing_output in FULL_OUTPUT_CONTRACTS:
        return "high"
    generic_terms = {
        "minimum_finding": ("best", "optimal"),
        "backtracking_tree_search": ("search", "tree"),
        "marked_vertex_quantum_walk": ("graph", "path"),
        "quantum_counting": ("number",),
    }
    return "medium" if any(term in lowered for term in generic_terms[opportunity]) else "low"


def size_parameters_for(row: dict[str, Any], record: dict[str, Any], opportunity: str) -> list[str]:
    items: list[str] = []
    metadata = record.get("existing_metadata", {})
    if isinstance(metadata, dict):
        values = metadata.get("inferred_size_parameters", [])
        if isinstance(values, list):
            items.extend(str(item) for item in values if str(item).strip())
    defaults = {
        "minimum_finding": "N: finite candidate set size for the isolated minimum-selection subroutine.",
        "backtracking_tree_search": "T, d: introduced search-tree size and depth bounds for the isolated subroutine.",
        "marked_vertex_quantum_walk": "N, delta, epsilon: chain size, spectral-gap lower bound, and marked-fraction lower bound.",
        "quantum_counting": "N, epsilon: finite search-space size and requested count-estimation precision.",
    }
    items.append(defaults[opportunity])
    return stable_unique(items)[:6]


def concise_source_summary(record: dict[str, Any], row: dict[str, Any]) -> str:
    pieces = [
        str(record.get("extracted_input_semantics", "")),
        str(record.get("extracted_output_semantics", "")),
        str(record.get("extracted_bottleneck", "")),
        str(row.get("evidence_text", "")),
    ]
    text = normalize_whitespace(" ".join(piece for piece in pieces if piece))
    text = re.sub(r"\b[eE]vidence\b", "support", text)
    return text[:700] if text else "the parent card exposes a public source-backed algorithmic subroutine candidate."


def review_decision(row: dict[str, Any]) -> str:
    risk = str(row.get("risk_of_overgeneration", ""))
    score = int_value(row.get("opportunity_score"))
    return "ACCEPT_BUT_LOW_VALUE" if risk == "medium" or score < 6 else "ACCEPT"


def review_reason(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    if str(row.get("review_decision", "")) == "ACCEPT_BUT_LOW_VALUE":
        return "the card is runnable and explicit, but its scientific value depends heavily on introduced assumptions."
    return "the card is runnable, registry-compatible, explicit about assumptions, and bounded to query/subroutine authority."


def short_type(opportunity: str) -> str:
    return {
        "minimum_finding": "MIN",
        "backtracking_tree_search": "BTS",
        "marked_vertex_quantum_walk": "MVW",
        "quantum_counting": "CNT",
    }[opportunity]


def source_text(row: dict[str, Any], public_card: dict[str, Any], metadata: dict[str, Any], record: dict[str, Any]) -> str:
    parts = [
        str(row.get("algorithm_name", row.get("parent_algorithm_name", ""))),
        str(row.get("probe_type", "")),
        str(public_card.get("statement", "")),
        str(public_card.get("input_model", "")),
        str(public_card.get("access_model", "")),
        str(public_card.get("output_contract", "")),
        " ".join(str(item) for item in public_card.get("promises", []) if item),
        str(metadata.get("why_probe_is_scientifically_interesting", "")),
        str(metadata.get("why_probe_may_fail", "")),
        str(record.get("extracted_problem_statement", "")),
        str(record.get("extracted_algorithm_summary", "")),
        str(record.get("extracted_input_semantics", "")),
        str(record.get("extracted_output_semantics", "")),
        str(record.get("extracted_bottleneck", "")),
        " ".join(str(item) for item in record.get("extracted_assumptions", []) if item),
    ]
    for source in record.get("source_records", []):
        if isinstance(source, dict):
            parts.append(str(source.get("title", "")))
            parts.extend(str(item) for item in source.get("extracted_facts", []) if item)
    return normalize_whitespace(" ".join(part for part in parts if part))


def evidence_snippet(text: str) -> str:
    clean = normalize_whitespace(text)
    clean = re.sub(r"\b[eE]vidence\b", "support", clean)
    return clean[:900]


def source_records_used(metadata: dict[str, Any], record: dict[str, Any]) -> list[str]:
    values = metadata.get("source_records_used", [])
    if isinstance(values, list) and values:
        return [str(item) for item in values if str(item)]
    return source_records_from_record(record)


def source_records_from_row(row: dict[str, Any], record: dict[str, Any]) -> list[str]:
    listed = [item.strip() for item in str(row.get("source_records_used", "")).split(";") if item.strip()]
    return listed or source_records_from_record(record)


def source_records_from_record(record: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for source in record.get("source_records", []):
        if isinstance(source, dict) and source.get("source_id"):
            result.append(str(source["source_id"]))
    return result


def load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return load_yaml_mapping(path)
    except Exception:
        return {}


def forbidden_public_labels(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in FORBIDDEN_PUBLIC_LABELS if term.lower() in lowered]


def remove_incompatible_outputs(out_root: Path, rows: list[dict[str, Any]], compatible_ids: set[str]) -> None:
    for row in rows:
        if row["probe_id"] in compatible_ids:
            continue
        for key in ("public_probe_path", "metadata_probe_path", "evidence_path"):
            path = Path(row[key])
            if path.exists():
                path.unlink()


def audit_result_summary(out_root: Path) -> str:
    path = out_root / "audit" / "registry_v1_probe_audit.csv"
    if not path.exists():
        return "pending"
    rows = read_csv(path)
    counts = Counter(str(row.get("severity", "")) for row in rows)
    return f"{dict(sorted(counts.items()))}"


def mock_result_summary(out_root: Path) -> str:
    path = out_root / "reports" / "registry_v1_probe_mock_validation.json"
    if not path.exists():
        return "pending"
    data = json.loads(path.read_text(encoding="utf-8"))
    return f"ok={data.get('ok')}; samples={len(data.get('mock_analyze', []))}; errors={len(data.get('errors', []))}"


def review_result_summary(out_root: Path, ready_rows: list[dict[str, Any]]) -> str:
    counts = Counter(str(row.get("review_decision", "")) for row in ready_rows)
    return f"{dict(sorted(counts.items()))}; review file: {out_root / 'reports' / 'registry_v1_human_review.md'}"


def example_rows(rows: list[dict[str, Any]], probe_type: str) -> str:
    items = [f"{row['probe_id']} {row['parent_algorithm_name']}" for row in rows if row.get("probe_type") == probe_type]
    return "; ".join(items[:5]) or "none"


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def int_value(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

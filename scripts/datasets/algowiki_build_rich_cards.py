from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    PublicProblemCard,
    leakage_matches,
    load_jsonl,
    normalize_whitespace,
    public_card_digest,
    stable_unique,
    validate_public_mapping,
    write_yaml,
)

GENERIC_PHRASES = (
    "targeted by the record",
    "compute the graph object or decomposition targeted by the classical algorithm record",
    "compute the output specified by the record",
    "unknown classical task",
    "algorithmic output",
)

CONTEXT_READY = "READY_PUBLIC_CONTEXT"
PROBE_READY = "READY_PUBLIC_PROBE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build rich AlgorithmWiki context or probe ProblemCards.")
    parser.add_argument("--enriched-jsonl", required=True)
    parser.add_argument("--out-public-context-dir")
    parser.add_argument("--out-metadata-context-dir")
    parser.add_argument("--out-public-probe-dir")
    parser.add_argument("--out-metadata-probe-dir")
    parser.add_argument("--out-evidence-dir", required=True)
    parser.add_argument("--out-review-needed-dir")
    parser.add_argument("--out-manifest", required=True)
    parser.add_argument("--mode", choices=["context", "probe"], required=True)
    parser.add_argument("--seed", type=int, default=20260627)
    args = parser.parse_args(argv)

    records = load_jsonl(Path(args.enriched_jsonl))
    evidence_dir = Path(args.out_evidence_dir)
    if args.mode == "context":
        if not args.out_public_context_dir or not args.out_metadata_context_dir or not args.out_review_needed_dir:
            parser.error("context mode requires --out-public-context-dir, --out-metadata-context-dir, and --out-review-needed-dir")
        result = build_context(
            records,
            Path(args.out_public_context_dir),
            Path(args.out_metadata_context_dir),
            evidence_dir,
            Path(args.out_review_needed_dir),
        )
    else:
        if not args.out_public_probe_dir or not args.out_metadata_probe_dir:
            parser.error("probe mode requires --out-public-probe-dir and --out-metadata-probe-dir")
        result = build_probe(records, Path(args.out_public_probe_dir), Path(args.out_metadata_probe_dir), evidence_dir)

    result["timestamp"] = datetime.now(UTC).isoformat()
    result["mode"] = args.mode
    result["seed"] = int(args.seed)
    write_json(Path(args.out_manifest), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def build_context(
    records: list[dict[str, Any]],
    public_dir: Path,
    metadata_dir: Path,
    evidence_dir: Path,
    review_dir: Path,
) -> dict[str, Any]:
    clear_patterns(public_dir, ("AW-*.yaml",))
    clear_patterns(metadata_dir, ("AW-*.meta.yaml",))
    clear_patterns(review_dir, ("AW-*.yaml",))
    ready_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for record in records:
        card, reasons = make_context_card(record)
        algorithm_id = str(record.get("algorithm_id", ""))
        if card is None:
            review = review_needed_record(record, reasons)
            write_yaml(review_dir / f"{algorithm_id}.yaml", review)
            review_rows.append(review)
            continue
        meta = context_metadata(record, card)
        evidence = evidence_record(record, "context", algorithm_id)
        write_yaml(public_dir / f"{algorithm_id}.yaml", card.to_dict())
        write_yaml(metadata_dir / f"{algorithm_id}.meta.yaml", meta)
        write_yaml(evidence_dir / f"{algorithm_id}.context.evidence.yaml", evidence)
        ready_rows.append(context_manifest_row(record, card, public_dir, metadata_dir, evidence_dir))
    write_context_manifests(public_dir.parent / "manifests", ready_rows, review_rows)
    return {
        "input_records": len(records),
        "ready_context_count": len(ready_rows),
        "review_needed_after_web_count": len(review_rows),
        "domain_counts": dict(sorted(Counter(str(row.get("domain", "")) for row in ready_rows).items())),
        "output_contract_counts": dict(sorted(Counter(str(row.get("output_contract", "")) for row in ready_rows).items())),
        "review_reason_counts": review_reason_counts(review_rows),
    }


def build_probe(
    records: list[dict[str, Any]],
    public_dir: Path,
    metadata_dir: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    clear_patterns(public_dir, ("AW-*.yaml",))
    clear_patterns(metadata_dir, ("AW-*.meta.yaml",))
    ready_rows: list[dict[str, Any]] = []
    probe_count = 0
    for record in records:
        for probe in make_probe_cards(record):
            probe_count += 1
            probe_id = f"{record['algorithm_id']}-P{probe_count:04d}"
            card = probe["card"]
            meta = probe_metadata(record, probe_id, probe)
            evidence = evidence_record(record, "probe", probe_id)
            write_yaml(public_dir / f"{probe_id}.yaml", card.to_dict())
            write_yaml(metadata_dir / f"{probe_id}.meta.yaml", meta)
            write_yaml(evidence_dir / f"{probe_id}.evidence.yaml", evidence)
            ready_rows.append(probe_manifest_row(record, probe_id, probe, public_dir, metadata_dir, evidence_dir))
            if len(ready_rows) >= 600:
                break
        if len(ready_rows) >= 600:
            break
    write_probe_manifests(public_dir.parent / "manifests", ready_rows)
    return {
        "input_records": len(records),
        "ready_probe_count": len(ready_rows),
        "probe_type_counts": dict(sorted(Counter(str(row.get("probe_type", "")) for row in ready_rows).items())),
    }


def make_context_card(record: dict[str, Any]) -> tuple[PublicProblemCard | None, list[str]]:
    reasons: list[str] = []
    algorithm_id = str(record.get("algorithm_id", ""))
    name = text_value(record, "canonical_name")
    metadata = metadata_for(record)
    domain = text_value(record, "extracted_domain")
    input_semantics = text_value(record, "extracted_input_semantics")
    output_semantics = text_value(record, "extracted_output_semantics")
    problem = text_value(record, "extracted_problem_statement")
    input_model = map_input_model(domain, metadata, input_semantics)
    access_model = map_access_model(domain, metadata, input_semantics)
    output_contract = map_output_contract(domain, metadata, output_semantics)
    size_parameters = size_parameters_for(metadata, record)
    source_records = list(record.get("source_records", []))
    if not name:
        reasons.append("missing_algorithm_name")
    if not problem or domain == "unknown":
        reasons.append("missing_concrete_problem_statement")
    if not input_semantics or input_model == "unknown_input_model":
        reasons.append("unknown_input_model")
    if not output_semantics or output_contract == "unknown_output_contract":
        reasons.append("unknown_output_contract")
    if access_model == "unknown_access_model":
        reasons.append("unknown_access_model")
    if not size_parameters:
        reasons.append("missing_size_parameters")
    if not source_records:
        reasons.append("missing_source_records")

    statement = context_statement(record, input_semantics, output_semantics)
    public_text = statement + " " + name
    if leakage_matches(public_text):
        reasons.append("public_leakage_term_in_name_or_statement")
    if has_generic_phrase(statement):
        reasons.append("generic_template_phrase")
    if reasons:
        return None, stable_unique(reasons)
    card = PublicProblemCard(
        statement=statement,
        input_model=input_model,
        access_model=access_model,
        output_contract=output_contract,
        promises=context_promises(record),
        size_parameters=size_parameters,
        ambiguities=context_ambiguities(record),
    )
    try:
        validate_public_mapping(card.to_dict(), canonical_name=name, blind=False)
    except ValueError as exc:
        return None, [f"public_card_validation_failed:{exc}"]
    if len(card.statement.split()) < 80:
        return None, ["statement_too_short_for_rich_context"]
    if not algorithm_id:
        return None, ["missing_algorithm_id"]
    return card, []


def context_statement(record: dict[str, Any], input_semantics: str, output_semantics: str) -> str:
    name = text_value(record, "canonical_name")
    domain = text_value(record, "extracted_domain").replace("_", " ")
    summary = scrub_generic_text(text_value(record, "extracted_algorithm_summary"), name, domain)
    steps = scrub_generic_text(text_value(record, "extracted_pseudocode_or_steps"), name, domain)
    time_complexity = text_value(record, "extracted_classical_time_complexity") or "unknown"
    space_complexity = text_value(record, "extracted_space_complexity") or "unknown"
    model = text_value(record, "extracted_computation_model") or "not stated"
    bottleneck = text_value(record, "extracted_bottleneck")
    assumptions = "; ".join(str(item) for item in record.get("extracted_assumptions", []) if item)
    source_note = source_quality_sentence(record)
    steps_sentence = f" Classical steps or pseudocode-level structure: {steps}" if steps else ""
    assumptions_sentence = f" Source-backed uncertainty or assumptions: {assumptions}" if assumptions else ""
    return normalize_whitespace(
        f"{name} is included as a named whole-algorithm context card for a classical {domain} task. "
        f"The task is to analyze the classical input-output problem, not to certify an end-to-end improvement claim. "
        f"Input semantics: {input_semantics} Output semantics: {output_semantics} "
        f"Classical algorithm summary: {summary}{steps_sentence} "
        f"Classical complexity recorded for this row: time {time_complexity}; space {space_complexity}; computation model {model}. "
        f"Dominant bottleneck: {bottleneck} "
        "The useful review questions are whether the named structure exposes a smaller decision, witness, estimation, "
        "or algebraic subproblem; whether the full output size dominates any asymptotic gain; and whether the stated "
        "access model is realistic for the original input. "
        f"{source_note}{assumptions_sentence}"
    )


def source_quality_sentence(record: dict[str, Any]) -> str:
    sources = list(record.get("source_records", []))
    fetched = [source for source in sources if source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched"]
    if fetched:
        titles = "; ".join(str(source.get("title", ""))[:120] for source in fetched[:2] if source.get("title"))
        return f" Provenance used for reconstruction includes public metadata or abstract sources such as {titles}."
    return " Provenance is limited to AlgorithmWiki metadata and source-link facts; unresolved details are kept as ambiguities."


def context_promises(record: dict[str, Any]) -> list[str]:
    metadata = metadata_for(record)
    promises = ["source_backed_classical_context", "whole_algorithm_analysis_input"]
    if truthy(text_value(metadata, "randomized")):
        promises.append("classical_randomized_algorithm")
    if truthy(text_value(metadata, "approximate")):
        promises.append("classical_approximation_algorithm")
    model = text_value(record, "extracted_computation_model")
    if "PRAM" in model or "parallel" in model.lower():
        promises.append("classical_parallel_model_recorded")
    return stable_unique(promises)


def context_ambiguities(record: dict[str, Any]) -> list[str]:
    items = [str(item) for item in record.get("extracted_assumptions", []) if item]
    if text_value(record, "enrichment_status") != "READY_WEB_ENRICHED":
        items.append(
            "Some details are reconstructed from AlgorithmWiki metadata rather than an independently fetched full public description."
        )
    items.append("The card is a discovery input and does not encode benchmark answers or evaluator labels.")
    return stable_unique(items)


def make_probe_cards(record: dict[str, Any]) -> list[dict[str, Any]]:
    if not context_probe_parent_ok(record):
        return []
    text = rich_text(record)
    probes: list[dict[str, Any]] = []
    for probe_type in candidate_probe_types(record, text):
        probe = build_probe_candidate(record, probe_type, text)
        if probe is not None:
            probes.append(probe)
    return probes[:2]


def context_probe_parent_ok(record: dict[str, Any]) -> bool:
    return bool(text_value(record, "extracted_problem_statement")) and text_value(record, "extracted_domain") != "unknown"


def candidate_probe_types(record: dict[str, Any], text: str) -> list[str]:
    lowered = text.lower()
    domain = text_value(record, "extracted_domain")
    types: list[str] = []
    if any(term in lowered for term in ("search", "witness", "matching", "pattern", "subset", "feasible", "collision", "nearest neighbor")):
        types.append("search_witness_probe")
    if domain in {"graph", "string", "combinatorics", "optimization"} and any(
        term in lowered for term in ("path", "vertex", "edge", "pattern", "subset", "assignment", "neighbor")
    ):
        types.append("search_witness_probe")
    if any(term in lowered for term in ("random", "sampling", "monte carlo", "estimate", "approximation", "expectation", "mean")):
        types.append("estimation_sampling_probe")
    if "sparse" in lowered and any(term in lowered for term in ("linear system", "matrix", "condition")):
        types.append("sparse_linear_system_probe")
    if domain == "graph" and any(term in lowered for term in ("walk", "path", "search", "marked", "neighbor", "hitting")):
        types.append("graph_walk_probe")
    if any(term in lowered for term in ("period", "cycle length", "cyclic group", "modular", "hidden period")):
        types.append("period_structure_probe")
    return stable_unique(types)


def build_probe_candidate(record: dict[str, Any], probe_type: str, text: str) -> dict[str, Any] | None:
    builders = {
        "search_witness_probe": search_witness_probe,
        "estimation_sampling_probe": estimation_sampling_probe,
        "sparse_linear_system_probe": sparse_linear_system_probe,
        "graph_walk_probe": graph_walk_probe,
        "period_structure_probe": period_structure_probe,
    }
    probe = builders[probe_type](record, text)
    if probe is None:
        return None
    card = probe["card"]
    try:
        validate_public_mapping(card.to_dict(), blind=False)
    except ValueError:
        return None
    return probe


def search_witness_probe(record: dict[str, Any], text: str) -> dict[str, Any]:
    statement = probe_statement(
        record,
        "search-witness",
        "asks whether a predicate over candidates can expose one valid witness, counterexample, path element, "
        "pattern occurrence, or feasible object",
        "The coherent Boolean oracle and marked-item promise are introduced assumptions, not facts established by "
        "the original AlgorithmWiki row.",
    )
    card = PublicProblemCard(
        statement=statement,
        input_model=probe_input_model(record),
        access_model="coherent_boolean_oracle",
        output_contract="one_witness",
        promises=["marked_item_exists", "oracle_model_assumption"],
        size_parameters=size_parameters_for(metadata_for(record), record),
        ambiguities=probe_ambiguities(
            record, "coherent predicate construction and candidate indexing may fail for the original full-output problem"
        ),
    )
    return {
        "probe_type": "search_witness_probe",
        "card": card,
        "introduced_assumptions": ["coherent_boolean_oracle", "marked_item_exists", "candidate_indexing"],
        "missing_from_original_problem": ["oracle construction", "proof that witness output captures the useful subroutine"],
        "why_probe_is_scientifically_interesting": (
            "Witness search can isolate a decision or local-output subroutine from a larger classical task."
        ),
        "why_probe_may_fail": "The original algorithm may require full output materialization or an expensive predicate oracle.",
    }


def estimation_sampling_probe(record: dict[str, Any], text: str) -> dict[str, Any]:
    statement = probe_statement(
        record,
        "estimation-sampling",
        "reformulates the row as estimating the mean, probability, count, or numerical quantity of a bounded random variable",
        "The bounded variable and coherent sampler are introduced assumptions; any positive result would be query-level only.",
    )
    card = PublicProblemCard(
        statement=statement,
        input_model=probe_input_model(record),
        access_model="coherent_estimation_oracle",
        output_contract="additive_estimate",
        promises=["bounded_random_variable", "coherent_access", "oracle_model_assumption"],
        size_parameters=size_parameters_for(metadata_for(record), record),
        ambiguities=probe_ambiguities(
            record, "variance bounds, coherent sampler construction, and tolerance mapping remain expert obligations"
        ),
    )
    return {
        "probe_type": "estimation_sampling_probe",
        "card": card,
        "introduced_assumptions": ["coherent_estimation_oracle", "bounded_random_variable", "coherent_sampler"],
        "missing_from_original_problem": ["sampler reversibility", "variance bound", "query-to-runtime translation"],
        "why_probe_is_scientifically_interesting": (
            "Estimation tasks can expose query-level structure even when the full algorithm remains classical."
        ),
        "why_probe_may_fail": (
            "Sampling or approximation may not be the bottleneck, or coherent access may be more expensive than the original method."
        ),
    }


def sparse_linear_system_probe(record: dict[str, Any], text: str) -> dict[str, Any] | None:
    if "sparse" not in text.lower():
        return None
    statement = probe_statement(
        record,
        "sparse-linear-system",
        "isolates a sparse linear-operator subproblem with state or expectation output rather than full dense matrix output",
        "Sparsity, conditioning, prepared right-hand side, and state/expectation output are introduced assumptions.",
    )
    card = PublicProblemCard(
        statement=statement,
        input_model="explicit_matrix_problem",
        access_model="sparse_matrix_oracle",
        output_contract="state_or_expectation",
        promises=["sparse_matrix", "bounded_condition_number", "prepared_rhs", "oracle_model_assumption"],
        size_parameters=size_parameters_for(metadata_for(record), record),
        ambiguities=probe_ambiguities(record, "full dense output would invalidate the sparse state-output reformulation"),
    )
    return {
        "probe_type": "sparse_linear_system_probe",
        "card": card,
        "introduced_assumptions": ["sparse_matrix", "bounded_condition_number", "prepared_rhs", "state_or_expectation_output"],
        "missing_from_original_problem": ["conditioning guarantee", "state preparation", "observable definition"],
        "why_probe_is_scientifically_interesting": (
            "Sparse state-output linear systems are a sharply different subproblem from full matrix production."
        ),
        "why_probe_may_fail": "The row may actually require dense classical output or lack condition-number control.",
    }


def graph_walk_probe(record: dict[str, Any], text: str) -> dict[str, Any]:
    statement = probe_statement(
        record,
        "graph-walk",
        "asks whether local graph transitions and marked vertices or edges define a hitting, path, or witness subroutine",
        "Local transition access and marked-item semantics are introduced assumptions, and the original full graph "
        "output may still dominate.",
    )
    card = PublicProblemCard(
        statement=statement,
        input_model="explicit_graph_problem",
        access_model="local_graph_transition_oracle",
        output_contract="one_witness",
        promises=["marked_item_exists", "local_transition_access", "oracle_model_assumption"],
        size_parameters=size_parameters_for(metadata_for(record), record),
        ambiguities=probe_ambiguities(record, "local transition access may not represent the original graph input cheaply"),
    )
    return {
        "probe_type": "graph_walk_probe",
        "card": card,
        "introduced_assumptions": ["local_graph_transition_oracle", "marked_vertex_or_edge", "query_model_subroutine"],
        "missing_from_original_problem": ["marked-state definition", "transition implementation", "end-to-end output reconstruction"],
        "why_probe_is_scientifically_interesting": (
            "Graph search rows often hide local witness or hitting subroutines behind full-output tasks."
        ),
        "why_probe_may_fail": "The useful result may require reporting a complete path, tree, or component labeling.",
    }


def period_structure_probe(record: dict[str, Any], text: str) -> dict[str, Any]:
    statement = probe_statement(
        record,
        "period-structure",
        "isolates an actual period, cycle length, recurrence, or modular structure-finding subroutine",
        "The periodic promise is introduced only when the public source text supports cycle or period language.",
    )
    card = PublicProblemCard(
        statement=statement,
        input_model="explicit_combinatorial_problem",
        access_model="coherent_boolean_oracle",
        output_contract="exact_value",
        promises=["periodic_structure", "oracle_model_assumption"],
        size_parameters=size_parameters_for(metadata_for(record), record),
        ambiguities=probe_ambiguities(record, "periodicity may be incidental metadata rather than the task bottleneck"),
    )
    return {
        "probe_type": "period_structure_probe",
        "card": card,
        "introduced_assumptions": ["periodic_structure", "coherent_function_access"],
        "missing_from_original_problem": ["proof that period finding is the relevant subroutine"],
        "why_probe_is_scientifically_interesting": "Cycle and period rows can expose sharply structured query tasks.",
        "why_probe_may_fail": "The original row may require explicit enumeration or full-output reconstruction after detecting a period.",
    }


def probe_statement(record: dict[str, Any], label: str, task: str, assumption_sentence: str) -> str:
    name = text_value(record, "canonical_name")
    input_semantics = scrub_generic_text(text_value(record, "extracted_input_semantics"), name, text_value(record, "extracted_domain"))
    output_semantics = scrub_generic_text(text_value(record, "extracted_output_semantics"), name, text_value(record, "extracted_domain"))
    bottleneck = text_value(record, "extracted_bottleneck")
    return normalize_whitespace(
        f"{name} {label} probe. This is a subroutine/query-model probe, not an end-to-end claim for the original algorithm. "
        f"The probe {task}. Original input context: {input_semantics} Original output context: {output_semantics} "
        f"Original bottleneck noted for the rich context card: {bottleneck} "
        f"{assumption_sentence} Coherent oracle construction, promise checking, and data-mapping cost remain expert obligations. "
        f"The original algorithm may still have full-output, preprocessing, or data-loading barriers."
    )


def probe_input_model(record: dict[str, Any]) -> str:
    return map_input_model(text_value(record, "extracted_domain"), metadata_for(record), text_value(record, "extracted_input_semantics"))


def scrub_generic_text(text: str, name: str, domain: str) -> str:
    cleaned = text
    replacement = f"the concrete classical {domain.replace('_', ' ')} task associated with {name}"
    for phrase in GENERIC_PHRASES:
        cleaned = re.sub(re.escape(phrase), lambda _match: replacement, cleaned, flags=re.IGNORECASE)
    return normalize_whitespace(cleaned)


def probe_ambiguities(record: dict[str, Any], specific: str) -> list[str]:
    return stable_unique(
        [
            "This probe is assumption-bearing and is not an end-to-end speedup claim.",
            specific,
            "The parent context card and source records should be checked before live use.",
        ]
    )


def map_input_model(domain: str, metadata: dict[str, Any], input_semantics: str) -> str:
    existing = text_value(metadata, "inferred_input_model")
    if existing and existing != "unknown_input_model":
        return existing
    mapping = {
        "graph": "explicit_graph_problem",
        "sorting": "explicit_sequence_problem",
        "string": "explicit_string_problem",
        "matrix_linear_algebra": "explicit_matrix_problem",
        "numerical_analysis": "explicit_numerical_problem",
        "data_structures": "explicit_data_structure_problem",
        "dynamic_programming": "explicit_dynamic_programming_problem",
        "computational_geometry": "explicit_geometry_problem",
        "optimization": "explicit_optimization_problem",
        "randomized_sampling": "explicit_numerical_problem",
        "combinatorics": "explicit_combinatorial_problem",
        "image_processing": "explicit_image_processing_problem",
        "robotics": "explicit_robotics_problem",
        "parallel_algorithms": "explicit_parallel_algorithm_problem",
    }
    if "integer" in input_semantics.lower() or "subset" in input_semantics.lower():
        return "explicit_combinatorial_problem"
    return mapping.get(domain, "unknown_input_model")


def map_access_model(domain: str, metadata: dict[str, Any], input_semantics: str) -> str:
    existing = text_value(metadata, "inferred_access_model")
    if existing and existing != "unknown_access_model":
        return existing
    lowered = input_semantics.lower()
    if "array" in lowered or "list" in lowered:
        return "random_access_array"
    if "string" in lowered or "sequence" in lowered:
        return "random_access_string"
    if "graph" in lowered or domain == "graph":
        return "adjacency_list_query"
    if "matrix" in lowered or domain == "matrix_linear_algebra":
        return "dense_matrix_access"
    if domain == "computational_geometry":
        return "explicit_geometric_objects"
    if domain in {"data_structures", "dynamic_programming"}:
        return "offline_batch_queries"
    if domain in {"numerical_analysis", "randomized_sampling"}:
        return "function_evaluation_oracle_classical"
    if domain != "unknown":
        return "explicit_input_instance"
    return "unknown_access_model"


def map_output_contract(domain: str, metadata: dict[str, Any], output_semantics: str) -> str:
    existing = text_value(metadata, "inferred_output_contract")
    if existing and existing != "unknown_output_contract":
        return existing
    lowered = output_semantics.lower()
    if "sorted" in lowered or domain == "sorting":
        return "full_sequence_output"
    if "path" in lowered or "tree" in lowered or "spanning" in lowered:
        return "path_or_tree"
    if "witness" in lowered or "occurrence" in lowered or "neighbor" in lowered:
        return "one_witness"
    if "yes/no" in lowered or "decision" in lowered:
        return "yes_no_decision"
    if "count" in lowered:
        return "count_or_number"
    if "estimate" in lowered or "approximate" in lowered:
        return "estimate"
    if "data structure" in lowered or domain == "data_structures":
        return "data_structure_output"
    if domain == "matrix_linear_algebra":
        return "full_classical_output"
    if domain != "unknown":
        return "full_solution"
    return "unknown_output_contract"


def size_parameters_for(metadata: dict[str, Any], record: dict[str, Any]) -> list[str]:
    values = metadata.get("inferred_size_parameters", [])
    items = [str(item) for item in values if str(item).strip()] if isinstance(values, list) else []
    params = text_value(metadata, "parameter_definitions")
    if params:
        for part in re.split(r"[;\n]+", params):
            clean = normalize_whitespace(part)
            if clean:
                items.append(f"Parameter definition: {clean}")
    if not items and re.search(r"\bn\b", rich_text(record)):
        items.append("n: primary input size parameter from the AlgorithmWiki complexity expression.")
    return stable_unique(items)[:8]


def context_metadata(record: dict[str, Any], card: PublicProblemCard) -> dict[str, Any]:
    metadata = dict(metadata_for(record))
    metadata.update(
        {
            "readiness": CONTEXT_READY,
            "quality_score": int(record.get("confidence_score", metadata.get("quality_score", 0)) or 0),
            "inferred_problem_statement": text_value(record, "extracted_problem_statement"),
            "inferred_input_model": card.input_model,
            "inferred_access_model": card.access_model,
            "inferred_output_contract": card.output_contract,
            "inferred_size_parameters": card.size_parameters,
            "inferred_promises": card.promises,
            "inferred_ambiguities": card.ambiguities,
            "rich_card_kind": "context",
            "source_records_used": source_ids(record),
            "source_count": len(record.get("source_records", [])),
            "source_quality": source_quality(record),
            "confidence_score": int(record.get("confidence_score", 0) or 0),
            "card_digest": public_card_digest(card),
            "extraction_version": "algorithm-wiki-rich-context-v1",
        }
    )
    return metadata


def probe_metadata(record: dict[str, Any], probe_id: str, probe: dict[str, Any]) -> dict[str, Any]:
    card = probe["card"]
    return {
        "probe_id": probe_id,
        "algorithm_id": probe_id,
        "canonical_name": f"{record['canonical_name']} {probe['probe_type']}",
        "readiness": PROBE_READY,
        "quality_score": int(record.get("confidence_score", 0) or 0),
        "probe_type": probe["probe_type"],
        "parent_algorithm_id": str(record.get("algorithm_id", "")),
        "parent_algorithm_name": text_value(record, "canonical_name"),
        "source_records_used": source_ids(record),
        "introduced_assumptions": probe["introduced_assumptions"],
        "missing_from_original_problem": probe["missing_from_original_problem"],
        "original_output_contract": map_output_contract(
            text_value(record, "extracted_domain"), metadata_for(record), text_value(record, "extracted_output_semantics")
        ),
        "probe_output_contract": card.output_contract,
        "not_end_to_end_claim": True,
        "expected_authority": "query_or_subroutine_hypothesis_only",
        "why_probe_is_scientifically_interesting": probe["why_probe_is_scientifically_interesting"],
        "why_probe_may_fail": probe["why_probe_may_fail"],
        "inferred_input_model": card.input_model,
        "inferred_access_model": card.access_model,
        "inferred_output_contract": card.output_contract,
        "inferred_size_parameters": card.size_parameters,
        "inferred_promises": card.promises,
        "inferred_ambiguities": card.ambiguities,
        "source_count": len(record.get("source_records", [])),
        "source_quality": source_quality(record),
        "confidence_score": int(record.get("confidence_score", 0) or 0),
        "card_digest": public_card_digest(card),
        "extraction_version": "algorithm-wiki-rich-probe-v1",
    }


def evidence_record(record: dict[str, Any], kind: str, identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": kind,
        "algorithm_id": str(record.get("algorithm_id", "")),
        "algorithm_name": text_value(record, "canonical_name"),
        "source_records": record.get("source_records", []),
        "web_query_attempts": record.get("web_query_attempts", []),
        "extracted_problem_statement": text_value(record, "extracted_problem_statement"),
        "extracted_algorithm_summary": text_value(record, "extracted_algorithm_summary"),
        "confirmation": "Discovery input provenance only; no gold label, expected verdict, or hidden evidence is encoded.",
    }


def review_needed_record(record: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "algorithm_id": str(record.get("algorithm_id", "")),
        "canonical_name": text_value(record, "canonical_name"),
        "enrichment_status": text_value(record, "enrichment_status"),
        "review_reasons": stable_unique(reasons),
        "source_records": record.get("source_records", []),
        "extracted_problem_statement": text_value(record, "extracted_problem_statement"),
        "extracted_input_semantics": text_value(record, "extracted_input_semantics"),
        "extracted_output_semantics": text_value(record, "extracted_output_semantics"),
    }


def context_manifest_row(
    record: dict[str, Any],
    card: PublicProblemCard,
    public_dir: Path,
    metadata_dir: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    algorithm_id = str(record.get("algorithm_id", ""))
    metadata = metadata_for(record)
    return {
        "algorithm_id": algorithm_id,
        "algorithm_name": text_value(record, "canonical_name"),
        "public_context_path": str(public_dir / f"{algorithm_id}.yaml"),
        "metadata_context_path": str(metadata_dir / f"{algorithm_id}.meta.yaml"),
        "evidence_path": str(evidence_dir / f"{algorithm_id}.context.evidence.yaml"),
        "domain": text_value(record, "extracted_domain"),
        "input_model": card.input_model,
        "access_model": card.access_model,
        "output_contract": card.output_contract,
        "time_complexity": text_value(record, "extracted_classical_time_complexity") or text_value(metadata, "time_complexity"),
        "space_complexity": text_value(record, "extracted_space_complexity") or text_value(metadata, "space_complexity"),
        "confidence_score": int(record.get("confidence_score", 0) or 0),
        "source_count": len(record.get("source_records", [])),
        "source_quality": source_quality(record),
        "card_digest": public_card_digest(card),
    }


def probe_manifest_row(
    record: dict[str, Any],
    probe_id: str,
    probe: dict[str, Any],
    public_dir: Path,
    metadata_dir: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    card = probe["card"]
    return {
        "probe_id": probe_id,
        "parent_algorithm_id": str(record.get("algorithm_id", "")),
        "parent_algorithm_name": text_value(record, "canonical_name"),
        "public_probe_path": str(public_dir / f"{probe_id}.yaml"),
        "metadata_probe_path": str(metadata_dir / f"{probe_id}.meta.yaml"),
        "evidence_path": str(evidence_dir / f"{probe_id}.evidence.yaml"),
        "probe_type": probe["probe_type"],
        "introduced_assumptions": "; ".join(probe["introduced_assumptions"]),
        "original_output_contract": map_output_contract(
            text_value(record, "extracted_domain"), metadata_for(record), text_value(record, "extracted_output_semantics")
        ),
        "probe_output_contract": card.output_contract,
        "not_end_to_end_claim": True,
        "confidence_score": int(record.get("confidence_score", 0) or 0),
        "source_count": len(record.get("source_records", [])),
        "card_digest": public_card_digest(card),
    }


def write_context_manifests(manifest_dir: Path, ready_rows: list[dict[str, Any]], review_rows: list[dict[str, Any]]) -> None:
    write_csv(manifest_dir / "ready_public_context.csv", ready_rows)
    write_jsonl(manifest_dir / "ready_public_context.jsonl", ready_rows)
    review_csv_rows = [
        {
            "algorithm_id": row["algorithm_id"],
            "algorithm_name": row["canonical_name"],
            "enrichment_status": row["enrichment_status"],
            "review_reasons": "; ".join(row["review_reasons"]),
        }
        for row in review_rows
    ]
    write_csv(manifest_dir / "review_needed_after_web.csv", review_csv_rows)


def write_probe_manifests(manifest_dir: Path, ready_rows: list[dict[str, Any]]) -> None:
    write_csv(manifest_dir / "ready_public_probe.csv", ready_rows)
    write_jsonl(manifest_dir / "ready_public_probe.jsonl", ready_rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def clear_patterns(directory: Path, patterns: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                path.unlink()


def review_reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(str(reason) for reason in row.get("review_reasons", []))
    return dict(counts.most_common(20))


def metadata_for(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("existing_metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def text_value(record: dict[str, Any], key: str) -> str:
    return normalize_whitespace(str(record.get(key, "") or ""))


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "randomized", "approximate", "approx"}


def rich_text(record: dict[str, Any]) -> str:
    parts = [
        text_value(record, "canonical_name"),
        text_value(record, "extracted_problem_statement"),
        text_value(record, "extracted_algorithm_summary"),
        text_value(record, "extracted_input_semantics"),
        text_value(record, "extracted_output_semantics"),
    ]
    for source in record.get("source_records", []):
        if isinstance(source, dict):
            parts.append(str(source.get("title", "")))
            parts.extend(str(item) for item in source.get("extracted_facts", []) if item)
    return normalize_whitespace(" ".join(parts))


def has_generic_phrase(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in GENERIC_PHRASES)


def source_ids(record: dict[str, Any]) -> list[str]:
    return [str(source.get("source_id", "")) for source in record.get("source_records", []) if isinstance(source, dict)]


def source_quality(record: dict[str, Any]) -> str:
    qualities = [str(source.get("reliability", "")) for source in record.get("source_records", []) if isinstance(source, dict)]
    if "HIGH" in qualities:
        return "HIGH"
    if "MEDIUM" in qualities:
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    raise SystemExit(main())

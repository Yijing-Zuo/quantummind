from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    AlgorithmWikiMetadata,
    AlgorithmWikiPreCard,
    CombinedAuditCard,
    PublicProblemCard,
    blind_name_leak,
    canonicalize_name,
    infer_source_link_type,
    load_jsonl,
    normalize_whitespace,
    public_card_digest,
    stable_unique,
    validate_public_mapping,
    write_yaml,
)


@dataclass(frozen=True)
class ConvertedRecord:
    algorithm_id: str
    metadata: AlgorithmWikiMetadata
    precard: AlgorithmWikiPreCard
    blind_card: PublicProblemCard | None
    named_card: PublicProblemCard | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Algorithm Wiki normalized records into metadata, precards, and public cards.")
    parser.add_argument("--records", default="corpus/algorithm_wiki/normalized/algowiki_records_enriched.jsonl")
    parser.add_argument("--out-metadata-dir", required=True)
    parser.add_argument("--out-precard-dir", required=True)
    parser.add_argument("--out-card-dir", required=True)
    parser.add_argument("--out-public-blind-dir", required=True)
    parser.add_argument("--out-public-named-dir", required=True)
    parser.add_argument("--out-review-needed-dir")
    parser.add_argument("--out-manifest", required=True)
    parser.add_argument("--seed", type=int, default=20260627)
    args = parser.parse_args(argv)

    records_path = choose_records_path(Path(args.records))
    records = load_jsonl(records_path)
    duplicate_variants = duplicate_variant_ids(records)
    converted = [
        convert_record(record, record.get("algorithm_id", f"AW-{index:06d}") in duplicate_variants)
        for index, record in enumerate(records, 1)
    ]
    converted, duplicate_digest_groups = deduplicate_blind_card_digests(converted)

    metadata_dir = Path(args.out_metadata_dir)
    precard_dir = Path(args.out_precard_dir)
    card_dir = Path(args.out_card_dir)
    public_blind_dir = Path(args.out_public_blind_dir)
    public_named_dir = Path(args.out_public_named_dir)
    review_needed_dir = Path(args.out_review_needed_dir) if args.out_review_needed_dir else None
    output_dirs = [metadata_dir, precard_dir, card_dir, public_blind_dir, public_named_dir]
    if review_needed_dir is not None:
        output_dirs.append(review_needed_dir)
    clear_generated_outputs(*output_dirs)
    for item in converted:
        write_converted_record(
            item,
            metadata_dir,
            precard_dir,
            card_dir,
            public_blind_dir,
            public_named_dir,
            review_needed_dir,
        )

    manifest = build_manifest(converted, records_path, int(args.seed), duplicate_digest_groups)
    out_manifest = Path(args.out_manifest)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def choose_records_path(requested: Path) -> Path:
    if requested.exists():
        return requested
    if requested.name == "algowiki_records_enriched.jsonl":
        fallback = requested.with_name("algowiki_records.jsonl")
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"Algorithm Wiki records file not found: {requested}")


def duplicate_variant_ids(records: list[dict[str, Any]]) -> set[str]:
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        name = str(record.get("name", ""))
        algorithm_id = str(record.get("algorithm_id", ""))
        canonical = canonicalize_name(name)
        if canonical and algorithm_id:
            groups[canonical].append(algorithm_id)
    duplicate_ids: set[str] = set()
    for ids in groups.values():
        duplicate_ids.update(ids[1:])
    return duplicate_ids


def convert_record(record: dict[str, Any], duplicate_variant: bool = False) -> ConvertedRecord:
    algorithm_id = text_value(record, "algorithm_id")
    name = text_value(record, "name")
    domain = infer_domain(record)
    input_model = infer_input_model(domain, record)
    access_model = infer_access_model(domain, record)
    output_contract = infer_output_contract(domain, record)
    size_parameters = infer_size_parameters(domain, record)
    promises = infer_promises(record)
    problem_statement = infer_problem_statement(domain, record)
    ambiguities = infer_ambiguities(record, problem_statement, input_model, access_model, output_contract, size_parameters)
    baseline = classical_baseline(record)
    bottleneck = bottleneck_hint(domain, output_contract)
    quality_flags, quality_score = score_record(
        record, domain, problem_statement, input_model, access_model, output_contract, size_parameters
    )
    readiness, review_reasons = readiness_for_record(
        record=record,
        duplicate_variant=duplicate_variant,
        quality_score=quality_score,
        problem_statement=problem_statement,
        input_model=input_model,
        access_model=access_model,
        output_contract=output_contract,
        size_parameters=size_parameters,
    )
    metadata = AlgorithmWikiMetadata(
        algorithm_id=algorithm_id,
        canonical_name=name,
        blind_name=f"Algorithm Wiki public task {algorithm_id}",
        year=text_value(record, "year"),
        domain=domain,
        family=infer_family(record, domain),
        variation=text_value(record, "page_variation"),
        problem_name=infer_problem_name(record, domain),
        algorithm_family=infer_algorithm_family(record, domain),
        time_complexity=text_value(record, "time_complexity"),
        space_complexity=text_value(record, "space_complexity"),
        computational_model=text_value(record, "computational_model"),
        randomized=text_value(record, "randomized"),
        approximate=text_value(record, "approximate"),
        approximation_factor=text_value(record, "approximation_factor"),
        parameter_definitions=text_value(record, "parameter_definitions"),
        span_depth=text_value(record, "span_depth"),
        work=text_value(record, "work"),
        number_of_processors=text_value(record, "number_of_processors"),
        source_link=text_value(record, "link"),
        source_link_type=infer_source_link_type(text_value(record, "link")),
        page_url=text_value(record, "page_url"),
        page_fetch_status=text_value(record, "page_fetch_status") or "disabled",
        page_digest=text_value(record, "page_digest"),
        extracted_description=text_value(record, "extracted_description"),
        inferred_problem_statement=problem_statement,
        inferred_input_model=input_model,
        inferred_access_model=access_model,
        inferred_output_contract=output_contract,
        inferred_size_parameters=size_parameters,
        inferred_promises=promises,
        inferred_ambiguities=ambiguities,
        quality_score=quality_score,
        quality_flags=quality_flags,
        readiness=readiness,
        review_reasons=review_reasons,
    )
    precard = AlgorithmWikiPreCard(
        algorithm_id=algorithm_id,
        canonical_name=name,
        public_summary=public_summary(problem_statement, baseline, bottleneck),
        classical_algorithm_summary=classical_algorithm_summary(record),
        likely_problem=problem_statement or "The Algorithm Wiki row does not expose enough task semantics for a public problem card.",
        input_semantics=input_semantics(input_model, access_model, record),
        output_semantics=output_semantics(output_contract),
        classical_baseline=baseline,
        bottleneck_hint=bottleneck,
        structural_hints=structural_hints(domain, record),
        barrier_hints=barrier_hints(domain, output_contract),
        source_metadata=source_metadata(record, metadata.source_link_type),
        readiness=readiness,
        review_reasons=review_reasons,
    )
    blind_card: PublicProblemCard | None = None
    named_card: PublicProblemCard | None = None
    try:
        blind_card = make_blind_card(metadata, baseline, bottleneck) if readiness == "READY_PUBLIC_BLIND" else None
        named_card = (
            make_named_card(metadata, baseline, bottleneck) if readiness in {"READY_PUBLIC_BLIND", "READY_PUBLIC_NAMED_ONLY"} else None
        )
    except ValueError as exc:
        blind_card = None
        named_card = None
        metadata = replace(
            metadata,
            readiness="REVIEW_NEEDED",
            review_reasons=stable_unique([*metadata.review_reasons, f"public_card_validation_failed: {exc}"]),
        )
        precard = replace(precard, readiness=metadata.readiness, review_reasons=metadata.review_reasons)
    return ConvertedRecord(algorithm_id, metadata, precard, blind_card, named_card)


def deduplicate_blind_card_digests(converted: list[ConvertedRecord]) -> tuple[list[ConvertedRecord], list[dict[str, Any]]]:
    digest_groups: dict[str, list[ConvertedRecord]] = defaultdict(list)
    for item in converted:
        if item.blind_card is not None:
            digest_groups[public_card_digest(item.blind_card)].append(item)

    duplicate_groups: list[dict[str, Any]] = []
    suppressed_ids: set[str] = set()
    for digest, items in sorted(digest_groups.items()):
        if len(items) <= 1:
            continue
        keeper = items[0]
        suppressed = items[1:]
        suppressed_ids.update(item.algorithm_id for item in suppressed)
        duplicate_groups.append(
            {
                "digest": digest,
                "kept_algorithm_id": keeper.algorithm_id,
                "suppressed_algorithm_ids": [item.algorithm_id for item in suppressed],
                "group_size": len(items),
                "input_model": keeper.metadata.inferred_input_model,
                "access_model": keeper.metadata.inferred_access_model,
                "output_contract": keeper.metadata.inferred_output_contract,
            }
        )

    if not suppressed_ids:
        return converted, []
    return [
        demote_duplicate_digest(item, duplicate_groups) if item.algorithm_id in suppressed_ids else item for item in converted
    ], duplicate_groups


def demote_duplicate_digest(item: ConvertedRecord, duplicate_groups: list[dict[str, Any]]) -> ConvertedRecord:
    group = next(group for group in duplicate_groups if item.algorithm_id in group["suppressed_algorithm_ids"])
    reason = f"duplicate_public_blind_digest:{group['digest']} kept:{group['kept_algorithm_id']}"
    metadata = replace(
        item.metadata,
        readiness="DUPLICATE_VARIANT",
        review_reasons=stable_unique([*item.metadata.review_reasons, reason]),
    )
    precard = replace(item.precard, readiness=metadata.readiness, review_reasons=metadata.review_reasons)
    return ConvertedRecord(item.algorithm_id, metadata, precard, None, item.named_card)


def infer_domain(record: dict[str, Any]) -> str:
    page_domain = text_value(record, "page_domain").lower()
    page_family = text_value(record, "page_family").lower()
    page_variation = text_value(record, "page_variation").lower()
    haystack = " ".join(
        [
            text_value(record, "name"),
            text_value(record, "link"),
            text_value(record, "computational_model"),
            text_value(record, "parameter_definitions"),
            text_value(record, "extracted_description"),
            page_domain,
            page_family,
            page_variation,
        ]
    ).lower()
    if contains_any(
        haystack,
        (
            "minimum spanning tree",
            "mst",
            "shortest path",
            "dijkstra",
            "bellman-ford",
            "strongly connected",
            "vertices",
            "edges",
            "kruskal",
            "prim",
            "boruvka",
            "network flow",
            "max flow",
        ),
    ):
        return "graph"
    if contains_any(haystack, ("sort", "sorting", "merge sort", "quick sort", "heapsort", "radix", "bucket")):
        return "sorting"
    if contains_any(haystack, ("matrix", "linear algebra", "strassen", "gaussian", "cholesky", "eigen", "lu decomposition", "qr ")):
        return "matrix_linear_algebra"
    if contains_any(haystack, ("graph",)):
        return "graph"
    if contains_any(haystack, ("string", "substring", "suffix", "prefix", "edit distance", "knuth", "morris", "pratt", "boyer", "moore")):
        return "string"
    if contains_any(haystack, ("convex hull", "voronoi", "delaunay", "closest pair", "polygon", "geometric", "line segment")):
        return "computational_geometry"
    if contains_any(haystack, ("image", "pixel", "segmentation", "filter", "morphological")):
        return "image_processing"
    if contains_any(haystack, ("robot", "motion planning", "path planning")):
        return "robotics"
    if contains_any(
        haystack,
        (
            "data structure",
            "hash table",
            "union find",
            "disjoint set",
            "priority queue",
            "search tree",
            "b-tree",
            "avl tree",
            "treap",
            "scapegoat tree",
            "splay tree",
            "tango tree",
        ),
    ):
        return "data_structures"
    if contains_any(haystack, ("dynamic programming", "longest common subsequence", "lcs", "edit distance", "bellman equation")):
        return "dynamic_programming"
    if contains_any(haystack, ("numerical", "integration", "quadrature", "newton", "bisection", "root finding", "approximation")):
        return "numerical_analysis"
    if contains_any(
        haystack, ("linear programming", "simplex", "optimization", "assignment", "scheduling", "knapsack", "approximation algorithm")
    ):
        return "optimization"
    if contains_any(haystack, ("sampling", "random sample", "monte carlo", "las vegas", "randomized")):
        return "randomized_sampling"
    if contains_any(haystack, ("parallel", "pram", "work", "span", "processors", "depth")):
        return "parallel_algorithms"
    if contains_any(haystack, ("number theory", "integer factor", "prime", "gcd", "modular")):
        return "combinatorics"
    if contains_any(haystack, ("combinator", "permutation", "subset", "matching")):
        return "combinatorics"
    return "unknown"


def infer_input_model(domain: str, record: dict[str, Any]) -> str:
    name = text_value(record, "name").lower()
    model = text_value(record, "computational_model").lower()
    if domain == "sorting":
        return "explicit_sequence_problem"
    if domain == "graph":
        return "explicit_graph_problem"
    if domain == "matrix_linear_algebra":
        return "explicit_matrix_problem"
    if domain == "string":
        return "explicit_string_problem"
    if domain == "computational_geometry":
        return "explicit_geometry_problem"
    if domain == "image_processing":
        return "explicit_image_processing_problem"
    if domain == "robotics":
        return "explicit_robotics_problem"
    if domain == "data_structures":
        return "explicit_data_structure_problem"
    if domain == "dynamic_programming":
        return "explicit_dynamic_programming_problem"
    if domain == "optimization":
        return "explicit_optimization_problem"
    if domain in {"numerical_analysis", "randomized_sampling"} or contains_any(name, ("approximation", "integration", "newton", "root")):
        return "explicit_numerical_problem"
    if domain == "parallel_algorithms" or contains_any(model, ("parallel", "pram")):
        return "explicit_parallel_algorithm_problem"
    if domain == "combinatorics":
        return "explicit_combinatorial_problem"
    return "unknown_input_model"


def infer_access_model(domain: str, record: dict[str, Any]) -> str:
    name = text_value(record, "name").lower()
    haystack = f"{name} {text_value(record, 'parameter_definitions').lower()}"
    if domain == "sorting":
        return "random_access_array"
    if domain == "graph":
        if contains_any(name, ("minimum spanning", "mst", "kruskal", "prim", "boruvka", "flow")):
            return "edge_list_input"
        return "adjacency_list_query"
    if domain == "matrix_linear_algebra":
        return "dense_matrix_access"
    if domain == "string":
        return "random_access_string"
    if domain == "computational_geometry":
        return "explicit_geometric_objects"
    if domain in {"data_structures", "dynamic_programming"}:
        return "offline_batch_queries"
    if domain in {"numerical_analysis", "randomized_sampling"}:
        if contains_any(haystack, ("integration", "function", "function evaluation", "root", "newton", "bisection")):
            return "function_evaluation_oracle_classical"
        return "explicit_numeric_parameters"
    if domain in {"image_processing", "robotics", "optimization", "combinatorics", "parallel_algorithms"}:
        return "explicit_input_instance"
    return "unknown_access_model"


def infer_output_contract(domain: str, record: dict[str, Any]) -> str:
    name = text_value(record, "name").lower()
    approximate = text_value(record, "approximate").lower()
    if domain == "sorting":
        return "full_sequence_output"
    if domain == "graph":
        if contains_any(name, ("minimum spanning", "mst", "spanning tree", "prim", "kruskal", "boruvka")):
            return "path_or_tree"
        if contains_any(name, ("strongly connected", "connected component", "component")):
            return "full_solution"
        if contains_any(name, ("shortest path", "dijkstra", "bellman")):
            return "path_or_tree"
        if contains_any(name, ("matching", "flow")):
            return "full_solution"
        return "full_solution"
    if domain == "matrix_linear_algebra":
        return "full_classical_output"
    if domain == "string":
        if contains_any(name, ("match", "search", "substring")):
            return "one_witness"
        return "full_solution"
    if domain == "computational_geometry":
        return "multiple_witnesses" if contains_any(name, ("hull", "voronoi", "delaunay")) else "full_solution"
    if domain == "data_structures":
        return "data_structure_output"
    if domain == "optimization":
        return "approximation_solution" if truthy(approximate) or "approx" in name else "assignment_or_schedule"
    if domain in {"numerical_analysis", "randomized_sampling"}:
        return "approximation_solution" if truthy(approximate) or "approx" in name else "estimate"
    if domain in {"image_processing", "robotics", "dynamic_programming", "combinatorics", "parallel_algorithms"}:
        return "full_solution"
    return "unknown_output_contract"


def infer_problem_statement(domain: str, record: dict[str, Any]) -> str:
    name = text_value(record, "name").lower()
    if domain == "sorting":
        return (
            "Given a finite sequence of comparable keys or records, produce the same items "
            "in nondecreasing order under the stated classical input model."
        )
    if domain == "graph":
        if contains_any(name, ("minimum spanning", "mst", "prim", "kruskal", "boruvka")):
            return (
                "Given a weighted undirected graph, compute a minimum spanning tree or spanning forest "
                "according to the graph connectivity assumptions."
            )
        if contains_any(name, ("strongly connected", "scc")):
            return "Given a directed graph, partition the vertices into strongly connected components."
        if contains_any(name, ("shortest path", "dijkstra", "bellman")):
            return (
                "Given a weighted graph and a source or source-target specification, compute "
                "shortest-path distances or a shortest-path tree."
            )
        return "Given an explicit graph instance, compute the graph object or decomposition targeted by the classical algorithm record."
    if domain == "matrix_linear_algebra":
        return (
            "Given one or more explicit dense matrices over the stated arithmetic domain, "
            "compute the matrix or linear-algebraic output specified by the record."
        )
    if domain == "string":
        return (
            "Given one or more explicit strings, compute the matching, indexing, alignment, "
            "or transformation output targeted by the record."
        )
    if domain == "computational_geometry":
        return (
            "Given explicit geometric objects such as points, segments, or polygons, "
            "compute the requested geometric structure or witness set."
        )
    if domain == "numerical_analysis":
        return (
            "Given explicit numeric parameters or a classical function-evaluation interface, "
            "compute the requested numerical value or approximation to the stated tolerance."
        )
    if domain == "data_structures":
        return (
            "Given an explicit collection of keys, items, or offline operations, construct "
            "or return the data-structure output targeted by the record."
        )
    if domain == "optimization":
        return (
            "Given an explicit optimization instance, compute a feasible solution, schedule, "
            "assignment, or approximation with the stated classical guarantees."
        )
    if domain == "dynamic_programming":
        return (
            "Given an explicit instance with overlapping subproblem structure, compute the full "
            "classical solution or value targeted by the dynamic-programming recurrence."
        )
    if domain == "image_processing":
        return (
            "Given an explicit image or grid of pixel values, compute the transformed image, "
            "segmentation, or detected structure targeted by the record."
        )
    if domain == "robotics":
        return (
            "Given an explicit robotics planning instance, compute a feasible path, motion plan, "
            "or configuration sequence under the stated constraints."
        )
    if domain == "randomized_sampling":
        return (
            "Given explicit input data and classical randomness as part of the algorithmic model, "
            "produce the sampled or estimated output described by the record."
        )
    if domain == "parallel_algorithms":
        return (
            "Given the explicit input instance for the stated classical task, execute or analyze "
            "the parallel algorithm under its work, span, and processor-count model."
        )
    if domain == "combinatorics":
        return (
            "Given an explicit combinatorial object or parameter set, compute the requested count, construction, witness set, or ordering."
        )
    return ""


def infer_size_parameters(domain: str, record: dict[str, Any]) -> list[str]:
    params: list[str] = []
    parameter_definitions = text_value(record, "parameter_definitions")
    if parameter_definitions:
        for part in split_parameter_definitions(parameter_definitions):
            params.append(f"Parameter definition: {part}")
    if not params:
        if domain == "sorting":
            params.append("n = number of input items")
        elif domain == "graph":
            params.extend(["n = number of vertices", "m = number of edges"])
        elif domain == "matrix_linear_algebra":
            params.append("n = matrix dimension or dominant matrix size")
        elif domain == "string":
            params.append("n = input string length")
        elif domain == "computational_geometry":
            params.append("n = number of geometric objects")
        elif domain == "image_processing":
            params.extend(["h = image height", "w = image width"])
        elif domain == "data_structures":
            params.append("n = number of stored items or offline operations")
        elif domain in {"numerical_analysis", "optimization", "dynamic_programming", "randomized_sampling", "combinatorics"}:
            params.append("n = dominant input size parameter for the classical task")
    processors = text_value(record, "number_of_processors")
    if processors:
        params.append(f"p = stated number of processors ({processors})")
    return stable_unique(params)


def infer_promises(record: dict[str, Any]) -> list[str]:
    promises: list[str] = []
    model = text_value(record, "computational_model")
    if model:
        promises.append(f"Classical computational model: {model}.")
    if truthy(text_value(record, "randomized")):
        randomized_type = text_value(record, "randomized_type")
        suffix = f" ({randomized_type})" if randomized_type else ""
        promises.append(f"The classical method is marked randomized{suffix}; success guarantees require review.")
    if truthy(text_value(record, "approximate")):
        factor = text_value(record, "approximation_factor")
        suffix = f" with stated factor {factor}" if factor else ""
        promises.append(f"The classical method is marked approximate{suffix}.")
    return promises


def infer_ambiguities(
    record: dict[str, Any],
    problem_statement: str,
    input_model: str,
    access_model: str,
    output_contract: str,
    size_parameters: list[str],
) -> list[str]:
    ambiguities: list[str] = []
    if not problem_statement:
        ambiguities.append("The row does not expose enough public task text to infer a problem statement.")
    if input_model == "unknown_input_model":
        ambiguities.append("Input model is unknown from the CSV row and any available public page text.")
    if access_model == "unknown_access_model":
        ambiguities.append("Classical access model is unknown; no nonclassical access model is inferred.")
    if output_contract == "unknown_output_contract":
        ambiguities.append("Output contract is unknown from the algorithm-level metadata.")
    if not size_parameters:
        ambiguities.append("No reliable size parameters were exposed by the row.")
    if text_value(record, "page_fetch_status") in {"not_found", "fetch_failed", "disabled", ""}:
        ambiguities.append("The problem statement is inferred from sparse algorithm-level information and may need review.")
    return stable_unique(ambiguities)


def readiness_for_record(
    record: dict[str, Any],
    duplicate_variant: bool,
    quality_score: int,
    problem_statement: str,
    input_model: str,
    access_model: str,
    output_contract: str,
    size_parameters: list[str],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if duplicate_variant:
        return "DUPLICATE_VARIANT", ["A previous row has the same canonicalized algorithm name."]
    link = text_value(record, "link").lower()
    if contains_any(link, ("private", "localhost", "file://")):
        return "BAD_SOURCE", ["Source link is not a public literature or dataset link."]
    if not problem_statement:
        reasons.append("missing_problem_statement")
    if input_model == "unknown_input_model":
        reasons.append("unknown_input_model")
    if access_model == "unknown_access_model":
        reasons.append("unknown_access_model")
    if output_contract == "unknown_output_contract":
        reasons.append("unknown_output_contract")
    if not size_parameters:
        reasons.append("missing_size_parameters")
    if not has_complexity(record):
        reasons.append("missing_complexity_semantics")
    if not has_algorithm_task_cues(record, infer_domain(record)):
        reasons.append("insufficient_algorithm_level_structure")
    if reasons:
        label = "INSUFFICIENT_INFORMATION" if len(reasons) >= 3 else "REVIEW_NEEDED"
        return label, reasons
    blind_text = make_blind_statement_text(
        record, problem_statement, classical_baseline(record), bottleneck_hint(infer_domain(record), output_contract)
    )
    if blind_name_leak(text_value(record, "name"), blind_text):
        return "READY_PUBLIC_NAMED_ONLY", ["Blind statement would expose the canonical algorithm name or exact named problem."]
    if quality_score >= 60:
        return "READY_PUBLIC_BLIND", []
    return "REVIEW_NEEDED", ["quality_score_below_ready_threshold"]


def has_algorithm_task_cues(record: dict[str, Any], domain: str) -> bool:
    text = " ".join(
        text_value(record, key)
        for key in (
            "name",
            "parameter_definitions",
            "page_problem",
            "page_family",
            "page_variation",
            "extracted_description",
            "computational_model",
            "work",
            "span_depth",
            "number_of_processors",
        )
    ).lower()
    if domain == "unknown":
        return False
    domain_terms = {
        "sorting": ("sort", "merge", "bucket", "heap", "radix", "sequence", "list"),
        "graph": ("graph", "vertex", "vertices", "edge", "edges", "path", "tree", "component", "spanning", "flow"),
        "matrix_linear_algebra": ("matrix", "matrices", "linear", "eigen", "decomposition", "factorization", "product", "multiply"),
        "numerical_analysis": ("approx", "estimate", "precision", "epsilon", "numeric", "integration", "function", "cardinality"),
        "image_processing": ("image", "pixel", "grid", "segmentation", "filter", "texture"),
        "robotics": ("robot", "motion", "path", "configuration", "slam"),
        "string": ("string", "pattern", "match", "substring", "prefix", "suffix", "edit"),
        "computational_geometry": ("point", "points", "segment", "polygon", "hull", "voronoi", "delaunay", "geometric"),
        "combinatorics": ("count", "witness", "matching", "permutation", "gcd", "integer", "prime", "sequence"),
        "data_structures": ("tree", "heap", "hash", "query", "update", "dictionary", "search", "treap"),
        "optimization": ("optimization", "assignment", "schedule", "knapsack", "feasible", "approx"),
        "dynamic_programming": ("dynamic", "subproblem", "recurrence", "sequence", "edit", "lcs"),
        "randomized_sampling": ("sample", "sampling", "random", "estimate", "approx", "probability"),
        "parallel_algorithms": (
            "sort",
            "merge",
            "prefix",
            "search",
            "graph",
            "tree",
            "list",
            "matrix",
            "hull",
            "connected",
            "work",
            "span",
        ),
    }
    return any(term in text for term in domain_terms.get(domain, ()))


def make_blind_card(metadata: AlgorithmWikiMetadata, baseline: str, bottleneck: str) -> PublicProblemCard:
    card = PublicProblemCard(
        statement=make_blind_statement_text(metadata.to_dict(), metadata.inferred_problem_statement, baseline, bottleneck),
        input_model=metadata.inferred_input_model,
        access_model=metadata.inferred_access_model,
        output_contract=metadata.inferred_output_contract,
        promises=metadata.inferred_promises,
        size_parameters=metadata.inferred_size_parameters,
        ambiguities=metadata.inferred_ambiguities,
    )
    validate_public_mapping(card.to_dict(), metadata.canonical_name, blind=True)
    return card


def make_named_card(metadata: AlgorithmWikiMetadata, baseline: str, bottleneck: str) -> PublicProblemCard:
    statement = normalize_whitespace(
        f"The Algorithm Wiki record for {metadata.canonical_name} describes this classical algorithm-level task. "
        f"{metadata.inferred_problem_statement} Classical baseline: {baseline} Dominant bottleneck: {bottleneck}"
    )
    card = PublicProblemCard(
        statement=statement,
        input_model=metadata.inferred_input_model,
        access_model=metadata.inferred_access_model,
        output_contract=metadata.inferred_output_contract,
        promises=metadata.inferred_promises,
        size_parameters=metadata.inferred_size_parameters,
        ambiguities=metadata.inferred_ambiguities,
    )
    validate_public_mapping(card.to_dict())
    return card


def make_blind_statement_text(record: dict[str, Any], problem_statement: str, baseline: str, bottleneck: str) -> str:
    model = text_value(record, "computational_model")
    model_sentence = f" The relevant classical computational model is {model}." if model else ""
    return normalize_whitespace(
        f"{problem_statement} The public task is to solve the explicit classical input-output "
        "problem, not to identify a named historical method. "
        f"Classical baseline: {baseline}.{model_sentence} Dominant bottleneck: {bottleneck}"
    )


def score_record(
    record: dict[str, Any],
    domain: str,
    problem_statement: str,
    input_model: str,
    access_model: str,
    output_contract: str,
    size_parameters: list[str],
) -> tuple[list[str], int]:
    flags: list[str] = []
    score = 0
    if domain != "unknown":
        flags.append("domain_inferred")
        score += 15
    if problem_statement:
        flags.append("problem_statement_inferred")
        score += 15
    if input_model != "unknown_input_model" and access_model != "unknown_access_model" and output_contract != "unknown_output_contract":
        flags.append("io_access_output_inferred")
        score += 20
    if has_complexity(record):
        flags.append("has_complexity_semantics")
        score += 15
    if size_parameters:
        flags.append("has_size_parameters")
        score += 10
    if text_value(record, "page_fetch_status") == "found" or text_value(record, "extracted_description"):
        flags.append("has_public_page_enrichment")
        score += 10
    if text_value(record, "computational_model"):
        flags.append("has_computational_model")
        score += 5
    if truthy(text_value(record, "randomized")):
        flags.append("randomized_flag_preserved")
    if truthy(text_value(record, "approximate")):
        flags.append("approximation_flag_preserved")
    return stable_unique(flags), score


def classical_baseline(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, key in (
        ("time", "time_complexity"),
        ("space", "space_complexity"),
        ("work", "work"),
        ("span/depth", "span_depth"),
        ("processors", "number_of_processors"),
    ):
        value = text_value(record, key)
        if value and is_public_complexity_value(value):
            parts.append(f"{label} {value}")
    return "; ".join(parts) if parts else "not stated"


def public_summary(problem_statement: str, baseline: str, bottleneck: str) -> str:
    if not problem_statement:
        return "No public-ready summary is available because the row lacks enough task semantics."
    return normalize_whitespace(f"{problem_statement} Baseline: {baseline}. Bottleneck: {bottleneck}")


def classical_algorithm_summary(record: dict[str, Any]) -> str:
    name = text_value(record, "name") or "Unnamed Algorithm Wiki row"
    year = text_value(record, "year") or "unknown year"
    return normalize_whitespace(f"{name}; year {year}; {classical_baseline(record)}.")


def input_semantics(input_model: str, access_model: str, record: dict[str, Any]) -> str:
    params = text_value(record, "parameter_definitions")
    suffix = f" Parameter notes: {params}" if params else ""
    return f"{input_model} with {access_model}.{suffix}"


def output_semantics(output_contract: str) -> str:
    return f"Output contract inferred as {output_contract}; review the original public source before benchmark use."


def bottleneck_hint(domain: str, output_contract: str) -> str:
    if domain == "sorting":
        return "comparison, distribution, and full-output movement costs dominate."
    if domain == "graph":
        return "graph traversal plus writing a tree, path, partition, or full graph solution dominates."
    if domain == "matrix_linear_algebra":
        return "dense arithmetic and full matrix output dominate."
    if domain == "numerical_analysis":
        return "precision, convergence, and function-evaluation costs dominate."
    if domain == "data_structures":
        return "updates, queries, balancing, and stored representation size dominate."
    if domain == "string":
        return "string scanning, preprocessing tables, and reporting matches dominate."
    if domain == "computational_geometry":
        return "geometric predicates, ordering events, and output-sensitive structure size dominate."
    if domain == "combinatorics":
        return "search, enumeration, arithmetic, and witness materialization dominate."
    if domain == "randomized_sampling":
        return "sampling variance, success probability, and estimator precision dominate."
    if domain == "parallel_algorithms":
        return "work, span, communication, and processor-count assumptions dominate."
    if domain == "image_processing":
        return "local neighborhood processing and writing image-sized outputs dominate."
    if domain == "optimization":
        return "search-space size, feasibility constraints, and solution quality dominate."
    if domain == "dynamic_programming":
        return "subproblem count, transition evaluation, and table output dominate."
    if output_contract in {"full_solution", "full_sequence_output", "full_classical_output"}:
        return "the classical output may be large, so output size is a first-order cost."
    return "the dominant cost is unclear from available task details."


def structural_hints(domain: str, record: dict[str, Any]) -> list[str]:
    hints = [domain]
    model = text_value(record, "computational_model")
    if model:
        hints.append(f"classical model: {model}")
    if text_value(record, "work") or text_value(record, "span_depth"):
        hints.append("parallel work/span metadata present")
    return stable_unique(hints)


def barrier_hints(domain: str, output_contract: str) -> list[str]:
    hints: list[str] = []
    if output_contract in {"full_solution", "full_sequence_output", "full_classical_output"}:
        hints.append("Full output may dominate end-to-end cost.")
    if domain == "sorting":
        hints.append("Sorting records often require producing an ordered sequence, not just a decision value.")
    if domain == "graph":
        hints.append("Graph records may require materializing paths, trees, or component labels.")
    return hints or ["No strong barrier hint is available from the algorithm-level details alone."]


def source_metadata(record: dict[str, Any], source_link_type: str) -> dict[str, Any]:
    return {
        "source_dataset": text_value(record, "source_dataset") or "AlgorithmWiki",
        "year": text_value(record, "year"),
        "source_link": text_value(record, "link"),
        "source_link_type": source_link_type,
        "page_url": text_value(record, "page_url"),
        "page_fetch_status": text_value(record, "page_fetch_status") or "disabled",
        "raw_digest": text_value(record, "raw_digest"),
    }


def infer_family(record: dict[str, Any], domain: str) -> str:
    return text_value(record, "page_family") or domain


def infer_problem_name(record: dict[str, Any], domain: str) -> str:
    return text_value(record, "page_problem") or domain.replace("_", " ")


def infer_algorithm_family(record: dict[str, Any], domain: str) -> str:
    page_family = text_value(record, "page_family")
    if page_family:
        return page_family
    name = text_value(record, "name").lower()
    if "sort" in name:
        return "sorting"
    if contains_any(name, ("mst", "spanning", "shortest", "graph", "flow")):
        return "graph algorithms"
    return domain.replace("_", " ")


def split_parameter_definitions(value: str) -> list[str]:
    parts = [normalize_whitespace(part) for part in re.split(r"[;\n]+", value) if normalize_whitespace(part)]
    return parts[:8] if parts else [normalize_whitespace(value)]


def has_complexity(record: dict[str, Any]) -> bool:
    return any(is_public_complexity_value(text_value(record, key)) for key in ("time_complexity", "space_complexity", "work", "span_depth"))


def is_public_complexity_value(value: str) -> bool:
    lowered = value.lower()
    return bool(value.strip()) and not contains_any(lowered, ("http://", "https://", "www.", "doi.org", "proquest.com"))


def write_converted_record(
    item: ConvertedRecord,
    metadata_dir: Path,
    precard_dir: Path,
    card_dir: Path,
    public_blind_dir: Path,
    public_named_dir: Path,
    review_needed_dir: Path | None = None,
) -> None:
    stem = item.algorithm_id
    write_yaml(metadata_dir / f"{stem}.meta.yaml", item.metadata.to_dict())
    write_yaml(precard_dir / f"{stem}.precard.yaml", item.precard.to_dict())
    audit_card = CombinedAuditCard(stem, item.blind_card or item.named_card, item.metadata, item.precard)
    write_yaml(card_dir / f"{stem}.audit.yaml", audit_card.to_dict())
    if item.blind_card is not None:
        write_yaml(public_blind_dir / f"{stem}.yaml", item.blind_card.to_dict())
    if item.named_card is not None:
        write_yaml(public_named_dir / f"{stem}.yaml", item.named_card.to_dict())
    if review_needed_dir is not None and item.blind_card is None:
        write_yaml(
            review_needed_dir / f"{stem}.review.yaml",
            {
                "algorithm_id": item.algorithm_id,
                "readiness": item.metadata.readiness,
                "review_reasons": item.metadata.review_reasons,
                "public_named_available": item.named_card is not None,
                "metadata": item.metadata.to_dict(),
                "precard": item.precard.to_dict(),
            },
        )


def clear_generated_outputs(*directories: Path) -> None:
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        for pattern in ("AW-*.yaml", "AW-*.meta.yaml", "AW-*.precard.yaml", "AW-*.audit.yaml", "AW-*.review.yaml"):
            for path in directory.glob(pattern):
                if path.is_file():
                    path.unlink()


def build_manifest(
    converted: list[ConvertedRecord],
    records_path: Path,
    seed: int,
    duplicate_digest_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness_counts = Counter(item.metadata.readiness for item in converted)
    domain_counts = Counter(item.metadata.domain for item in converted)
    blind_ready = [item.algorithm_id for item in converted if item.blind_card is not None]
    named_ready = [item.algorithm_id for item in converted if item.named_card is not None]
    duplicate_groups = list(duplicate_digest_groups or [])
    largest_duplicate_group = max((int(group["group_size"]) for group in duplicate_groups), default=0)
    rng = random.Random(seed)
    sample = list(blind_ready or named_ready)
    rng.shuffle(sample)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "records_path": str(records_path),
        "source_limitations": source_limitations_for(records_path, len(converted)),
        "row_count": len(converted),
        "precard_count": len(converted),
        "metadata_count": len(converted),
        "public_blind_ready_count": len(blind_ready),
        "public_named_ready_count": len(named_ready),
        "review_needed_count": sum(1 for item in converted if item.blind_card is None),
        "readiness_counts": dict(sorted(readiness_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "duplicate_public_blind_digest_group_count": len(duplicate_groups),
        "largest_duplicate_public_blind_digest_group_size": largest_duplicate_group,
        "suppressed_duplicate_public_blind_count": sum(len(group["suppressed_algorithm_ids"]) for group in duplicate_groups),
        "duplicate_public_blind_digest_groups": duplicate_groups,
        "sample_ready_ids": sample[:20],
        "public_card_digests": {
            item.algorithm_id: public_card_digest(item.blind_card) for item in converted if item.blind_card is not None
        },
    }


def source_limitations_for(records_path: Path, row_count: int) -> list[str]:
    limitations: list[str] = []
    normalized_path = str(records_path).replace("\\", "/").lower()
    if "algowiki1870_v1" in normalized_path:
        limitations.append(
            "This corpus was generated from the fallback public Algorithm Wiki /download extract and must be named algowiki1870_v1."
        )
    if row_count != 1901:
        limitations.append(f"Source row_count is {row_count}, not 1901; report the actual source size in every full-stage report.")
    return limitations


def text_value(record: dict[str, Any], key: str) -> str:
    return normalize_whitespace(str(record.get(key, "") or ""))


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "randomized", "approximate", "approx", "las vegas", "monte carlo"}


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


if __name__ == "__main__":
    raise SystemExit(main())

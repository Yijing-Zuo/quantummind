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

from scripts.datasets.algowiki_build_rich_cards import (  # noqa: E402
    evidence_record,
    make_context_card,
    make_probe_cards,
    probe_manifest_row,
    probe_metadata,
    review_needed_record,
)
from scripts.datasets.algowiki_common import (  # noqa: E402
    PublicProblemCard,
    load_yaml_mapping,
    normalize_whitespace,
    public_card_digest,
    short_sha256,
    stable_unique,
    write_yaml,
)
from scripts.datasets.algowiki_select_rich_live_sets import live_command_text, live_output_dir  # noqa: E402
from scripts.datasets.algowiki_web_enrich import (  # noqa: E402
    FetchBudget,
    algorithm_wiki_source,
    extract_arxiv_id,
    extract_doi,
    fetch_arxiv,
    fetch_crossref,
    fetch_public_url,
    fetch_wikipedia,
    first_sentence,
    short_quote,
)

OUTPUT_DIRS = (
    "enriched_records_second_pass",
    "public_context_recovered",
    "public_probe_recovered",
    "metadata_context_recovered",
    "metadata_probe_recovered",
    "evidence_recovered",
    "still_review_needed",
    "audit",
    "reports",
    "manifests",
    "commands",
    "raw_web_cache_second_pass",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Second-pass enrichment for AlgorithmWiki rows still review-needed after rich v1.")
    parser.add_argument("--review-needed", required=True)
    parser.add_argument("--enriched-jsonl", required=True)
    parser.add_argument("--metadata-dir", required=True)
    parser.add_argument("--precard-dir", required=True)
    parser.add_argument("--out-root", default="corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass")
    parser.add_argument("--max-rows", type=int, default=545)
    parser.add_argument("--max-source-fetches", type=int, default=900)
    parser.add_argument("--sleep-seconds", type=float, default=0.08)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)

    root = Path(args.out_root)
    for directory in OUTPUT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    clear_outputs(root)

    review_rows = read_csv(Path(args.review_needed))[: int(args.max_rows)]
    base_records = load_jsonl_by_id(Path(args.enriched_jsonl))
    fetch_budget = FetchBudget(int(args.max_source_fetches))
    robots: dict[str, Any] = {}
    enriched_records: list[dict[str, Any]] = []
    reconstruction_notes: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    probe_rows: list[dict[str, Any]] = []
    still_rows: list[dict[str, Any]] = []
    probe_index = 0

    for review_row in review_rows:
        algorithm_id = str(review_row["algorithm_id"])
        metadata = load_yaml_mapping(Path(args.metadata_dir) / f"{algorithm_id}.meta.yaml")
        precard_path = Path(args.precard_dir) / f"{algorithm_id}.precard.yaml"
        precard = load_yaml_mapping(precard_path) if precard_path.exists() else {}
        base_record = base_records.get(algorithm_id, {})
        enriched = enrich_second_pass_record(
            review_row,
            base_record,
            metadata,
            precard,
            root / "raw_web_cache_second_pass",
            fetch_budget,
            robots,
            float(args.sleep_seconds),
            float(args.timeout_seconds),
        )
        note = reconstruction_note(enriched)
        enriched_records.append(enriched)
        reconstruction_notes.append(note)

        if note["reconstruction_decision"] in {"RECOVER_CONTEXT", "RECOVER_CONTEXT_AND_PROBE"}:
            card, reasons = make_context_card(enriched)
            if card is None:
                note["reconstruction_decision"] = "STILL_REVIEW_NEEDED"
                note["unresolved_ambiguity"] = "; ".join(stable_unique([note["unresolved_ambiguity"], *reasons]))
            else:
                write_recovered_context(root, enriched, card)
                context_rows.append(context_manifest_row(root, enriched, card))
        if note["reconstruction_decision"] in {"RECOVER_CONTEXT_AND_PROBE", "RECOVER_PROBE_ONLY"}:
            for probe in make_probe_cards(enriched):
                probe_index += 1
                probe_id = f"{algorithm_id}-SP{probe_index:04d}"
                card = probe["card"]
                write_recovered_probe(root, enriched, probe_id, probe)
                probe_rows.append(
                    probe_manifest_row(
                        enriched,
                        probe_id,
                        probe,
                        root / "public_probe_recovered",
                        root / "metadata_probe_recovered",
                        root / "evidence_recovered",
                    )
                )
                if len(probe_rows) >= 250:
                    break
        if note["reconstruction_decision"] == "STILL_REVIEW_NEEDED":
            still = review_needed_record(
                enriched, [note["unresolved_ambiguity"] or "source-backed I/O reconstruction is still insufficient"]
            )
            write_yaml(root / "still_review_needed" / f"{algorithm_id}.yaml", still)
            still_rows.append(still_manifest_row(still, note))
        if len(probe_rows) >= 250:
            # Keep the second pass selective; remaining rows can still recover context.
            pass

    write_jsonl(root / "enriched_records_second_pass" / "enriched_algorithms_second_pass.jsonl", enriched_records)
    write_jsonl(root / "enriched_records_second_pass" / "reconstruction_notes.jsonl", reconstruction_notes)
    write_csv(root / "manifests" / "recovered_context.csv", context_rows)
    write_jsonl(root / "manifests" / "recovered_context.jsonl", context_rows)
    write_csv(root / "manifests" / "recovered_probe.csv", probe_rows)
    write_jsonl(root / "manifests" / "recovered_probe.jsonl", probe_rows)
    write_csv(root / "manifests" / "still_review_needed.csv", still_rows)
    write_source_index(root)
    write_commands(root)
    report = build_report(review_rows, reconstruction_notes, context_rows, probe_rows, still_rows, fetch_budget)
    write_json(root / "manifests" / "second_pass_manifest.json", report)
    write_text(root / "reports" / "second_pass_enrichment_report.md", markdown_report(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def enrich_second_pass_record(
    review_row: dict[str, str],
    base_record: dict[str, Any],
    metadata: dict[str, Any],
    precard: dict[str, Any],
    cache_dir: Path,
    fetch_budget: FetchBudget,
    robots: dict[str, Any],
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    algorithm_id = str(metadata.get("algorithm_id", review_row.get("algorithm_id", "")))
    name = text_value(metadata, "canonical_name")
    source_records = merge_sources(list(base_record.get("source_records", [])), [algorithm_wiki_source(metadata, precard)])
    attempts = second_pass_attempts(name, metadata, source_records)

    doi = extract_doi(text_value(metadata, "source_link"))
    if doi and not has_source_type(source_records, "doi_metadata"):
        attempts.append(attempt(doi, "crossref_doi_metadata", "attempted"))
        source = fetch_crossref(doi, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        update_last_attempt(attempts, source)
        if source:
            source_records.append(source)
    arxiv_id = extract_arxiv_id(text_value(metadata, "source_link"))
    if arxiv_id and not has_source_type(source_records, "arxiv_abstract"):
        attempts.append(attempt(arxiv_id, "arxiv_abstract_metadata", "attempted"))
        source = fetch_arxiv(arxiv_id, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        update_last_attempt(attempts, source)
        if source:
            source_records.append(source)

    title_query = best_title_query(name, source_records)
    if title_query and fetch_budget.remaining > 0:
        attempts.append(attempt(title_query + " algorithm", "crossref_title_search", "attempted"))
        source = fetch_crossref_title_search(title_query + " algorithm", cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        update_last_attempt(attempts, source)
        if source:
            source_records.append(source)
    if should_fetch_wiki(name, source_records) and fetch_budget.remaining > 0:
        attempts.append(attempt(name + " algorithm", "wikipedia_summary_search", "attempted"))
        source = fetch_wikipedia(name, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        update_last_attempt(attempts, source)
        if source:
            source_records.append(source)

    reconstructed = reconstruct_fields(metadata, precard, source_records)
    confidence = reconstructed["confidence_score"]
    status = "SECOND_PASS_RECOVERED" if confidence >= 65 and reconstructed["problem_statement"] else "SECOND_PASS_INSUFFICIENT"
    return {
        "algorithm_id": algorithm_id,
        "canonical_name": name,
        "original_algorithm_name": name,
        "source_link": text_value(metadata, "source_link"),
        "source_link_type": text_value(metadata, "source_link_type") or "unknown",
        "existing_metadata": metadata,
        "web_query_attempts": attempts[:12],
        "source_records": merge_sources(source_records, []),
        "extracted_problem_statement": reconstructed["problem_statement"],
        "extracted_algorithm_summary": reconstructed["algorithm_summary"],
        "extracted_pseudocode_or_steps": reconstructed["steps"],
        "extracted_input_semantics": reconstructed["input_semantics"],
        "extracted_output_semantics": reconstructed["output_semantics"],
        "extracted_classical_time_complexity": reconstructed["time_complexity"],
        "extracted_space_complexity": reconstructed["space_complexity"],
        "extracted_computation_model": reconstructed["computation_model"],
        "extracted_bottleneck": reconstructed["bottleneck"],
        "extracted_assumptions": reconstructed["assumptions"],
        "extracted_domain": reconstructed["domain"],
        "extracted_family": reconstructed["family"],
        "confidence_score": confidence,
        "enrichment_status": status,
        "second_pass_rule": reconstructed["rule_id"],
        "second_pass_unresolved": reconstructed["unresolved"],
    }


def reconstruct_fields(metadata: dict[str, Any], precard: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    text = rich_text(metadata, precard, sources)
    name = text_value(metadata, "canonical_name")
    rule = choose_rule(text, name, metadata)
    if forbidden_public_name(name, text):
        rule = {}
    if not rule:
        return unresolved_reconstruction(metadata, "No second-pass rule could identify source-backed task semantics.")
    complexity = complexity_summary(metadata)
    source_sentence = source_support_sentence(sources)
    problem = (
        f"{name} is reconstructed as a classical {rule['domain'].replace('_', ' ')} task. "
        f"Problem/task: {rule['task']} Input semantics: {rule['input']} Output semantics: {rule['output']}"
    )
    summary = f"{name} is treated as the named AlgorithmWiki variant for {rule['task']} {complexity}. {source_sentence}"
    assumptions = []
    if rule.get("uncertainty"):
        assumptions.append(str(rule["uncertainty"]))
    if only_algorithm_wiki_source(sources):
        assumptions.append("Second-pass evidence is primarily AlgorithmWiki metadata plus public source-link/title facts.")
    return {
        "problem_statement": normalize_whitespace(problem),
        "algorithm_summary": normalize_whitespace(summary),
        "steps": str(rule.get("steps", "")),
        "input_semantics": str(rule["input"]),
        "output_semantics": str(rule["output"]),
        "time_complexity": text_value(metadata, "time_complexity") or "unknown",
        "space_complexity": text_value(metadata, "space_complexity") or "unknown",
        "computation_model": text_value(metadata, "computational_model") or "not stated",
        "bottleneck": str(rule["bottleneck"]),
        "assumptions": stable_unique(assumptions),
        "domain": str(rule["domain"]),
        "family": str(rule.get("family", rule["domain"])),
        "confidence_score": min(int(metadata.get("quality_score", 0) or 0) + int(rule.get("score", 40)) + source_bonus(sources), 100),
        "rule_id": str(rule["rule_id"]),
        "unresolved": "",
    }


def choose_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    lowered = text.lower()
    params = text_value(metadata, "parameter_definitions").lower()
    checks = [
        subset_sum_rule,
        motif_rule,
        matrix_chain_rule,
        vandermonde_rule,
        string_matching_rule,
        automata_subset_rule,
        integer_multiplication_rule,
        max_subarray_rule,
        rod_cutting_rule,
        coin_change_rule,
        image_feature_rule,
        rendering_rule,
        culling_rule,
        segmentation_rule,
        factorization_rule,
        mutual_exclusion_rule,
        dining_philosophers_rule,
        sequence_assembly_rule,
        geometry_points_rule,
        n_queens_rule,
        cycle_detection_rule,
        graph_named_rule,
        data_structure_rule,
    ]
    for check in checks:
        rule = check(lowered, name.lower(), params)
        if rule:
            return rule
    return {}


def base_rule(rule_id: str, domain: str, family: str, task: str, input_text: str, output: str, bottleneck: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "domain": domain,
        "family": family,
        "task": task,
        "input": input_text,
        "output": output,
        "bottleneck": bottleneck,
        "score": 45,
    }


def subset_sum_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "target sum" not in text and "subset sum" not in text:
        return {}
    return base_rule(
        "subset_sum",
        "dynamic_programming",
        "subset_sum",
        "solve a subset-sum or target-sum decision/witness instance",
        "A finite set or multiset of integers S, its size n, and a target value t.",
        "A yes/no decision and, when requested, a subset whose sum equals the target.",
        "The pseudopolynomial table, algebraic convolution, or witness reconstruction dominates.",
    )


def motif_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if not any(term in text for term in ("motif", "common sites", "biopolymer sequences", "unaligned")):
        return {}
    return base_rule(
        "motif_discovery",
        "string",
        "motif_discovery",
        "identify shared motifs or common sites in biological sequences",
        "A collection of sequences, sequence length parameters, alphabet information, and motif/model parameters.",
        "Motif locations, motif model parameters, or a scored set of common sequence sites.",
        "Scanning sequence windows and optimizing model likelihood or sampling hidden motif positions dominates.",
    )


def matrix_chain_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "number of matrices" not in text:
        return {}
    return base_rule(
        "matrix_chain_ordering",
        "dynamic_programming",
        "matrix_chain_multiplication",
        "choose a parenthesization/order for multiplying a chain of matrices",
        "A sequence of matrix dimensions for n matrices.",
        "An optimal parenthesization or multiplication cost for the matrix chain.",
        "The number of subproblems and split-point transitions dominate.",
    )


def vandermonde_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "bjorck" not in text and "pereyra" not in text and "vandermonde" not in text:
        return {}
    return base_rule(
        "vandermonde_linear_system",
        "matrix_linear_algebra",
        "vandermonde_system_solving",
        "solve a Vandermonde-structured linear system",
        "A Vandermonde matrix described by nodes and a right-hand-side vector.",
        "The solution vector or equivalent structured linear-system output.",
        "Structured polynomial/interpolation arithmetic and numerical stability dominate.",
    )


def string_matching_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if not any(term in text for term in ("pattern length", "text length", "searchable text", "rabin-karp", "bitap", "boyer", "matching")):
        return {}
    return base_rule(
        "string_matching",
        "string",
        "string_matching",
        "find occurrences of a pattern in a text",
        "A finite text string, a finite pattern string, and alphabet/hash/preprocessing parameters when stated.",
        "One or more occurrence positions or a report that no occurrence exists.",
        "Text scanning, preprocessing tables or hashes, and match verification dominate.",
    )


def automata_subset_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "powerset construction" not in text and "number of states" not in text:
        return {}
    return base_rule(
        "automata_subset_construction",
        "combinatorics",
        "finite_automata_determinization",
        "convert a nondeterministic finite automaton into an equivalent deterministic automaton",
        "A finite automaton with n states, alphabet, transition relation, start states, and accepting states.",
        "The reachable deterministic automaton states and transition table.",
        "The exponential subset-state space and transition materialization dominate.",
    )


def integer_multiplication_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("karatsuba", "toom", "long multiplication", "furer", "fürer", "harvey hoeven", "integer multiplication")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "integer_multiplication",
        "combinatorics",
        "integer_arithmetic",
        "multiply large integers",
        "Two integers represented by n-bit or n-limb strings.",
        "The exact product integer.",
        "Recursive splitting, convolution, carry propagation, and writing the full product dominate.",
    )


def max_subarray_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "kadane" not in text and "programming pearls" not in text and not ("length of array" in text and "grenander" in text):
        return {}
    return base_rule(
        "maximum_subarray",
        "dynamic_programming",
        "maximum_subarray",
        "find a contiguous subarray with maximum sum",
        "A numeric array of length n.",
        "The maximum subarray value and optionally the interval attaining it.",
        "Scanning candidate intervals or maintaining dynamic prefix information dominates.",
    )


def rod_cutting_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "length of rod" not in text:
        return {}
    return base_rule(
        "rod_cutting",
        "dynamic_programming",
        "rod_cutting",
        "choose cuts of a rod to maximize total price",
        "A rod length n and a price table for cut lengths.",
        "An optimal revenue value and optionally a cut pattern.",
        "The recurrence over lengths and split choices dominates.",
    )


def coin_change_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "coin denominations" not in text:
        return {}
    return base_rule(
        "coin_change",
        "dynamic_programming",
        "coin_change",
        "make or count ways to make a target sum using coin denominations",
        "A set of coin denominations, count n, and target sum S.",
        "A feasibility answer, count, or minimum-coin witness depending on the variant.",
        "The target-sum dynamic-programming table dominates.",
    )


def image_feature_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("corner detector", "sift", "surf", "blob detection", "interest points", "moravec", "förstner", "hessian")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "image_feature_detection",
        "image_processing",
        "feature_detection",
        "detect local image features such as corners, blobs, or scale-invariant keypoints",
        "An image or image pyramid/grid of pixel intensities plus detector parameters.",
        "A set of detected feature locations, scales, orientations, or descriptors.",
        "Local filtering, scale-space construction, nonmaximum suppression, and descriptor output dominate.",
    )


def rendering_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("rendering", "shading", "illumination", "phong", "blinn", "cook", "torrance", "ray", "reflection")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "rendering_shading",
        "image_processing",
        "computer_graphics_rendering",
        "compute shaded/rendered image values from a geometric scene and illumination model",
        "Scene geometry, material parameters, lights, camera/view information, and image resolution.",
        "Rendered pixel colors or intermediate shading/visibility values.",
        "Visibility tests, lighting evaluation, sampling, and writing image-sized output dominate.",
    )


def culling_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "culling" not in text and "view frustum" not in text:
        return {}
    return base_rule(
        "visibility_culling",
        "computational_geometry",
        "visibility_culling",
        "discard scene objects that cannot contribute to a rendered view",
        "A scene/object set, view frustum or occlusion representation, and visibility thresholds.",
        "The subset of visible or potentially visible objects.",
        "Geometric visibility tests and maintaining conservative visible sets dominate.",
    )


def segmentation_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("segmentation", "watershed", "region merging", "split and merge", "mumford", "markov random field")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "image_segmentation",
        "image_processing",
        "image_segmentation",
        "partition an image into coherent regions or labels",
        "An image grid with pixel intensities/features and model or merge/split parameters.",
        "A segmentation labeling, boundary set, or region hierarchy.",
        "Neighborhood evaluation, region merging/splitting, energy optimization, and output labeling dominate.",
    )


def factorization_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("factorization", "trial division", "quadratic sieve", "rational sieve", "dixon", "fermat", "squfof", "lenstra")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "integer_factorization",
        "combinatorics",
        "integer_factorization",
        "find a nontrivial factorization of an integer",
        "An integer N represented with n bits and method-specific smoothness or search bounds.",
        "A nontrivial factor, a complete factorization, or a failure indication under the method assumptions.",
        "Candidate generation, modular arithmetic, smoothness testing, and relation collection dominate.",
    )


def mutual_exclusion_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("bakery algorithm", "maekawa", "suzuki", "mutual exclusion", "processes")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "distributed_mutual_exclusion",
        "parallel_algorithms",
        "distributed_mutual_exclusion",
        "coordinate process access to a critical section without simultaneous entry",
        "A set of processes, request/release events, and shared-memory or message-passing assumptions.",
        "A protocol state sequence or decision granting safe critical-section access.",
        "Message or shared-variable access, waiting conditions, and fairness/progress constraints dominate.",
    )


def dining_philosophers_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "philosophers" not in text:
        return {}
    return base_rule(
        "dining_philosophers",
        "parallel_algorithms",
        "resource_allocation",
        "schedule resource acquisition to avoid unsafe dining-philosophers states",
        "A set of philosophers/processes and shared fork/resource constraints.",
        "A safe allocation or protocol schedule satisfying mutual exclusion/progress constraints.",
        "State-space growth and coordination constraints dominate.",
    )


def sequence_assembly_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("overlap layout consensus", "reads", "input sequences", "seqaid")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "sequence_assembly",
        "string",
        "sequence_assembly",
        "assemble sequences from reads using overlap/layout/consensus structure",
        "A collection of sequence reads and their total length or count.",
        "An assembled sequence, overlap graph/layout, or consensus representation.",
        "Pairwise overlap computation and consensus reconstruction dominate.",
    )


def geometry_points_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "number of points" not in text and "dimension of space" not in text:
        return {}
    return base_rule(
        "point_set_geometry",
        "computational_geometry",
        "point_set_geometry",
        "compute a geometric structure or relation over a finite point set",
        "A finite set of points, dimension k when stated, and geometric predicate assumptions.",
        "A geometric witness, nearest/closest relation, hull, partition, or related structure supported by the named row.",
        "Distance/geometric predicate evaluation and output-sensitive structure size dominate.",
    ) | {"uncertainty": "The exact geometric output may need source review when the row is author-only."}


def n_queens_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "queens" not in text and "board" not in text:
        return {}
    return base_rule(
        "n_queens",
        "combinatorics",
        "n_queens",
        "place queens on a board subject to nonattacking constraints",
        "A board dimension n and a requested number of queens k when stated.",
        "A feasible placement or decision that no such placement exists.",
        "Backtracking/search over placements and constraint checking dominate.",
    )


def cycle_detection_rule(text: str, name: str, params: str) -> dict[str, Any]:
    if "cycle length" not in text and "first index of element in cycle" not in text and "period" not in text:
        return {}
    return base_rule(
        "cycle_detection",
        "combinatorics",
        "cycle_detection",
        "detect the preperiod and cycle in an iterated sequence",
        "An iterated function or sequence access plus parameters for preperiod and cycle length.",
        "The first cycle index and cycle length, or a repeated-state witness.",
        "Function iteration and memory/time tradeoffs for repeated-state detection dominate.",
    )


def graph_named_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("graph", "shortest path", "spanning", "network", "flow")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "named_graph_problem",
        "graph",
        "graph",
        "solve the named graph task indicated by the public source metadata",
        "An explicit graph with vertices, edges, weights, labels, or adjacency access as required by the row.",
        "A path, tree, component labeling, flow, matching, or witness object for the named graph task.",
        "Traversal, priority/frontier maintenance, and materializing graph outputs dominate.",
    ) | {"uncertainty": "The row should be reviewed if the source title does not specify the graph output exactly."}


def data_structure_rule(text: str, name: str, params: str) -> dict[str, Any]:
    terms = ("hashing", "priority queue", "tree", "dictionary", "heap")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "data_structure",
        "data_structures",
        "data_structure",
        "maintain a data structure supporting the named operations",
        "A set of records and operation sequence for insert, delete, query, or search operations.",
        "A maintained representation and answers to the supported queries.",
        "Update/query costs, balancing, hashing, and representation size dominate.",
    )


def unresolved_reconstruction(metadata: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "problem_statement": "",
        "algorithm_summary": "",
        "steps": "",
        "input_semantics": "",
        "output_semantics": "",
        "time_complexity": text_value(metadata, "time_complexity") or "unknown",
        "space_complexity": text_value(metadata, "space_complexity") or "unknown",
        "computation_model": text_value(metadata, "computational_model") or "not stated",
        "bottleneck": "",
        "assumptions": [reason],
        "domain": "unknown",
        "family": "unknown",
        "confidence_score": int(metadata.get("quality_score", 0) or 0),
        "rule_id": "none",
        "unresolved": reason,
    }


def reconstruction_note(record: dict[str, Any]) -> dict[str, Any]:
    decision = "STILL_REVIEW_NEEDED"
    if record["enrichment_status"] == "SECOND_PASS_RECOVERED":
        probes = "search" in rich_record_text(record).lower() or "estimate" in rich_record_text(record).lower()
        decision = "RECOVER_CONTEXT_AND_PROBE" if probes else "RECOVER_CONTEXT"
    if "duplicate" in rich_record_text(record).lower() and record["confidence_score"] < 65:
        decision = "DUPLICATE_ONLY"
    if forbidden_public_name(str(record.get("canonical_name", "")), rich_record_text(record)):
        decision = "BAD_SOURCE"
    if decision in {"BAD_SOURCE", "DUPLICATE_ONLY"}:
        decision = "STILL_REVIEW_NEEDED"
    return {
        "algorithm_id": record["algorithm_id"],
        "canonical_name": record["canonical_name"],
        "likely_problem": record["extracted_problem_statement"],
        "input_semantics": record["extracted_input_semantics"],
        "output_semantics": record["extracted_output_semantics"],
        "classical_complexity": record["extracted_classical_time_complexity"],
        "computational_model": record["extracted_computation_model"],
        "bottleneck": record["extracted_bottleneck"],
        "source_evidence": source_ids(record),
        "unresolved_ambiguity": record["second_pass_unresolved"],
        "confidence_score": record["confidence_score"],
        "reconstruction_decision": decision,
        "rule_id": record["second_pass_rule"],
    }


def write_recovered_context(root: Path, record: dict[str, Any], card: PublicProblemCard) -> None:
    algorithm_id = str(record["algorithm_id"])
    metadata = dict(record["existing_metadata"])
    metadata.update(
        {
            "readiness": "READY_PUBLIC_CONTEXT",
            "quality_score": int(record.get("confidence_score", 0) or 0),
            "inferred_problem_statement": record["extracted_problem_statement"],
            "inferred_input_model": card.input_model,
            "inferred_access_model": card.access_model,
            "inferred_output_contract": card.output_contract,
            "inferred_size_parameters": card.size_parameters,
            "inferred_promises": card.promises,
            "inferred_ambiguities": card.ambiguities,
            "rich_card_kind": "context_recovered",
            "source_records_used": source_ids(record),
            "source_count": len(record.get("source_records", [])),
            "source_quality": source_quality(record),
            "confidence_score": int(record.get("confidence_score", 0) or 0),
            "card_digest": public_card_digest(card),
            "second_pass_rule": record.get("second_pass_rule", ""),
            "extraction_version": "algorithm-wiki-rich-second-pass-context-v1",
        }
    )
    write_yaml(root / "public_context_recovered" / f"{algorithm_id}.yaml", card.to_dict())
    write_yaml(root / "metadata_context_recovered" / f"{algorithm_id}.meta.yaml", metadata)
    write_yaml(
        root / "evidence_recovered" / f"{algorithm_id}.context.evidence.yaml", evidence_record(record, "context_recovered", algorithm_id)
    )


def write_recovered_probe(root: Path, record: dict[str, Any], probe_id: str, probe: dict[str, Any]) -> None:
    card = probe["card"]
    metadata = probe_metadata(record, probe_id, probe)
    metadata["readiness"] = "READY_PUBLIC_PROBE"
    metadata["rich_card_kind"] = "probe_recovered"
    metadata["extraction_version"] = "algorithm-wiki-rich-second-pass-probe-v1"
    write_yaml(root / "public_probe_recovered" / f"{probe_id}.yaml", card.to_dict())
    write_yaml(root / "metadata_probe_recovered" / f"{probe_id}.meta.yaml", metadata)
    write_yaml(root / "evidence_recovered" / f"{probe_id}.evidence.yaml", evidence_record(record, "probe_recovered", probe_id))


def context_manifest_row(root: Path, record: dict[str, Any], card: PublicProblemCard) -> dict[str, Any]:
    algorithm_id = str(record["algorithm_id"])
    return {
        "algorithm_id": algorithm_id,
        "algorithm_name": str(record["canonical_name"]),
        "public_context_path": str(root / "public_context_recovered" / f"{algorithm_id}.yaml"),
        "metadata_context_path": str(root / "metadata_context_recovered" / f"{algorithm_id}.meta.yaml"),
        "evidence_path": str(root / "evidence_recovered" / f"{algorithm_id}.context.evidence.yaml"),
        "domain": str(record["extracted_domain"]),
        "input_model": card.input_model,
        "access_model": card.access_model,
        "output_contract": card.output_contract,
        "time_complexity": str(record["extracted_classical_time_complexity"]),
        "space_complexity": str(record["extracted_space_complexity"]),
        "confidence_score": int(record["confidence_score"]),
        "source_count": len(record.get("source_records", [])),
        "source_quality": source_quality(record),
        "card_digest": public_card_digest(card),
        "second_pass_rule": str(record.get("second_pass_rule", "")),
    }


def still_manifest_row(still: dict[str, Any], note: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm_id": str(still.get("algorithm_id", "")),
        "algorithm_name": str(still.get("canonical_name", "")),
        "reconstruction_decision": str(note.get("reconstruction_decision", "STILL_REVIEW_NEEDED")),
        "review_reasons": "; ".join(str(item) for item in still.get("review_reasons", [])),
        "confidence_score": str(note.get("confidence_score", "")),
    }


def second_pass_attempts(name: str, metadata: dict[str, Any], sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    title = best_title_query(name, sources)
    queries = [
        f'"{name}" algorithm',
        f'"{name}" input output',
        f'"{name}" time complexity',
        f'"{name}" pseudocode',
        f'"{name}" problem',
        f'"{name}" PDF metadata abstract',
    ]
    if title and title != name:
        queries.append(f'"{title}" algorithm')
    source_link = text_value(metadata, "source_link")
    if source_link:
        queries.append(source_link)
    return [attempt(query, "search_plan", "recorded") for query in queries]


def fetch_crossref_title_search(
    query: str,
    cache_dir: Path,
    fetch_budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not fetch_budget.consume():
        return None
    url = "https://api.crossref.org/works?rows=1&query.title=" + quote_query(query)
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if payload["status"] != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    items = data.get("message", {}).get("items", [])
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    title = first_string(item.get("title")) or query
    abstract = first_sentence(strip_tags(str(item.get("abstract", ""))))
    facts = [f"Crossref title-search result: {title}"]
    if abstract:
        facts.append(f"abstract summary: {abstract}")
    return {
        "source_id": "crossref_search:" + short_sha256(query),
        "url": str(item.get("URL", "")),
        "title": title,
        "source_type": "doi_metadata",
        "access_status": "fetched",
        "reliability": "MEDIUM",
        "extracted_facts": facts,
        "short_quote": short_quote(abstract),
        "digest": short_sha256({"query": query, "title": title, "abstract": abstract}),
    }


def write_source_index(root: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "evidence_recovered").glob("*.evidence.yaml")):
        evidence = load_yaml_mapping(path)
        for source in evidence.get("source_records", []):
            if isinstance(source, dict):
                rows.append(
                    {
                        "card_or_probe_id": str(evidence.get("id", path.stem)),
                        "algorithm_id": str(evidence.get("algorithm_id", "")),
                        "algorithm_name": str(evidence.get("algorithm_name", "")),
                        "source_id": str(source.get("source_id", "")),
                        "url": str(source.get("url", "")),
                        "title": str(source.get("title", "")),
                        "source_type": str(source.get("source_type", "")),
                        "access_status": str(source.get("access_status", "")),
                        "reliability": str(source.get("reliability", "")),
                        "digest": str(source.get("digest", "")),
                    }
                )
    write_csv(root / "manifests" / "recovered_web_source_index.csv", rows)


def write_commands(root: Path) -> None:
    command_dir = root / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    (command_dir / "run_live_recovered_context_first_50_openai.bat").write_text(live_command(root, "context", "first_50"), encoding="utf-8")
    (command_dir / "run_live_recovered_context_shard_openai.bat").write_text(live_command(root, "context", "shard"), encoding="utf-8")
    (command_dir / "run_live_recovered_context_all_openai.bat").write_text(live_command(root, "context", "all"), encoding="utf-8")
    (command_dir / "run_live_recovered_probe_first_50_openai.bat").write_text(live_command(root, "probe", "first_50"), encoding="utf-8")
    (command_dir / "run_live_recovered_probe_shard_openai.bat").write_text(live_command(root, "probe", "shard"), encoding="utf-8")
    (command_dir / "run_live_recovered_probe_all_openai.bat").write_text(live_command(root, "probe", "all"), encoding="utf-8")
    (command_dir / "summarize_recovered_context_runs.bat").write_text(summary_command(root, "context"), encoding="utf-8")
    (command_dir / "summarize_recovered_probe_runs.bat").write_text(summary_command(root, "probe"), encoding="utf-8")


def live_command(root: Path, kind: str, mode: str) -> str:
    manifest = root / "manifests" / f"recovered_{kind}.csv"
    effort = "high" if kind == "probe" else "medium"
    output_dir = live_output_dir("algowiki_recovered", kind, mode)
    return live_command_text(f"Run live recovered {kind} {mode} with OpenAI", manifest, kind, mode, effort, output_dir)


def summary_command(root: Path, kind: str) -> str:
    manifest = root / "manifests" / f"recovered_{kind}.csv"
    return (
        "@echo off\nREM No API keys are stored in this file.\n"
        "python scripts\\datasets\\summarize_qml_discovery_runs.py "
        f"--kind {kind} --run-dir runs "
        f'--manifest "{manifest}" '
        f'--out-csv "{root}\\reports\\recovered_{kind}_run_summary.csv" '
        f'--out-md "{root}\\reports\\recovered_{kind}_run_summary.md"\n'
    )


def build_report(
    review_rows: list[dict[str, str]],
    notes: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    still_rows: list[dict[str, Any]],
    fetch_budget: FetchBudget,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "original_unresolved_count": len(review_rows),
        "recovered_context_count": len(context_rows),
        "recovered_probe_count": len(probe_rows),
        "still_unresolved_count": len(still_rows),
        "recovery_rate": len(context_rows) / max(len(review_rows), 1),
        "decision_counts": dict(sorted(Counter(str(note["reconstruction_decision"]) for note in notes).items())),
        "rule_counts": dict(Counter(str(note.get("rule_id", "")) for note in notes).most_common()),
        "domain_counts": dict(sorted(Counter(str(row.get("domain", "")) for row in context_rows).items())),
        "source_quality_distribution": dict(sorted(Counter(str(row.get("source_quality", "")) for row in context_rows).items())),
        "network_fetches_used": fetch_budget.used,
        "network_fetches_remaining": fetch_budget.remaining,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AlgorithmWiki Rich Second-Pass Enrichment Report",
        "",
        f"- Original unresolved count: {report['original_unresolved_count']}",
        f"- Recovered context count: {report['recovered_context_count']}",
        f"- Recovered probe count: {report['recovered_probe_count']}",
        f"- Still unresolved count: {report['still_unresolved_count']}",
        f"- Recovery rate: {report['recovery_rate']:.1%}",
        f"- Decision counts: {report['decision_counts']}",
        f"- Rule counts: {report['rule_counts']}",
        f"- Domain counts: {report['domain_counts']}",
        f"- Source quality distribution: {report['source_quality_distribution']}",
        f"- Network fetches used: {report['network_fetches_used']}",
        "",
        "No OpenAI calls were made. PDF bodies were not downloaded or redistributed.",
    ]
    return "\n".join(lines) + "\n"


def clear_outputs(root: Path) -> None:
    patterns = {
        "public_context_recovered": ("*.yaml",),
        "public_probe_recovered": ("*.yaml",),
        "metadata_context_recovered": ("*.meta.yaml",),
        "metadata_probe_recovered": ("*.meta.yaml",),
        "evidence_recovered": ("*.yaml",),
        "still_review_needed": ("*.yaml",),
        "manifests": ("recovered_*.csv", "recovered_*.jsonl", "still_review_needed.csv", "second_pass_manifest.json"),
    }
    for directory, globs in patterns.items():
        for pattern in globs:
            for path in (root / directory).glob(pattern):
                if path.is_file():
                    path.unlink()


def source_support_sentence(sources: list[dict[str, Any]]) -> str:
    fetched = [source for source in sources if source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched"]
    if fetched:
        title = str(fetched[0].get("title", "public metadata"))
        return f"Public metadata/source title support includes {title}."
    return "AlgorithmWiki metadata and public source-link facts support the reconstruction."


def source_bonus(sources: list[dict[str, Any]]) -> int:
    bonus = 0
    for source in sources:
        if source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched":
            bonus += 10 if source.get("reliability") == "HIGH" else 5
    return min(bonus, 20)


def source_quality(record: dict[str, Any]) -> str:
    qualities = [str(source.get("reliability", "")) for source in record.get("source_records", []) if isinstance(source, dict)]
    if "HIGH" in qualities:
        return "HIGH"
    if "MEDIUM" in qualities:
        return "MEDIUM"
    return "LOW"


def source_ids(record: dict[str, Any]) -> list[str]:
    return [str(source.get("source_id", "")) for source in record.get("source_records", []) if isinstance(source, dict)]


def has_source_type(sources: list[dict[str, Any]], source_type: str) -> bool:
    return any(source.get("source_type") == source_type and source.get("access_status") == "fetched" for source in sources)


def only_algorithm_wiki_source(sources: list[dict[str, Any]]) -> bool:
    return not any(source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched" for source in sources)


def merge_sources(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*left, *right]:
        key = str(source.get("source_id") or source.get("url") or source.get("title"))
        if key and key not in seen:
            seen.add(key)
            merged.append(source)
    return merged


def best_title_query(name: str, sources: list[dict[str, Any]]) -> str:
    for source in sources:
        title = str(source.get("title", ""))
        if title and not title.startswith(("AlgorithmWiki metadata", "HTTP Error", "robots.txt", "<urlopen")):
            return title
    return name


def should_fetch_wiki(name: str, sources: list[dict[str, Any]]) -> bool:
    lowered = name.lower()
    if has_source_type(sources, "wikipedia"):
        return False
    return len(name.split()) <= 6 and any(
        term in lowered
        for term in (
            "karatsuba",
            "rabin",
            "kadane",
            "bitap",
            "trial division",
            "quadratic sieve",
            "phong",
            "sift",
            "bakery",
            "maekawa",
            "powerset",
        )
    )


def forbidden_public_name(name: str, text: str) -> bool:
    lowered = f"{name} {text}".lower()
    return any(term in lowered for term in ("quantum", "grover", "shor", "hhl", "paperbench", "expected_primitive"))


def complexity_summary(metadata: dict[str, Any]) -> str:
    parts = []
    for label, key in (("time", "time_complexity"), ("space", "space_complexity"), ("work", "work"), ("span/depth", "span_depth")):
        value = text_value(metadata, key)
        if value:
            parts.append(f"{label} {value}")
    return "Classical complexity metadata: " + "; ".join(parts) if parts else "Classical complexity is not stated"


def rich_text(metadata: dict[str, Any], precard: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    parts = [
        text_value(metadata, "canonical_name"),
        text_value(metadata, "parameter_definitions"),
        text_value(metadata, "time_complexity"),
        text_value(metadata, "source_link"),
        text_value(precard, "public_summary"),
    ]
    for source in sources:
        parts.append(str(source.get("title", "")))
        parts.extend(str(item) for item in source.get("extracted_facts", []) if item)
    return normalize_whitespace(" ".join(parts))


def rich_record_text(record: dict[str, Any]) -> str:
    return normalize_whitespace(
        " ".join(
            str(record.get(key, ""))
            for key in (
                "canonical_name",
                "extracted_problem_statement",
                "extracted_algorithm_summary",
                "extracted_input_semantics",
                "extracted_output_semantics",
                "second_pass_rule",
            )
        )
    )


def update_last_attempt(attempts: list[dict[str, str]], source: dict[str, Any] | None) -> None:
    attempts[-1]["status"] = str(source.get("access_status", "fetched")) if source else "failed_or_not_relevant"


def attempt(query: str, method: str, status: str) -> dict[str, str]:
    return {"query": normalize_whitespace(query), "method": method, "status": status}


def first_string(value: Any) -> str:
    if isinstance(value, list) and value:
        return normalize_whitespace(str(value[0]))
    return normalize_whitespace(str(value or ""))


def strip_tags(text: str) -> str:
    return normalize_whitespace(re.sub(r"(?s)<[^>]+>", " ", text))


def quote_query(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def text_value(record: dict[str, Any], key: str) -> str:
    return normalize_whitespace(str(record.get(key, "") or ""))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_jsonl_by_id(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                data = json.loads(line)
                if isinstance(data, dict) and data.get("algorithm_id"):
                    records[str(data["algorithm_id"])] = data
    return records


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

from scripts.datasets.algowiki_audit_rich_cards import main as audit_main
from scripts.datasets.algowiki_build_rich_cards import main as build_main
from scripts.datasets.algowiki_common import PUBLIC_FIELDS, load_yaml_mapping, validate_public_mapping
from scripts.datasets.algowiki_select_rich_live_sets import write_commands


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def enriched_fixture() -> list[dict[str, object]]:
    return [
        {
            "algorithm_id": "AW-000001",
            "canonical_name": "Counting Sort",
            "original_algorithm_name": "Counting Sort",
            "source_link": "https://doi.org/10.1145/example",
            "source_link_type": "doi",
            "existing_metadata": {
                "algorithm_id": "AW-000001",
                "canonical_name": "Counting Sort",
                "blind_name": "Algorithm Wiki public task AW-000001",
                "year": "1954",
                "domain": "sorting",
                "family": "sorting",
                "variation": "",
                "problem_name": "sorting",
                "algorithm_family": "sorting",
                "time_complexity": "O(n+k)",
                "space_complexity": "O(n+k)",
                "computational_model": "RAM",
                "randomized": "0",
                "approximate": "0",
                "approximation_factor": "",
                "parameter_definitions": "n: number of keys; k: key range",
                "span_depth": "",
                "work": "",
                "number_of_processors": "",
                "source_link": "https://doi.org/10.1145/example",
                "source_link_type": "doi",
                "page_url": "",
                "page_fetch_status": "not_found",
                "page_digest": "",
                "extracted_description": "",
                "inferred_problem_statement": "Given a finite sequence of keys, return the keys in sorted order.",
                "inferred_input_model": "explicit_sequence_problem",
                "inferred_access_model": "random_access_array",
                "inferred_output_contract": "full_sequence_output",
                "inferred_size_parameters": ["n: number of keys", "k: key range"],
                "inferred_promises": [],
                "inferred_ambiguities": [],
                "quality_score": 85,
                "quality_flags": [],
                "readiness": "READY_PUBLIC_BLIND",
                "review_reasons": [],
            },
            "web_query_attempts": [{"query": "Counting Sort algorithm", "method": "fixture", "status": "fetched"}],
            "source_records": [
                {
                    "source_id": "fixture:counting-sort",
                    "url": "https://doi.org/10.1145/example",
                    "title": "Counting Sort",
                    "source_type": "doi_metadata",
                    "access_status": "fetched",
                    "reliability": "HIGH",
                    "extracted_facts": ["Counting sort sorts integer keys using counts over the key range."],
                    "short_quote": "",
                    "digest": "abc",
                }
            ],
            "extracted_problem_statement": "Counting Sort sorts integer keys by counting how many keys fall in each key value.",
            "extracted_algorithm_summary": "Counting Sort computes counts, prefix positions, and a full ordered output sequence.",
            "extracted_pseudocode_or_steps": "Count key frequencies, prefix-sum the counts, and scatter records into sorted positions.",
            "extracted_input_semantics": "A finite array of integer keys drawn from a bounded key range.",
            "extracted_output_semantics": "The same records returned in nondecreasing key order.",
            "extracted_classical_time_complexity": "O(n+k)",
            "extracted_space_complexity": "O(n+k)",
            "extracted_computation_model": "RAM",
            "extracted_bottleneck": "Counting array initialization plus writing the full ordered sequence.",
            "extracted_assumptions": [],
            "extracted_domain": "sorting",
            "extracted_family": "sorting",
            "confidence_score": 95,
            "enrichment_status": "READY_WEB_ENRICHED",
        },
        {
            "algorithm_id": "AW-000002",
            "canonical_name": "A Star Search",
            "original_algorithm_name": "A Star Search",
            "source_link": "https://example.org/a-star",
            "source_link_type": "other_public_source",
            "existing_metadata": {
                "algorithm_id": "AW-000002",
                "canonical_name": "A Star Search",
                "domain": "graph",
                "family": "graph",
                "time_complexity": "O(b^d)",
                "space_complexity": "O(b^d)",
                "computational_model": "RAM",
                "parameter_definitions": "b: branching factor; d: search depth",
                "inferred_input_model": "explicit_graph_problem",
                "inferred_access_model": "adjacency_list_query",
                "inferred_output_contract": "path_or_tree",
                "inferred_size_parameters": ["b: branching factor", "d: search depth"],
                "quality_score": 90,
                "readiness": "READY_PUBLIC_BLIND",
            },
            "web_query_attempts": [{"query": "A Star Search algorithm", "method": "fixture", "status": "fetched"}],
            "source_records": [
                {
                    "source_id": "fixture:a-star",
                    "url": "https://example.org/a-star",
                    "title": "A Star Search",
                    "source_type": "other_public_source",
                    "access_status": "fetched",
                    "reliability": "MEDIUM",
                    "extracted_facts": ["A Star Search uses a heuristic frontier to find a path to a target state."],
                    "short_quote": "",
                    "digest": "def",
                }
            ],
            "extracted_problem_statement": "A Star Search finds a path in a graph or state-space search instance.",
            "extracted_algorithm_summary": "A Star Search expands frontier states according to path cost plus a heuristic.",
            "extracted_pseudocode_or_steps": "Maintain a priority frontier, expand the lowest score state, and reconstruct a path.",
            "extracted_input_semantics": (
                "A graph or state-space instance with successor queries, start state, target predicate, and heuristic."
            ),
            "extracted_output_semantics": "A path, path cost, or predecessor tree for reaching the target state.",
            "extracted_classical_time_complexity": "O(b^d)",
            "extracted_space_complexity": "O(b^d)",
            "extracted_computation_model": "RAM",
            "extracted_bottleneck": "Frontier priority maintenance and path materialization.",
            "extracted_assumptions": [],
            "extracted_domain": "graph",
            "extracted_family": "shortest_path_search",
            "confidence_score": 90,
            "enrichment_status": "READY_WEB_ENRICHED",
        },
    ]


def test_rich_context_builder_outputs_valid_public_cards(tmp_path: Path) -> None:
    enriched = tmp_path / "enriched.jsonl"
    write_jsonl(enriched, enriched_fixture())

    assert (
        build_main(
            [
                "--enriched-jsonl",
                str(enriched),
                "--out-public-context-dir",
                str(tmp_path / "public_context"),
                "--out-metadata-context-dir",
                str(tmp_path / "metadata_context"),
                "--out-evidence-dir",
                str(tmp_path / "evidence"),
                "--out-review-needed-dir",
                str(tmp_path / "review_needed_after_web"),
                "--out-manifest",
                str(tmp_path / "manifests" / "rich_context_manifest.json"),
                "--mode",
                "context",
            ]
        )
        == 0
    )
    card = load_yaml_mapping(tmp_path / "public_context" / "AW-000001.yaml")

    assert tuple(card) == PUBLIC_FIELDS
    assert "Counting Sort" in card["statement"]
    validate_public_mapping(card, blind=False)


def test_rich_probe_builder_and_audit_outputs_valid_probe(tmp_path: Path) -> None:
    enriched = tmp_path / "enriched.jsonl"
    write_jsonl(enriched, enriched_fixture())

    assert (
        build_main(
            [
                "--enriched-jsonl",
                str(enriched),
                "--out-public-probe-dir",
                str(tmp_path / "public_probe"),
                "--out-metadata-probe-dir",
                str(tmp_path / "metadata_probe"),
                "--out-evidence-dir",
                str(tmp_path / "evidence"),
                "--out-manifest",
                str(tmp_path / "manifests" / "rich_probe_manifest.json"),
                "--mode",
                "probe",
            ]
        )
        == 0
    )

    probe_paths = sorted((tmp_path / "public_probe").glob("*.yaml"))
    assert probe_paths
    probe = load_yaml_mapping(probe_paths[0])
    assert tuple(probe) == PUBLIC_FIELDS
    assert "not an end-to-end" in probe["statement"]
    validate_public_mapping(probe, blind=False)
    assert (
        audit_main(
            [
                "--public-dir",
                str(tmp_path / "public_probe"),
                "--metadata-dir",
                str(tmp_path / "metadata_probe"),
                "--kind",
                "probe",
                "--out-jsonl",
                str(tmp_path / "audit" / "probe.jsonl"),
                "--out-csv",
                str(tmp_path / "audit" / "probe.csv"),
                "--out-md",
                str(tmp_path / "audit" / "probe.md"),
            ]
        )
        == 0
    )


def test_live_probe_command_uses_named_path_column_not_third_csv_token(tmp_path: Path) -> None:
    root = tmp_path / "rich"
    manifest_dir = root / "manifests"
    manifest_dir.mkdir(parents=True)
    probe_card = root / "public_probe" / "AW-000001.probe.yaml"
    probe_card.parent.mkdir(parents=True)
    probe_card.write_text("id: AW-000001.probe\n", encoding="utf-8")
    (manifest_dir / "ready_public_probe.csv").write_text(
        "\n".join(
            [
                "probe_id,parent_algorithm_id,parent_algorithm_name,public_probe_path",
                f"AW-000001.probe,AW-000001,Melhorn's Approximation algorithm,{probe_card}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "ready_public_context.csv").write_text(
        "algorithm_id,algorithm_name,public_context_path\nAW-000001,Placeholder,path.yaml\n",
        encoding="utf-8",
    )

    write_commands(root)

    command = (root / "commands" / "run_live_probe_first_50_openai.bat").read_text(encoding="utf-8")
    assert "Import-Csv" in command
    assert "public_probe_path" in command
    assert "tokens=3 delims=," not in command
    assert "Melhorn's Approximation algorithm" not in command

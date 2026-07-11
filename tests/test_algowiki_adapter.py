from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml
from pytest import MonkeyPatch

from quantummindlite.models import ProblemCard
from scripts.datasets.algowiki_common import PUBLIC_FIELDS, leakage_matches, load_yaml_mapping, validate_public_mapping
from scripts.datasets.algowiki_ingest import ingest_csv, resolve_csv_path
from scripts.datasets.algowiki_ingest import main as ingest_main
from scripts.datasets.algowiki_to_cards import main as cards_main
from scripts.datasets.algowiki_validate_cards import main as validate_main

HEADER = (
    "Name",
    "Year",
    "Time Complexity",
    "Space Complexity",
    "Computational Model",
    "Randomized",
    "Randomized Type",
    "Approximate",
    "Approximation Factor",
    "Parameter Definitions",
    "Span Depth",
    "Work",
    "Number Of Processors",
    "Link",
)


def fixture_rows() -> list[tuple[str, ...]]:
    return [
        (
            "Counting Sort",
            "1954",
            "O(n+k)",
            "O(n+k)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = number of keys; k = key range",
            "",
            "",
            "",
            "https://doi.org/10.1145/example",
        ),
        (
            "Counting Sort",
            "1954",
            "O(n+k)",
            "O(n+k)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = number of keys; k = key range",
            "",
            "",
            "",
            "https://doi.org/10.1145/example-duplicate",
        ),
        (
            "Kruskal Algorithm",
            "1956",
            "O(m log n)",
            "O(n+m)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = vertices; m = edges",
            "",
            "",
            "",
            "https://dl.acm.org/doi/10.1145/example",
        ),
        (
            "Strassen Matrix Product",
            "1969",
            "O(n^2.807)",
            "O(n^2)",
            "Arithmetic RAM",
            "No",
            "",
            "No",
            "",
            "n = matrix dimension",
            "",
            "",
            "",
            "https://arxiv.org/abs/0000000",
        ),
        (
            "Adaptive Simpson Approximation",
            "1962",
            "O(t)",
            "O(t)",
            "Real RAM",
            "No",
            "",
            "Yes",
            "epsilon",
            "t = function evaluations; epsilon = requested tolerance",
            "",
            "",
            "",
            "https://example.org/simpson.pdf",
        ),
        (
            "Mystery Method",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ),
    ]


def write_csv(path: Path, rows: Sequence[tuple[str, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(HEADER)
        writer.writerows(rows)


def generate_cards(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    csv_path = tmp_path / "algowiki.csv"
    normalized = tmp_path / "normalized" / "algowiki_records.jsonl"
    ingest_manifest = tmp_path / "manifests" / "ingest.json"
    metadata = tmp_path / "metadata"
    precards = tmp_path / "precards"
    cards = tmp_path / "cards"
    public_blind = tmp_path / "public_blind"
    public_named = tmp_path / "public_named"
    cards_manifest = tmp_path / "manifests" / "cards.json"
    write_csv(csv_path, fixture_rows())
    assert ingest_main(["--csv", str(csv_path), "--out-normalized", str(normalized), "--out-manifest", str(ingest_manifest)]) == 0
    assert (
        cards_main(
            [
                "--records",
                str(normalized),
                "--out-metadata-dir",
                str(metadata),
                "--out-precard-dir",
                str(precards),
                "--out-card-dir",
                str(cards),
                "--out-public-blind-dir",
                str(public_blind),
                "--out-public-named-dir",
                str(public_named),
                "--out-manifest",
                str(cards_manifest),
            ]
        )
        == 0
    )
    return metadata, precards, cards, public_blind, public_named


def test_semicolon_csv_parse_preserves_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "algowiki.csv"
    write_csv(csv_path, fixture_rows())

    records, manifest = ingest_csv(csv_path)

    assert len(records) == 6
    assert manifest["columns"] == list(HEADER)
    assert records[0].algorithm_id == "AW-000001"
    assert records[0].time_complexity == "O(n+k)"


def test_1901_row_like_ingestion_manifest_counts_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "algowiki_1901.csv"
    rows = [
        (
            f"Fixture Sort {index}",
            "2026",
            "O(n log n)",
            "O(n)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = number of items",
            "",
            "",
            "",
            "",
        )
        for index in range(1901)
    ]
    write_csv(csv_path, rows)

    records, manifest = ingest_csv(csv_path)

    assert len(records) == 1901
    assert manifest["row_count"] == 1901
    assert manifest["unique_name_count"] == 1901


def test_duplicate_names_are_detected(tmp_path: Path) -> None:
    csv_path = tmp_path / "algowiki.csv"
    write_csv(csv_path, fixture_rows())

    _, manifest = ingest_csv(csv_path)

    assert "counting sort" in manifest["duplicate_names"]
    assert len(manifest["duplicate_names"]["counting sort"]) == 2


def test_csv_resolution_prefers_raw_primary_source(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    raw_csv = tmp_path / "corpus" / "algorithm_wiki" / "raw" / "algowiki-dataset-export.csv"
    raw_csv.parent.mkdir(parents=True)
    write_csv(raw_csv, fixture_rows())

    resolved, source = resolve_csv_path(Path("algowiki-dataset-export.csv"))

    assert resolved == Path("corpus/algorithm_wiki/raw/algowiki-dataset-export.csv")
    assert source["source_kind"] == "primary_raw"
    assert source["recommended_corpus_slug"] == "algowiki1901_v1"


def test_public_blind_card_has_exactly_seven_fields(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    data = load_yaml_mapping(public_blind / "AW-000001.yaml")

    assert tuple(data) == PUBLIC_FIELDS
    validate_public_mapping(data, canonical_name="Counting Sort", blind=True)


def test_metadata_contains_source_name_year_link_but_public_blind_does_not(tmp_path: Path) -> None:
    metadata, _, _, public_blind, _ = generate_cards(tmp_path)
    meta = load_yaml_mapping(metadata / "AW-000001.meta.yaml")
    public_text = yaml.safe_dump(load_yaml_mapping(public_blind / "AW-000001.yaml"))

    assert meta["canonical_name"] == "Counting Sort"
    assert meta["year"] == "1954"
    assert meta["source_link"] == "https://doi.org/10.1145/example"
    assert "Counting Sort" not in public_text
    assert "1954" not in public_text
    assert "doi.org" not in public_text


def test_sorting_row_maps_to_sequence_full_output_card(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    data = load_yaml_mapping(public_blind / "AW-000001.yaml")

    assert data["input_model"] == "explicit_sequence_problem"
    assert data["access_model"] == "random_access_array"
    assert data["output_contract"] == "full_sequence_output"


def test_mst_row_maps_to_graph_tree_output_card(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    data = load_yaml_mapping(public_blind / "AW-000003.yaml")

    assert data["input_model"] == "explicit_graph_problem"
    assert data["access_model"] == "edge_list_input"
    assert data["output_contract"] == "path_or_tree"


def test_matrix_product_row_maps_to_matrix_full_classical_card(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    data = load_yaml_mapping(public_blind / "AW-000004.yaml")

    assert data["input_model"] == "explicit_matrix_problem"
    assert data["access_model"] == "dense_matrix_access"
    assert data["output_contract"] == "full_classical_output"


def test_numerical_approximation_maps_to_approximation_solution(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    data = load_yaml_mapping(public_blind / "AW-000005.yaml")

    assert data["input_model"] == "explicit_numerical_problem"
    assert data["access_model"] == "function_evaluation_oracle_classical"
    assert data["output_contract"] in {"estimate", "approximation_solution"}


def test_low_information_row_creates_precard_but_no_ready_public_card(tmp_path: Path) -> None:
    metadata, precards, _, public_blind, public_named = generate_cards(tmp_path)

    assert (precards / "AW-000006.precard.yaml").exists()
    assert (metadata / "AW-000006.meta.yaml").exists()
    assert not (public_blind / "AW-000006.yaml").exists()
    assert not (public_named / "AW-000006.yaml").exists()
    assert load_yaml_mapping(metadata / "AW-000006.meta.yaml")["readiness"] == "INSUFFICIENT_INFORMATION"


def test_duplicate_blind_digests_are_suppressed_and_reviewed(tmp_path: Path) -> None:
    csv_path = tmp_path / "algowiki.csv"
    normalized = tmp_path / "normalized" / "algowiki_records.jsonl"
    ingest_manifest = tmp_path / "manifests" / "ingest.json"
    metadata = tmp_path / "metadata"
    precards = tmp_path / "precards"
    cards = tmp_path / "cards"
    public_blind = tmp_path / "public_blind"
    public_named = tmp_path / "public_named"
    review_needed = tmp_path / "review_needed"
    cards_manifest = tmp_path / "manifests" / "cards.json"
    duplicate_rows = [
        (
            "Intro Sort",
            "1997",
            "O(n log n)",
            "O(log n)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = number of items",
            "",
            "",
            "",
            "https://example.org/intro",
        ),
        (
            "Heap Sort Variant",
            "1964",
            "O(n log n)",
            "O(log n)",
            "RAM",
            "No",
            "",
            "No",
            "",
            "n = number of items",
            "",
            "",
            "",
            "https://example.org/heap",
        ),
    ]
    write_csv(csv_path, duplicate_rows)
    assert ingest_main(["--csv", str(csv_path), "--out-normalized", str(normalized), "--out-manifest", str(ingest_manifest)]) == 0
    assert (
        cards_main(
            [
                "--records",
                str(normalized),
                "--out-metadata-dir",
                str(metadata),
                "--out-precard-dir",
                str(precards),
                "--out-card-dir",
                str(cards),
                "--out-public-blind-dir",
                str(public_blind),
                "--out-public-named-dir",
                str(public_named),
                "--out-review-needed-dir",
                str(review_needed),
                "--out-manifest",
                str(cards_manifest),
            ]
        )
        == 0
    )

    manifest = json.loads(cards_manifest.read_text(encoding="utf-8"))

    assert len(list(public_blind.glob("AW-*.yaml"))) == 1
    assert len(list(public_named.glob("AW-*.yaml"))) == 2
    assert (review_needed / "AW-000002.review.yaml").exists()
    assert load_yaml_mapping(metadata / "AW-000002.meta.yaml")["readiness"] == "DUPLICATE_VARIANT"
    assert manifest["duplicate_public_blind_digest_group_count"] == 1
    assert manifest["largest_duplicate_public_blind_digest_group_size"] == 2


def test_validation_rejects_duplicate_public_blind_digest(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    metadata_dir = tmp_path / "metadata"
    duplicate_path = public_blind / "AW-009999.yaml"
    duplicate_path.write_text((public_blind / "AW-000001.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    meta = load_yaml_mapping(metadata_dir / "AW-000001.meta.yaml")
    meta["algorithm_id"] = "AW-009999"
    meta["canonical_name"] = "Synthetic Duplicate Sort"
    with (metadata_dir / "AW-009999.meta.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(meta, handle, sort_keys=False)

    result = validate_main(
        [
            "--public-dir",
            str(public_blind),
            "--metadata-dir",
            str(metadata_dir),
            "--min-ready",
            "1",
            "--sample-mock-analyze",
            "0",
            "--out-report",
            str(tmp_path / "validation.json"),
        ]
    )

    assert result == 1
    report = json.loads((tmp_path / "validation.json").read_text(encoding="utf-8"))
    assert report["duplicate_digest_group_count"] == 1


def test_leakage_scanner_catches_forbidden_terms() -> None:
    text = "quantum Grover Shor HHL QFT amplitude amplification expected_primitive PaperBench QM-PB hidden"

    matches = set(leakage_matches(text))

    assert {"quantum", "grover", "shor", "hhl", "qft", "amplitude amplification", "expected_primitive"} <= matches
    assert {"paperbench", "qm-pb", "hidden"} <= matches


def test_generated_public_card_can_be_analyzed_with_mock_provider(tmp_path: Path) -> None:
    _, _, _, public_blind, _ = generate_cards(tmp_path)
    card_path = public_blind / "AW-000001.yaml"
    data = load_yaml_mapping(card_path)
    ProblemCard.model_validate(data)

    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else src_path + os.pathsep + str(env["PYTHONPATH"])
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantummindlite.cli",
            "analyze",
            "--input",
            str(card_path),
            "--provider",
            "mock",
            "--output-dir",
            str(tmp_path / "runs"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr

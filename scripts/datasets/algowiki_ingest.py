from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    AlgorithmWikiRawRecord,
    canonicalize_name,
    infer_source_link_type,
    normalize_whitespace,
    short_sha256,
    write_jsonl,
)

FIELD_ALIASES = {
    "name": ("algorithm", "algorithm_name", "name", "title"),
    "year": ("year", "publication_year"),
    "time_complexity": ("time_complexity", "time", "running_time", "runtime", "work_time"),
    "space_complexity": ("space_complexity", "space", "memory", "memory_complexity"),
    "computational_model": ("computational_model", "model", "computation_model"),
    "randomized": ("randomized", "randomised", "is_randomized", "random"),
    "randomized_type": ("randomized_type", "randomised_type", "type_of_randomization"),
    "approximate": ("approximate", "approximation", "is_approximate", "approx"),
    "approximation_factor": ("approximation_factor", "approximation_ratio", "approx_factor"),
    "parameter_definitions": ("parameter_definitions", "parameters", "parameter_definition", "parameter"),
    "span_depth": ("span_depth", "span", "depth", "parallel_depth"),
    "work": ("work", "parallel_work"),
    "number_of_processors": ("number_of_processors", "processors", "number_processors", "processor_count"),
    "link": ("link", "literature_link", "url", "source_link", "paper_link", "reference"),
}

PRIMARY_CSV_CANDIDATES = (
    Path("algowiki-dataset-export.csv"),
    Path("corpus/algorithm_wiki/raw/algowiki-dataset-export.csv"),
)
FALLBACK_PUBLIC_EXPORT = Path("corpus/algorithm_wiki/raw/algowiki_public_download_extract.csv")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest an Algorithm Wiki semicolon-delimited CSV export.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-normalized", required=True)
    parser.add_argument("--out-manifest", required=True)
    args = parser.parse_args(argv)

    csv_path, source_selection = resolve_csv_path(Path(args.csv))
    records, manifest = ingest_csv(csv_path, source_selection)
    write_jsonl(Path(args.out_normalized), [record.to_dict() for record in records])
    out_manifest = Path(args.out_manifest)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def resolve_csv_path(requested: Path) -> tuple[Path, dict[str, str]]:
    requested_text = str(requested).replace("\\", "/").lower()
    for index, candidate in enumerate(PRIMARY_CSV_CANDIDATES):
        candidate_text = str(candidate).replace("\\", "/").lower()
        if requested_text == candidate_text and candidate.exists():
            kind = "primary_root" if index == 0 else "primary_raw"
            return candidate, source_selection(kind, candidate, "algowiki1901_v1", "")
    if str(requested).lower() in {"auto", "algowiki-dataset-export.csv"}:
        for index, candidate in enumerate(PRIMARY_CSV_CANDIDATES):
            if candidate.exists():
                kind = "primary_root" if index == 0 else "primary_raw"
                return candidate, source_selection(kind, candidate, "algowiki1901_v1", "")
        if FALLBACK_PUBLIC_EXPORT.exists():
            limitation = (
                "Primary algowiki-dataset-export.csv was not found; using the fallback public "
                "Algorithm Wiki /download extract. Name the output algowiki1870_v1 and treat "
                "row counts as fallback-source counts, not the full 1901 export."
            )
            return FALLBACK_PUBLIC_EXPORT, source_selection(
                "fallback_public_download_extract", FALLBACK_PUBLIC_EXPORT, "algowiki1870_v1", limitation
            )
    if requested.exists():
        return requested, source_selection("explicit_path", requested, "custom", "")
    raise FileNotFoundError(f"Algorithm Wiki CSV source not found: {requested}")


def source_selection(kind: str, path: Path, corpus_slug: str, limitation: str) -> dict[str, str]:
    return {
        "source_kind": kind,
        "resolved_csv": str(path),
        "recommended_corpus_slug": corpus_slug,
        "limitation": limitation,
    }


def ingest_csv(path: Path, source_selection_info: dict[str, str] | None = None) -> tuple[list[AlgorithmWikiRawRecord], dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        columns = [str(column) for column in (reader.fieldnames or [])]
        normalized_columns = {column: normalize_field_name(column) for column in columns}
        rows = [normalize_row(row, columns) for row in reader]

    alias_lookup = build_alias_lookup(columns)
    records: list[AlgorithmWikiRawRecord] = []
    canonical_to_records: dict[str, list[dict[str, str]]] = defaultdict(list)
    missingness: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    link_counts: Counter[str] = Counter()
    for row_index, row in enumerate(rows, start=1):
        values = {field: row_value(row, alias_lookup, field) for field in FIELD_ALIASES}
        for column in columns:
            if not row.get(column, "").strip():
                missingness[column] += 1
        algorithm_id = f"AW-{row_index:06d}"
        raw_digest = short_sha256({column: row.get(column, "") for column in columns})
        record = AlgorithmWikiRawRecord(
            algorithm_id=algorithm_id,
            name=values["name"],
            year=values["year"],
            time_complexity=values["time_complexity"],
            space_complexity=values["space_complexity"],
            computational_model=values["computational_model"],
            randomized=values["randomized"],
            randomized_type=values["randomized_type"],
            approximate=values["approximate"],
            approximation_factor=values["approximation_factor"],
            parameter_definitions=values["parameter_definitions"],
            span_depth=values["span_depth"],
            work=values["work"],
            number_of_processors=values["number_of_processors"],
            link=values["link"],
            row_index=row_index,
            raw_digest=raw_digest,
        )
        records.append(record)
        canonical = canonicalize_name(record.name)
        if canonical:
            canonical_to_records[canonical].append({"algorithm_id": algorithm_id, "name": record.name})
        model_counts[record.computational_model or "unknown"] += 1
        link_counts[infer_source_link_type(record.link)] += 1

    duplicate_names = {name: items for name, items in sorted(canonical_to_records.items()) if len(items) > 1}
    source_info = dict(source_selection_info or source_selection("explicit_path", path, "custom", ""))
    limitations = [source_info["limitation"]] if source_info.get("limitation") else []
    if source_info.get("recommended_corpus_slug") == "algowiki1901_v1" and len(records) != 1901:
        limitations.append(f"Primary Algorithm Wiki export row_count is {len(records)}, not 1901; report the actual row count honestly.")
    manifest: dict[str, Any] = {
        "input_csv_path": str(path),
        "source_selection": source_info,
        "source_limitations": limitations,
        "row_count": len(records),
        "unique_name_count": len(canonical_to_records),
        "columns": columns,
        "normalized_columns": normalized_columns,
        "missingness": {column: missingness[column] for column in columns},
        "computational_model_counts": dict(sorted(model_counts.items())),
        "link_counts": dict(sorted(link_counts.items())),
        "duplicate_names": duplicate_names,
    }
    return records, manifest


def normalize_field_name(value: str) -> str:
    lowered = value.strip().lower().replace("&", " and ")
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", lowered)).strip("_")


def normalize_row(row: dict[str | None, str | None], columns: list[str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for column in columns:
        normalized[column] = normalize_whitespace(str(row.get(column) or ""))
    return normalized


def build_alias_lookup(columns: list[str]) -> dict[str, str]:
    normalized_to_original = {normalize_field_name(column): column for column in columns}
    lookup: dict[str, str] = {}
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized_to_original:
                lookup[field_name] = normalized_to_original[alias]
                break
    return lookup


def row_value(row: dict[str, str], alias_lookup: dict[str, str], field_name: str) -> str:
    column = alias_lookup.get(field_name)
    if column is None:
        return ""
    return row.get(column, "")


if __name__ == "__main__":
    raise SystemExit(main())

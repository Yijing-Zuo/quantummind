from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import load_yaml_mapping, metadata_from_mapping  # noqa: E402

QUOTAS = {
    "sorting_comparison": 5,
    "graph": 8,
    "matrix_numerical": 8,
    "data_structures": 5,
    "string_combinatorial_geometry": 8,
    "randomized_approximation": 5,
    "parallel_work_span": 5,
}

BASELINE10_IDS = (
    "AW-000142",
    "AW-000029",
    "AW-000198",
    "AW-000182",
    "AW-000038",
    "AW-000549",
    "AW-000976",
    "AW-000016",
    "AW-000907",
    "AW-001045",
)

PREFERRED_IDS = (
    *BASELINE10_IDS,
    "AW-000028",
    "AW-000145",
    "AW-000149",
    "AW-000201",
    "AW-000197",
    "AW-000214",
    "AW-000215",
    "AW-000183",
    "AW-000213",
    "AW-000079",
    "AW-000080",
    "AW-000092",
    "AW-000556",
    "AW-000039",
    "AW-000041",
    "AW-000065",
    "AW-000255",
    "AW-000515",
    "AW-000550",
    "AW-000977",
    "AW-000978",
    "AW-000979",
    "AW-000980",
    "AW-000714",
    "AW-000842",
    "AW-000427",
    "AW-000867",
    "AW-000904",
    "AW-000905",
    "AW-000906",
    "AW-000908",
    "AW-001188",
    "AW-001189",
    "AW-001128",
    "AW-001397",
    "AW-001407",
    "AW-001012",
    "AW-001013",
    "AW-001020",
    "AW-001039",
    "AW-001040",
    "AW-001133",
    "AW-001225",
)

PILOT_EXCLUDED_IDS = {
    "AW-000060",  # MST/demand-sorting metadata is not safe as a blind sorting card.
    "AW-001189",  # Regular-sampling row is too underspecified after CSV-only inference.
    "AW-001397",  # Randomized row reads as a theorem-level entry without enough I/O semantics.
}


@dataclass(frozen=True)
class SourceDirs:
    metadata: Path
    precards: Path
    public_blind: Path
    public_named: Path
    cards: Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select a balanced Algorithm Wiki pilot set.")
    parser.add_argument("--metadata-dir", required=True)
    parser.add_argument("--precard-dir", required=True)
    parser.add_argument("--public-blind-dir", required=True)
    parser.add_argument("--public-named-dir", required=True)
    parser.add_argument("--card-dir", default="corpus/algorithm_wiki/cards_all_preview")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--target", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260627)
    args = parser.parse_args(argv)

    source = SourceDirs(
        metadata=Path(args.metadata_dir),
        precards=Path(args.precard_dir),
        public_blind=Path(args.public_blind_dir),
        public_named=Path(args.public_named_dir),
        cards=Path(args.card_dir),
    )
    target = int(args.target)
    rows = load_candidate_rows(source)
    selected = select_pilot(rows, target, int(args.seed))
    if len(selected) != target:
        raise RuntimeError(f"selected {len(selected)} records, expected {target}")
    validation = validate_selection(selected, target)
    if validation["errors"]:
        raise RuntimeError("selection constraints failed: " + "; ".join(validation["errors"]))
    out_root = Path(args.out_root)
    write_selection(source, out_root, selected)
    manifest = build_manifest(selected, rows, validation, int(args.seed))
    out_manifest = out_root / "manifests" / "pilot50_selection_manifest.json"
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def load_candidate_rows(source: SourceDirs) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(source.metadata.glob("AW-*.meta.yaml")):
        metadata = metadata_from_mapping(load_yaml_mapping(metadata_path))
        if metadata.algorithm_id in PILOT_EXCLUDED_IDS:
            continue
        blind_path = source.public_blind / f"{metadata.algorithm_id}.yaml"
        named_path = source.public_named / f"{metadata.algorithm_id}.yaml"
        if metadata.readiness != "READY_PUBLIC_BLIND" or not blind_path.exists() or not has_source_link(metadata.source_link):
            continue
        row = metadata.to_dict()
        row["blind_path"] = str(blind_path)
        row["named_path"] = str(named_path)
        row["category_tags"] = category_tags(row)
        row["search_text"] = search_text(row)
        row["name_quality"] = name_quality(str(row["canonical_name"]))
        row["has_complexity"] = bool(row.get("time_complexity") or row.get("work") or row.get("span_depth"))
        rows.append(row)
    return rows


def select_pilot(rows: list[dict[str, Any]], target: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows_by_id = {str(row["algorithm_id"]): row for row in rows}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for algorithm_id in PREFERRED_IDS:
        row = rows_by_id.get(algorithm_id)
        if row and can_add(row, selected, target) and algorithm_id not in selected_ids:
            selected.append(row)
            selected_ids.add(algorithm_id)
        if len(selected) >= target:
            break

    while len(selected) < target:
        deficits = quota_deficits(selected)
        if deficits:
            category = max(deficits, key=lambda item: (deficits[item], QUOTAS[item]))
            pool = [row for row in rows if category in row["category_tags"] and str(row["algorithm_id"]) not in selected_ids]
        else:
            pool = [row for row in rows if str(row["algorithm_id"]) not in selected_ids]
        pool = [row for row in pool if can_add(row, selected, target)]
        if not pool:
            raise RuntimeError("no eligible rows remain for pilot selection")
        rng.shuffle(pool)
        row = min(pool, key=rank_row)
        selected.append(row)
        selected_ids.add(str(row["algorithm_id"]))

    return selected


def can_add(row: dict[str, Any], selected: list[dict[str, Any]], target: int) -> bool:
    max_domain = int(target * 0.3)
    domain_counts = Counter(str(item["domain"]) for item in selected)
    return domain_counts[str(row["domain"])] < max_domain


def quota_deficits(selected: list[dict[str, Any]]) -> dict[str, int]:
    counts = category_counts(selected)
    return {category: minimum - counts.get(category, 0) for category, minimum in QUOTAS.items() if counts.get(category, 0) < minimum}


def validate_selection(selected: list[dict[str, Any]], target: int) -> dict[str, Any]:
    errors: list[str] = []
    counts = category_counts(selected)
    for category, minimum in QUOTAS.items():
        if counts.get(category, 0) < minimum:
            errors.append(f"{category} count {counts.get(category, 0)} below {minimum}")
    domain_counts = Counter(str(row["domain"]) for row in selected)
    max_domain = int(target * 0.3)
    for domain, count in domain_counts.items():
        if count > max_domain:
            errors.append(f"{domain} count {count} exceeds max {max_domain}")
    return {"category_counts": dict(sorted(counts.items())), "domain_counts": dict(sorted(domain_counts.items())), "errors": errors}


def category_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(str(tag) for tag in row["category_tags"])
    return counts


def category_tags(row: dict[str, Any]) -> list[str]:
    domain = str(row["domain"])
    text = search_text(row)
    tags: list[str] = []
    if domain == "sorting" and any(term in text for term in ("sort", "merge", "heap", "quick", "comparison")):
        tags.append("sorting_comparison")
    if domain == "graph":
        tags.append("graph")
    if domain in {"matrix_linear_algebra", "numerical_analysis"}:
        tags.append("matrix_numerical")
    if domain == "data_structures" or is_data_structure_or_query(text):
        tags.append("data_structures")
    if domain in {"string", "combinatorics", "computational_geometry"}:
        tags.append("string_combinatorial_geometry")
    if (
        domain == "randomized_sampling"
        or truthy(str(row.get("randomized", "")))
        or truthy(str(row.get("approximate", "")))
        or any(term in text for term in ("random", "approx", "sampling", "sample", "monte carlo"))
    ):
        tags.append("randomized_approximation")
    if row.get("work") or row.get("span_depth") or row.get("number_of_processors") or domain == "parallel_algorithms":
        tags.append("parallel_work_span")
    return sorted(set(tags))


def is_data_structure_or_query(text: str) -> bool:
    terms = (
        "tree",
        "heap",
        "treap",
        "trie",
        "hash",
        "sketch",
        "hyperloglog",
        "query",
        "range",
        "static tree",
        "dynamic",
        "search",
        "dictionary",
        "priority queue",
        "fibonacci heap",
        "binary heap",
    )
    return any(term in text for term in terms)


def search_text(row: dict[str, Any]) -> str:
    keys = (
        "canonical_name",
        "domain",
        "family",
        "variation",
        "problem_name",
        "algorithm_family",
        "time_complexity",
        "space_complexity",
        "computational_model",
        "parameter_definitions",
        "work",
        "span_depth",
        "number_of_processors",
        "inferred_problem_statement",
    )
    return " ".join(str(row.get(key, "")) for key in keys).lower()


def rank_row(row: dict[str, Any]) -> tuple[int, int, int, int, str]:
    return (
        -int(row["algorithm_id"] in BASELINE10_IDS),
        -int(row["name_quality"]),
        -int(row["has_complexity"]),
        -int(row.get("quality_score", 0)),
        str(row["algorithm_id"]),
    )


def name_quality(name: str) -> bool:
    lowered = name.lower()
    if any(term in lowered for term in ("algorithm", "sort", "tree", "heap", "search", "sampling", "hull", "strassen", "kruskal")):
        return True
    return any(term in lowered for term in ("dijkstra", "tarjan", "hyperloglog", "scapegoat", "gibbs", "convex", "matrix"))


def has_source_link(value: str) -> bool:
    cleaned = value.strip().lower()
    return bool(cleaned and cleaned not in {"-", "unknown", "none", "n/a"})


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "randomized", "approximate", "approx"}


def write_selection(source: SourceDirs, out_root: Path, selected: list[dict[str, Any]]) -> None:
    for subdir in ("public_blind", "public_named", "metadata", "precards", "cards", "reports", "manifests"):
        directory = out_root / subdir
        directory.mkdir(parents=True, exist_ok=True)
        for child in directory.glob("AW-*.yaml"):
            child.unlink()
        for child in directory.glob("*.json"):
            child.unlink()
    for row in selected:
        algorithm_id = str(row["algorithm_id"])
        copy_if_exists(source.public_blind / f"{algorithm_id}.yaml", out_root / "public_blind" / f"{algorithm_id}.yaml")
        copy_if_exists(source.public_named / f"{algorithm_id}.yaml", out_root / "public_named" / f"{algorithm_id}.yaml")
        copy_if_exists(source.metadata / f"{algorithm_id}.meta.yaml", out_root / "metadata" / f"{algorithm_id}.meta.yaml")
        copy_if_exists(source.precards / f"{algorithm_id}.precard.yaml", out_root / "precards" / f"{algorithm_id}.precard.yaml")
        copy_if_exists(source.cards / f"{algorithm_id}.audit.yaml", out_root / "cards" / f"{algorithm_id}.audit.yaml")


def copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build_manifest(
    selected: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    validation: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "seed": seed,
        "target": len(selected),
        "candidate_count": len(rows),
        "selected_count": len(selected),
        "category_counts": validation["category_counts"],
        "domain_counts": validation["domain_counts"],
        "errors": validation["errors"],
        "selected": [
            {
                "algorithm_id": str(row["algorithm_id"]),
                "canonical_name": str(row["canonical_name"]),
                "domain": str(row["domain"]),
                "category_tags": list(row["category_tags"]),
                "source_link": str(row["source_link"]),
                "quality_score": int(row["quality_score"]),
            }
            for row in selected
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())

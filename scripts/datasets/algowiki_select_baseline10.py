from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    load_yaml_mapping,
    metadata_from_mapping,
)

CATEGORIES = (
    ("comparison_sorting", ("sorting",), ("merge", "heap", "quick", "shell"), ("quick sort", "heap sort", "shell sort")),
    ("noncomparison_sorting_or_selection", ("sorting",), ("counting", "radix", "bucket", "selection"), ("counting sort", "radix sort")),
    ("minimum_spanning_tree_graph", ("graph",), ("minimum spanning", "mst", "kruskal", "prim", "boruvka"), ("kruskal's algorithm", "prim")),
    ("connectivity_or_scc_graph", ("graph",), ("strongly connected", "connected component", "connectivity"), ("tarjan",)),
    ("matrix_product", ("matrix_linear_algebra",), ("matrix", "product", "multiplication", "strassen"), ("strassen",)),
    ("numerical_analysis", ("numerical_analysis",), ("approximation", "hyperloglog", "newton", "iteration"), ("hyperloglog",)),
    ("data_structure_query", ("data_structures",), ("tree", "treap", "hash", "priority queue"), ("scapegoat tree", "treap", "avl tree")),
    ("randomized_or_approximate", ("randomized_sampling", "optimization", "sorting"), ("random", "gibbs", "sample"), ("gibbs sampling",)),
    (
        "geometry_or_combinatorics",
        ("computational_geometry", "combinatorics"),
        ("convex", "geometric", "hull"),
        ("convex hull", "quickhull"),
    ),
    (
        "parallel_work_span",
        ("parallel_algorithms", "sorting"),
        ("parallel", "pram", "span", "work", "processor"),
        ("ajtai", "aks", "bitonic"),
    ),
)

PREFERRED_IDS = {
    "comparison_sorting": ("AW-000142", "AW-000028"),
    "noncomparison_sorting_or_selection": ("AW-000029",),
    "minimum_spanning_tree_graph": ("AW-000198",),
    "connectivity_or_scc_graph": ("AW-000182",),
    "matrix_product": ("AW-000038",),
    "numerical_analysis": ("AW-000549",),
    "data_structure_query": ("AW-000976",),
    "randomized_or_approximate": ("AW-000016",),
    "geometry_or_combinatorics": ("AW-000907",),
    "parallel_work_span": ("AW-001045",),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select a balanced high-confidence Algorithm Wiki baseline10 subset.")
    parser.add_argument("--metadata-dir", default="corpus/algorithm_wiki/metadata_all_preview")
    parser.add_argument("--precard-dir", default="corpus/algorithm_wiki/precards_all_preview")
    parser.add_argument("--card-dir", default="corpus/algorithm_wiki/cards_all_preview")
    parser.add_argument("--public-blind-dir", default="corpus/algorithm_wiki/public_blind_preview")
    parser.add_argument("--public-named-dir", default="corpus/algorithm_wiki/public_named_preview")
    parser.add_argument("--out-root", default="corpus/algorithm_wiki/baseline10")
    parser.add_argument("--out-manifest", default="corpus/algorithm_wiki/baseline10/manifests/baseline10_selection_manifest.json")
    args = parser.parse_args(argv)

    source = SourceDirs(
        metadata=Path(args.metadata_dir),
        precards=Path(args.precard_dir),
        cards=Path(args.card_dir),
        public_blind=Path(args.public_blind_dir),
        public_named=Path(args.public_named_dir),
    )
    out_root = Path(args.out_root)
    rows = load_rows(source)
    selected = select_rows(rows)
    if len(selected) != 10:
        raise RuntimeError(f"selected {len(selected)} rows, expected 10")
    write_selection(source, out_root, selected)
    manifest = build_manifest(selected, rows)
    out_manifest = Path(args.out_manifest)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


class SourceDirs:
    def __init__(self, metadata: Path, precards: Path, cards: Path, public_blind: Path, public_named: Path) -> None:
        self.metadata = metadata
        self.precards = precards
        self.cards = cards
        self.public_blind = public_blind
        self.public_named = public_named


def load_rows(source: SourceDirs) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(source.metadata.glob("AW-*.meta.yaml")):
        metadata = metadata_from_mapping(load_yaml_mapping(metadata_path))
        blind_path = source.public_blind / f"{metadata.algorithm_id}.yaml"
        named_path = source.public_named / f"{metadata.algorithm_id}.yaml"
        if not blind_path.exists():
            continue
        row = metadata.to_dict()
        row["blind_path"] = blind_path
        row["named_path"] = named_path
        row["source_link_present"] = has_source_link(metadata.source_link)
        row["has_complexity"] = bool(metadata.time_complexity or metadata.work or metadata.span_depth)
        row["search_text"] = " ".join(
            [
                metadata.canonical_name,
                metadata.domain,
                metadata.family,
                metadata.variation,
                metadata.problem_name,
                metadata.algorithm_family,
                metadata.computational_model,
                metadata.inferred_problem_statement,
                metadata.time_complexity,
                metadata.work,
                metadata.span_depth,
                "randomized" if metadata.randomized.lower() in {"true", "yes", "1"} else "",
                "approximate" if metadata.approximate.lower() in {"true", "yes", "1"} else "",
            ]
        ).lower()
        rows.append(row)
    return rows


def select_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for category, domains, keywords, preferred in CATEGORIES:
        candidate = preferred_candidate(rows, used_ids, category)
        if candidate is None:
            candidate = best_candidate(rows, used_ids, domains, keywords, preferred)
        if candidate is None:
            candidate = best_candidate(rows, used_ids, (), keywords, preferred)
        if candidate is None:
            candidate = best_candidate(rows, used_ids, domains, (), preferred)
        if candidate is None:
            continue
        candidate["selection_category"] = category
        selected.append(candidate)
        used_ids.add(str(candidate["algorithm_id"]))
    if len(selected) < 10:
        for row in sorted(rows, key=rank_row):
            if str(row["algorithm_id"]) not in used_ids:
                row["selection_category"] = "high_quality_fallback"
                selected.append(row)
                used_ids.add(str(row["algorithm_id"]))
            if len(selected) == 10:
                break
    return selected[:10]


def preferred_candidate(rows: list[dict[str, Any]], used_ids: set[str], category: str) -> dict[str, Any] | None:
    rows_by_id = {str(row["algorithm_id"]): row for row in rows}
    for algorithm_id in PREFERRED_IDS.get(category, ()):
        row = rows_by_id.get(algorithm_id)
        if row and algorithm_id not in used_ids and row["readiness"] == "READY_PUBLIC_BLIND" and row["source_link_present"]:
            return row
    return None


def best_candidate(
    rows: list[dict[str, Any]],
    used_ids: set[str],
    domains: tuple[str, ...],
    keywords: tuple[str, ...],
    preferred: tuple[str, ...],
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row["algorithm_id"]) not in used_ids
        and row["readiness"] == "READY_PUBLIC_BLIND"
        and (not domains or str(row["domain"]) in domains)
        and (not keywords or any(keyword in str(row["search_text"]) for keyword in keywords))
    ]
    return min(candidates, key=lambda row: rank_row(row, preferred)) if candidates else None


def rank_row(row: dict[str, Any], preferred: tuple[str, ...] = ()) -> tuple[int, int, int, int, int, str]:
    text = str(row["search_text"])
    preference = min((index for index, term in enumerate(preferred) if term in text), default=len(preferred))
    return (
        preference,
        -int(row["source_link_present"]),
        -int(row["has_complexity"]),
        -int(bool(row.get("work") or row.get("span_depth"))),
        -int(row.get("quality_score", 0)),
        str(row["algorithm_id"]),
    )


def has_source_link(value: str) -> bool:
    cleaned = value.strip().lower()
    return bool(cleaned and cleaned not in {"-", "unknown", "none", "n/a"})


def write_selection(source: SourceDirs, out_root: Path, selected: list[dict[str, Any]]) -> None:
    subdirs = ("public_blind", "public_named", "metadata", "precards", "cards", "reports", "manifests")
    for subdir in subdirs:
        target = out_root / subdir
        target.mkdir(parents=True, exist_ok=True)
        for child in target.glob("AW-*.yaml"):
            child.unlink()
        for child in target.glob("*.json"):
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


def build_manifest(selected: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "selected_count": len(selected),
        "candidate_count": len(rows),
        "selected": [
            {
                "algorithm_id": str(row["algorithm_id"]),
                "canonical_name": str(row["canonical_name"]),
                "domain": str(row["domain"]),
                "selection_category": str(row["selection_category"]),
                "source_link": str(row["source_link"]),
                "quality_score": int(row["quality_score"]),
            }
            for row in selected
        ],
        "selected_domain_counts": dict(sorted(Counter(str(row["domain"]) for row in selected).items())),
    }


if __name__ == "__main__":
    raise SystemExit(main())

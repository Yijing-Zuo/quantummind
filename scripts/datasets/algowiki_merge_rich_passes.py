from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PASS_RANK = {"v1": 1, "second_pass": 2, "third_pass": 3}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create merge recommendations for AlgorithmWiki rich pass outputs.")
    parser.add_argument("--v1-root", required=True)
    parser.add_argument("--second-pass-root", required=True)
    parser.add_argument("--third-pass-root", required=True)
    parser.add_argument("--out-root")
    args = parser.parse_args(argv)

    v1_root = Path(args.v1_root)
    second_root = Path(args.second_pass_root)
    third_root = Path(args.third_pass_root)
    out_root = Path(args.out_root) if args.out_root else third_root
    manifest_dir = out_root / "manifests"
    report_dir = out_root / "reports"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    context_rows = merge_context_rows(
        [
            ("v1", read_csv(v1_root / "manifests" / "ready_public_context.csv")),
            ("second_pass", read_csv(second_root / "manifests" / "recovered_context.csv")),
            ("third_pass", read_csv(third_root / "manifests" / "recovered_context.csv")),
        ]
    )
    probe_rows = merge_probe_rows(
        [
            ("v1", read_csv(v1_root / "manifests" / "ready_public_probe.csv")),
            ("second_pass", read_csv(second_root / "manifests" / "recovered_probe.csv")),
            ("third_pass", read_csv(third_root / "manifests" / "recovered_probe.csv")),
        ]
    )
    write_csv(manifest_dir / "merged_ready_public_context_recommendation.csv", context_rows)
    write_csv(manifest_dir / "merged_ready_public_probe_recommendation.csv", probe_rows)
    write_report(report_dir / "merge_recommendation.md", context_rows, probe_rows)
    print(
        {
            "merged_context_count": len(context_rows),
            "merged_probe_count": len(probe_rows),
            "context_by_pass": dict(Counter(row["source_pass"] for row in context_rows)),
            "probe_by_pass": dict(Counter(row["source_pass"] for row in probe_rows)),
        }
    )
    return 0


def merge_context_rows(inputs: list[tuple[str, list[dict[str, str]]]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    duplicate_digest_seen: set[str] = set()
    for source_pass, rows in inputs:
        for row in rows:
            algorithm_id = str(row.get("algorithm_id", ""))
            digest = str(row.get("card_digest", ""))
            if not algorithm_id:
                continue
            candidate = dict(row)
            candidate["source_pass"] = source_pass
            candidate["merge_action"] = "include"
            if digest and digest in duplicate_digest_seen:
                continue
            existing = selected.get(algorithm_id)
            if existing is None or PASS_RANK[source_pass] >= PASS_RANK[str(existing.get("source_pass", "v1"))]:
                if existing is not None and source_pass == "third_pass":
                    candidate["merge_action"] = "replace_older_same_algorithm_id"
                selected[algorithm_id] = candidate
            if digest:
                duplicate_digest_seen.add(digest)
    return sorted(selected.values(), key=lambda row: str(row.get("algorithm_id", "")))


def merge_probe_rows(inputs: list[tuple[str, list[dict[str, str]]]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    digest_seen: set[tuple[str, str]] = set()
    for source_pass, rows in inputs:
        for row in rows:
            probe_id = str(row.get("probe_id") or row.get("algorithm_id") or "")
            parent_id = str(row.get("parent_algorithm_id", ""))
            digest = str(row.get("card_digest", ""))
            if not probe_id:
                continue
            key = (parent_id, digest)
            if digest and key in digest_seen:
                continue
            candidate = dict(row)
            candidate["source_pass"] = source_pass
            candidate["merge_action"] = "include"
            selected[probe_id] = candidate
            if digest:
                digest_seen.add(key)
    return sorted(selected.values(), key=lambda row: (str(row.get("parent_algorithm_id", "")), str(row.get("probe_id", ""))))


def write_report(path: Path, context_rows: list[dict[str, Any]], probe_rows: list[dict[str, Any]]) -> None:
    context_counts = Counter(str(row.get("source_pass", "")) for row in context_rows)
    probe_counts = Counter(str(row.get("source_pass", "")) for row in probe_rows)
    replacements = [row for row in context_rows if row.get("merge_action") == "replace_older_same_algorithm_id"]
    lines = [
        "# AlgorithmWiki Rich Merge Recommendation",
        "",
        f"- Timestamp: {datetime.now(UTC).isoformat()}",
        f"- Recommended context cards: {len(context_rows)}",
        f"- Context cards by pass: {dict(sorted(context_counts.items()))}",
        f"- Recommended probe cards: {len(probe_rows)}",
        f"- Probe cards by pass: {dict(sorted(probe_counts.items()))}",
        f"- Third-pass replacement recommendations: {len(replacements)}",
        "",
        (
            "The recommendation preserves v1 and second-pass directories, then stages a reviewable merged manifest. "
            "Context rows are deduplicated by algorithm_id and card digest with later-pass rows preferred when they "
            "are more source-supported. Probe rows may coexist when probe_id is unique and card digest/parent pairs differ."
        ),
        "",
        "No OpenAI calls are performed by this merge script.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["id"]
    preferred = [
        "algorithm_id",
        "probe_id",
        "parent_algorithm_id",
        "algorithm_name",
        "parent_algorithm_name",
        "public_context_path",
        "public_probe_path",
        "metadata_context_path",
        "metadata_probe_path",
        "evidence_path",
        "source_pass",
        "merge_action",
        "card_digest",
    ]
    ordered = [field for field in preferred if field in fieldnames] + [field for field in fieldnames if field not in preferred]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())

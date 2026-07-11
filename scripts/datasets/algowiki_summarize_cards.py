from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    load_yaml_mapping,
    metadata_from_mapping,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize Algorithm Wiki generated metadata and public cards.")
    parser.add_argument("--metadata-dir", default="corpus/algorithm_wiki/metadata")
    parser.add_argument("--public-blind-dir", default="corpus/algorithm_wiki/public_blind")
    parser.add_argument("--public-named-dir", default="corpus/algorithm_wiki/public_named")
    parser.add_argument("--manifest", default="corpus/algorithm_wiki/manifests/algowiki_cards_manifest.json")
    parser.add_argument("--out-csv", default="corpus/algorithm_wiki/reports/algowiki_cards_summary.csv")
    parser.add_argument("--out-md", default="corpus/algorithm_wiki/reports/algowiki_cards_summary.md")
    parser.add_argument("--seed", type=int, default=20260627)
    args = parser.parse_args(argv)

    rows = load_rows(Path(args.metadata_dir), Path(args.public_blind_dir), Path(args.public_named_dir))
    manifest = load_manifest(Path(args.manifest))
    write_summary_csv(Path(args.out_csv), rows)
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(
        markdown_summary(rows, manifest, int(args.seed), Path(args.public_blind_dir)),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "metadata_records": len(rows),
                "public_blind_ready": sum(1 for row in rows if row["public_blind_exists"]),
                "public_named_ready": sum(1 for row in rows if row["public_named_exists"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def load_rows(metadata_dir: Path, public_blind_dir: Path, public_named_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(metadata_dir.glob("AW-*.meta.yaml")):
        metadata = metadata_from_mapping(load_yaml_mapping(metadata_path))
        algorithm_id = metadata.algorithm_id
        rows.append(
            {
                "algorithm_id": algorithm_id,
                "readiness": metadata.readiness,
                "quality_score": metadata.quality_score,
                "domain": metadata.domain,
                "input_model": metadata.inferred_input_model,
                "access_model": metadata.inferred_access_model,
                "output_contract": metadata.inferred_output_contract,
                "source_link_type": metadata.source_link_type,
                "page_fetch_status": metadata.page_fetch_status,
                "public_blind_exists": (public_blind_dir / f"{algorithm_id}.yaml").exists(),
                "public_named_exists": (public_named_dir / f"{algorithm_id}.yaml").exists(),
                "review_reasons": "; ".join(metadata.review_reasons),
                "metadata_path": str(metadata_path),
                "public_blind_path": str(public_blind_dir / f"{algorithm_id}.yaml"),
                "public_named_path": str(public_named_dir / f"{algorithm_id}.yaml"),
            }
        )
    return rows


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "algorithm_id",
        "readiness",
        "quality_score",
        "domain",
        "input_model",
        "access_model",
        "output_contract",
        "source_link_type",
        "page_fetch_status",
        "public_blind_exists",
        "public_named_exists",
        "review_reasons",
        "metadata_path",
        "public_blind_path",
        "public_named_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fieldnames})


def markdown_summary(rows: list[dict[str, Any]], manifest: dict[str, Any], seed: int, public_blind_dir: Path) -> str:
    qualities = [int(row["quality_score"]) for row in rows]
    average_quality = statistics.mean(qualities) if qualities else 0.0
    ready_rows = [row for row in rows if row["public_blind_exists"]]
    review_rows = [row for row in rows if not row["public_blind_exists"]]
    rng = random.Random(seed)
    rng.shuffle(review_rows)
    top_rows = sorted(rows, key=lambda row: (-int(row["quality_score"]), str(row["algorithm_id"])))[:20]
    baseline_command = (
        f"Get-ChildItem {public_blind_dir}\\AW-*.yaml | Select-Object -First 10 | ForEach-Object "
        "{ python -m quantummindlite.cli analyze --input $_.FullName --provider mock --output-dir runs\\algowiki_baseline10 }"
    )
    lines = [
        "# Algorithm Wiki Cards Summary",
        "",
        f"- Metadata records: {len(rows)}",
        f"- Precards produced: {manifest.get('precard_count', len(rows))}",
        f"- Public blind ready: {len(ready_rows)}",
        f"- Public named ready: {sum(1 for row in rows if row['public_named_exists'])}",
        f"- Duplicate public blind digest groups suppressed: {manifest.get('duplicate_public_blind_digest_group_count', 0)}",
        f"- Largest duplicate public blind digest group: {manifest.get('largest_duplicate_public_blind_digest_group_size', 0)}",
        f"- Average quality: {average_quality:.2f}",
        "",
        "## Source Limitations",
        *source_limitation_lines(manifest),
        "",
        "## Readiness Distribution",
        *counter_lines(Counter(str(row["readiness"]) for row in rows)),
        "",
        "## Domain Distribution",
        *counter_lines(Counter(str(row["domain"]) for row in rows)),
        "",
        "## Output Contract Distribution",
        *counter_lines(Counter(str(row["output_contract"]) for row in rows)),
        "",
        "## Page Fetch Status",
        *counter_lines(Counter(str(row["page_fetch_status"]) for row in rows)),
        "",
        "## Top Quality Rows",
        *card_lines(top_rows),
        "",
        "## Review Samples",
        *card_lines(review_rows[:20]),
        "",
        "## Next 10-Card Baseline Command",
        "",
        f"`{baseline_command}`",
    ]
    return "\n".join(lines) + "\n"


def source_limitation_lines(manifest: dict[str, Any]) -> list[str]:
    limitations = manifest.get("source_limitations")
    if isinstance(limitations, list) and limitations:
        return [f"- {item}" for item in limitations]
    source_selection = manifest.get("source_selection")
    if isinstance(source_selection, dict):
        limitation = str(source_selection.get("limitation", "")).strip()
        if limitation:
            return [f"- {limitation}"]
    return ["- None recorded."]


def counter_lines(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["- None"]
    return [f"- {key}: {value}" for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def card_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- None"]
    return [
        f"- {row['algorithm_id']}: {row['readiness']}, quality {row['quality_score']}, {row['domain']}, {row['output_contract']}"
        for row in rows
    ]


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    PublicProblemCard,
    load_yaml_mapping,
    metadata_from_mapping,
    public_card_digest,
    validate_public_mapping,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Algorithm Wiki public cards and metadata sidecars.")
    parser.add_argument("--public-dir", default="corpus/algorithm_wiki/public_blind")
    parser.add_argument("--metadata-dir", default="corpus/algorithm_wiki/metadata")
    parser.add_argument("--min-ready", type=int, default=1)
    parser.add_argument("--sample-mock-analyze", type=int, default=10)
    parser.add_argument("--out-report", default="corpus/algorithm_wiki/reports/algowiki_validation_report.json")
    parser.add_argument("--seed", type=int, default=20260627)
    parser.add_argument("--allow-named", action="store_true", help="Validate named review cards without blind-name rejection.")
    args = parser.parse_args(argv)

    public_dir = Path(args.public_dir)
    metadata_dir = Path(args.metadata_dir)
    errors: list[str] = []
    cards: list[Path] = []
    digests: dict[str, list[str]] = {}
    allow_named = bool(args.allow_named) or public_dir.name in {
        "public_named",
        "public_context",
        "public_probe",
        "public_context_recovered",
        "public_probe_recovered",
    }
    for public_path in sorted(public_dir.glob("AW-*.yaml")):
        try:
            data = load_yaml_mapping(public_path)
            canonical_name, quality_score, readiness = read_metadata_summary(
                load_yaml_mapping(metadata_dir / f"{public_path.stem}.meta.yaml")
            )
            validate_public_mapping(data, canonical_name=canonical_name, blind=not allow_named)
            card = PublicProblemCard.from_mapping(data)
            digest = public_card_digest(card)
            digests.setdefault(digest, []).append(public_path.name)
            if is_ready(card, quality_score):
                cards.append(public_path)
            allowed_readiness = {"READY_PUBLIC_BLIND", "READY_PUBLIC_NAMED_ONLY", "READY_PUBLIC_CONTEXT", "READY_PUBLIC_PROBE"}
            if args.allow_named:
                allowed_readiness.add("DUPLICATE_VARIANT")
            if readiness not in allowed_readiness:
                errors.append(f"{public_path.name}: metadata readiness is {readiness}")
        except Exception as exc:
            errors.append(f"{public_path.name}: {exc}")

    if len(cards) < int(args.min_ready):
        errors.append(f"ready card count {len(cards)} is below --min-ready {args.min_ready}")
    duplicate_digest_groups = {digest: names for digest, names in sorted(digests.items()) if len(names) > 1}
    if duplicate_digest_groups and not allow_named:
        errors.append(f"duplicate public blind card digests found: {len(duplicate_digest_groups)} groups")
    mock_results = run_mock_sample(cards, int(args.sample_mock_analyze), int(args.seed), Path(args.out_report))
    for item in mock_results:
        if not item["ok"]:
            errors.append(f"mock analyze failed for {item['card']}: {item['error']}")

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ok": not errors,
        "public_dir": str(public_dir),
        "metadata_dir": str(metadata_dir),
        "total_public_cards": len(list(public_dir.glob("AW-*.yaml"))),
        "ready_cards": len(cards),
        "min_ready": int(args.min_ready),
        "duplicate_digest_group_count": len(duplicate_digest_groups),
        "largest_duplicate_digest_group_size": max((len(names) for names in duplicate_digest_groups.values()), default=0),
        "duplicate_digest_groups": duplicate_digest_groups,
        "mock_analyze": mock_results,
        "errors": errors,
    }
    out_report = Path(args.out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_report.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def is_ready(card: PublicProblemCard, quality_score: int) -> bool:
    return (
        quality_score >= 60
        and len(card.statement) >= 200
        and card.input_model != "unknown_input_model"
        and card.access_model != "unknown_access_model"
        and card.output_contract != "unknown_output_contract"
        and bool(card.size_parameters)
    )


def read_metadata_summary(metadata_data: dict[str, Any]) -> tuple[str, int, str]:
    try:
        metadata = metadata_from_mapping(metadata_data)
        return metadata.canonical_name, metadata.quality_score, metadata.readiness
    except Exception:
        return (
            str(metadata_data.get("canonical_name", metadata_data.get("parent_algorithm_name", ""))),
            int(metadata_data.get("quality_score", metadata_data.get("confidence_score", 0)) or 0),
            str(metadata_data.get("readiness", "")),
        )


def run_mock_sample(public_paths: list[Path], sample_size: int, seed: int, out_report: Path) -> list[dict[str, Any]]:
    if sample_size <= 0 or not public_paths:
        return []
    rng = random.Random(seed)
    sample = list(public_paths)
    rng.shuffle(sample)
    run_dir = out_report.parent / f"{out_report.stem}_mock_analyze_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    for child in run_dir.glob("qml-*"):
        if child.is_dir():
            shutil.rmtree(child)
    results: list[dict[str, Any]] = []
    for path in sample[:sample_size]:
        env = dict(os.environ)
        src_path = str(Path(__file__).resolve().parents[2] / "src")
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
        command = [
            sys.executable,
            "-m",
            "quantummindlite.cli",
            "analyze",
            "--input",
            str(path),
            "--provider",
            "mock",
            "--output-dir",
            str(run_dir),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False, env=env)
        results.append(
            {
                "card": path.name,
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "run_dir": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "",
                "error": completed.stderr.strip(),
            }
        )
    return results


def markdown_report(report: dict[str, Any]) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    lines = [
        f"# Algorithm Wiki Validation Report: {status}",
        "",
        f"- Total public cards: {report['total_public_cards']}",
        f"- Ready cards: {report['ready_cards']}",
        f"- Minimum requested: {report['min_ready']}",
        f"- Duplicate digest groups: {report['duplicate_digest_group_count']}",
        f"- Largest duplicate digest group: {report['largest_duplicate_digest_group_size']}",
        f"- Mock analyze samples: {len(report['mock_analyze'])}",
        "",
        "## Errors",
    ]
    errors = report["errors"]
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

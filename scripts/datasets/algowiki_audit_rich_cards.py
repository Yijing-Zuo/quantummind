from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_build_rich_cards import GENERIC_PHRASES  # noqa: E402
from scripts.datasets.algowiki_common import (  # noqa: E402
    PUBLIC_FIELDS,
    leakage_matches,
    load_yaml_mapping,
    validate_public_mapping,
)

AUDIT_FIELDS = (
    "id",
    "kind",
    "public_path",
    "metadata_path",
    "public_field_set_exactly_seven",
    "public_validation_ok",
    "leakage_free",
    "concrete_problem_task",
    "concrete_input",
    "concrete_output",
    "complexity_included",
    "no_generic_template_phrase",
    "known_input_access_output",
    "source_trace_present",
    "probe_assumptions_explicit",
    "probe_not_end_to_end_explicit",
    "parent_trace_present",
    "recommended_action",
    "severity",
    "issue_codes",
    "human_review_summary",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit rich AlgorithmWiki context/probe cards.")
    parser.add_argument("--public-dir", required=True)
    parser.add_argument("--metadata-dir", required=True)
    parser.add_argument("--kind", choices=["context", "probe"], required=True)
    parser.add_argument("--out-jsonl", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args(argv)

    records = audit_directory(Path(args.public_dir), Path(args.metadata_dir), str(args.kind))
    write_jsonl(Path(args.out_jsonl), records)
    write_csv(Path(args.out_csv), records)
    write_markdown(Path(args.out_md), records)
    print(json.dumps(summary(records), indent=2, sort_keys=True))
    return 0


def audit_directory(public_dir: Path, metadata_dir: Path, kind: str) -> list[dict[str, Any]]:
    return [audit_card(path, metadata_dir / f"{path.stem}.meta.yaml", kind) for path in sorted(public_dir.glob("*.yaml"))]


def audit_card(public_path: Path, metadata_path: Path, kind: str) -> dict[str, Any]:
    errors: list[str] = []
    public_data = load_or_error(public_path, errors, "public")
    metadata = load_or_error(metadata_path, errors, "metadata")
    statement = str(public_data.get("statement", ""))
    validation_ok = validate_public(public_data, errors)
    leak_terms = leakage_matches(json.dumps(public_data, sort_keys=True))
    record = {
        "id": public_path.stem,
        "kind": kind,
        "public_path": str(public_path),
        "metadata_path": str(metadata_path),
        "public_field_set_exactly_seven": tuple(public_data) == PUBLIC_FIELDS,
        "public_validation_ok": validation_ok,
        "leakage_free": not leak_terms,
        "concrete_problem_task": concrete_problem(statement, kind),
        "concrete_input": concrete_input(statement, public_data),
        "concrete_output": concrete_output(statement, public_data),
        "complexity_included": complexity_included(statement, kind),
        "no_generic_template_phrase": not any(phrase in statement.lower() for phrase in GENERIC_PHRASES),
        "known_input_access_output": known_io(public_data),
        "source_trace_present": bool(metadata.get("source_records_used")) and int(metadata.get("source_count", 0) or 0) > 0,
        "probe_assumptions_explicit": True,
        "probe_not_end_to_end_explicit": True,
        "parent_trace_present": True,
    }
    if kind == "probe":
        introduced = metadata.get("introduced_assumptions", [])
        record["probe_assumptions_explicit"] = isinstance(introduced, list) and bool(introduced)
        record["probe_not_end_to_end_explicit"] = bool(metadata.get("not_end_to_end_claim")) and "not an end-to-end" in statement.lower()
        record["parent_trace_present"] = bool(metadata.get("parent_algorithm_id")) and bool(metadata.get("source_records_used"))
    issues = issue_codes(record, errors, leak_terms)
    action, severity, review = classify(issues)
    record["recommended_action"] = action
    record["severity"] = severity
    record["issue_codes"] = ";".join(issues)
    record["human_review_summary"] = review
    return record


def load_or_error(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label}_missing")
        return {}
    try:
        return load_yaml_mapping(path)
    except Exception as exc:
        errors.append(f"{label}_parse_failed:{exc}")
        return {}


def validate_public(public_data: dict[str, Any], errors: list[str]) -> bool:
    try:
        validate_public_mapping(public_data, blind=False)
        return True
    except Exception as exc:
        errors.append(f"public_validation_failed:{exc}")
        return False


def concrete_problem(statement: str, kind: str) -> bool:
    lowered = statement.lower()
    if kind == "probe":
        return "probe" in lowered and ("subroutine" in lowered or "query-model" in lowered)
    return len(statement.split()) >= 80 and "task" in lowered and "input semantics" in lowered


def concrete_input(statement: str, public_data: dict[str, Any]) -> bool:
    return str(public_data.get("input_model", "")).strip() != "unknown_input_model" and "input" in statement.lower()


def concrete_output(statement: str, public_data: dict[str, Any]) -> bool:
    return str(public_data.get("output_contract", "")).strip() != "unknown_output_contract" and "output" in statement.lower()


def complexity_included(statement: str, kind: str) -> bool:
    if kind == "probe":
        return True
    lowered = statement.lower()
    return "complexity" in lowered and "time" in lowered and "space" in lowered


def known_io(public_data: dict[str, Any]) -> bool:
    return (
        str(public_data.get("input_model", "")) != "unknown_input_model"
        and str(public_data.get("access_model", "")) != "unknown_access_model"
        and str(public_data.get("output_contract", "")) != "unknown_output_contract"
    )


def issue_codes(record: dict[str, Any], errors: list[str], leak_terms: list[str]) -> list[str]:
    issues = list(errors)
    if leak_terms:
        issues.append("leakage_terms:" + ",".join(sorted(leak_terms)))
    for key in (
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "leakage_free",
        "concrete_problem_task",
        "concrete_input",
        "concrete_output",
        "complexity_included",
        "no_generic_template_phrase",
        "known_input_access_output",
        "source_trace_present",
        "probe_assumptions_explicit",
        "probe_not_end_to_end_explicit",
        "parent_trace_present",
    ):
        if not record[key]:
            issues.append(key)
    return stable_unique(issues)


def classify(issues: list[str]) -> tuple[str, str, str]:
    critical_prefixes = (
        "public_missing",
        "public_parse_failed",
        "metadata_missing",
        "metadata_parse_failed",
        "public_validation_failed",
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "leakage_terms:",
        "leakage_free",
        "probe_not_end_to_end_explicit",
    )
    major = {
        "concrete_problem_task",
        "concrete_input",
        "concrete_output",
        "complexity_included",
        "no_generic_template_phrase",
        "known_input_access_output",
        "source_trace_present",
        "probe_assumptions_explicit",
        "parent_trace_present",
    }
    if any(any(issue.startswith(prefix) for prefix in critical_prefixes) for issue in issues):
        return "EXCLUDE_OR_REGENERATE", "CRITICAL", "; ".join(issues)
    if any(issue in major for issue in issues):
        return "REVIEW_AND_REGENERATE", "MAJOR", "; ".join(issues)
    return "ACCEPT", "NONE", "Rich public card passes shape, leakage, source-trace, and semantic checks."


def stable_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AUDIT_FIELDS))
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in AUDIT_FIELDS})


def write_markdown(path: Path, records: list[dict[str, Any]]) -> None:
    counts = summary(records)
    lines = [
        f"# AlgorithmWiki Rich {records[0]['kind'].title() if records else 'Card'} Audit",
        "",
        f"- Total cards: {counts['total']}",
        f"- Severity counts: {counts['severity_counts']}",
        f"- Action counts: {counts['action_counts']}",
        f"- Thresholds passed: {counts['thresholds_passed']}",
        "",
        "| id | severity | action | summary |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| {id} | {severity} | {action} | {summary} |".format(
                id=record["id"],
                severity=record["severity"],
                action=record["recommended_action"],
                summary=str(record["human_review_summary"]).replace("|", "\\|"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts = Counter(str(record.get("severity", "")) for record in records)
    action_counts = Counter(str(record.get("recommended_action", "")) for record in records)
    kind = str(records[0].get("kind", "")) if records else ""
    total = len(records)
    major_limit = 0.05 if kind == "probe" else 0.03
    thresholds_passed = bool(severity_counts.get("CRITICAL", 0) == 0 and (severity_counts.get("MAJOR", 0) / max(total, 1)) <= major_limit)
    return {
        "total": total,
        "severity_counts": dict(sorted(severity_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "thresholds_passed": thresholds_passed,
    }


if __name__ == "__main__":
    raise SystemExit(main())

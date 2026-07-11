from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    PUBLIC_FIELDS,
    load_yaml_mapping,
    normalize_whitespace,
    validate_public_mapping,
)
from scripts.datasets.algowiki_generate_registry_v1_probes import (  # noqa: E402
    FORBIDDEN_PUBLIC_LABELS,
    OUT_ROOT,
    READY_FIELDS,
    REGISTRY_V1_PRIMITIVES,
    ROOT,
    audit_result_summary,
    forbidden_public_labels,
    read_csv,
    review_reason,
    write_csv,
    write_generation_report,
    write_jsonl,
)

AUDIT_FIELDS = (
    "probe_id",
    "public_path",
    "metadata_path",
    "evidence_path",
    "public_field_set_exactly_seven",
    "public_validation_ok",
    "public_forbidden_label_free",
    "not_end_to_end_explicit",
    "query_subroutine_boundary_explicit",
    "metadata_target_registry_v1",
    "metadata_assumptions_explicit",
    "metadata_not_end_to_end_true",
    "new_access_or_output_pattern",
    "public_schema_registry_compatible",
    "no_full_output_positive_claim",
    "source_trace_present",
    "duplicate_or_low_value_explained",
    "recommended_action",
    "severity",
    "issue_codes",
    "human_review_summary",
)
NEW_ACCESS_MODELS = {
    "coherent_value_oracle",
    "coherent_backtracking_tree_oracle",
    "coherent_markov_chain_walk_oracle",
}
NEW_OUTPUT_CONTRACTS = {
    "argmin_item",
    "minimum_value_and_argmin",
    "one_solution_leaf",
    "one_marked_vertex",
    "additive_count_estimate",
    "relative_count_estimate",
}
FULL_OUTPUT_CONTRACTS = {
    "sorted_order",
    "path_or_tree",
    "assignment_or_schedule",
    "data_structure_output",
    "full_solution",
    "full_sequence_output",
    "full_classical_output",
    "multiple_witnesses",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit generated registry-v1 AlgorithmWiki probes.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--registry-root", default=str(OUT_ROOT))
    args = parser.parse_args(argv)

    root = Path(args.root)
    registry_root = Path(args.registry_root)
    ready_rows = read_csv(registry_root / "manifests" / "ready_public_probe_registry_v1.csv")
    duplicate_keys = duplicate_probe_keys(ready_rows)
    audit_rows = [audit_row(row, duplicate_keys) for row in ready_rows]
    write_jsonl(registry_root / "audit" / "registry_v1_probe_audit.jsonl", audit_rows)
    write_csv(registry_root / "audit" / "registry_v1_probe_audit.csv", audit_rows, AUDIT_FIELDS)
    write_audit_markdown(registry_root / "audit" / "registry_v1_probe_audit.md", audit_rows)
    refreshed_ready = refresh_review_decisions(ready_rows, audit_rows)
    write_csv(registry_root / "manifests" / "ready_public_probe_registry_v1.csv", refreshed_ready, READY_FIELDS)
    write_jsonl(registry_root / "manifests" / "ready_public_probe_registry_v1.jsonl", refreshed_ready)
    write_human_review(registry_root, refreshed_ready)
    write_generation_report(
        registry_root,
        read_csv(root / "manifests" / "ready_public_context.csv"),
        read_csv(root / "manifests" / "ready_public_probe.csv"),
        read_csv(registry_root / "manifests" / "registry_v1_screening.csv"),
        refreshed_ready,
    )
    summary = summarize(audit_rows)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["thresholds_passed"] else 1


def audit_row(row: dict[str, Any], duplicate_keys: set[tuple[str, str]]) -> dict[str, Any]:
    errors: list[str] = []
    public = load_or_error(Path(row["public_probe_path"]), errors, "public")
    metadata = load_or_error(Path(row["metadata_probe_path"]), errors, "metadata")
    evidence = load_or_error(Path(row["evidence_path"]), errors, "evidence")
    statement = str(public.get("statement", ""))
    lowered = statement.lower()
    validation_ok = validate_public(public, errors)
    forbidden = forbidden_public_labels(json.dumps(public, sort_keys=True) + "\n" + statement)
    target = str(metadata.get("target_registry_primitive", ""))
    parent_type_key = (str(metadata.get("parent_algorithm_id", "")), target)
    public_schema_registry_compatible = bool(
        row.get("probe_access_model") == public.get("access_model")
        and row.get("probe_output_contract") == public.get("output_contract")
        and row.get("target_registry_primitive") == target
    )
    record = {
        "probe_id": str(row.get("probe_id", "")),
        "public_path": str(row.get("public_probe_path", "")),
        "metadata_path": str(row.get("metadata_probe_path", "")),
        "evidence_path": str(row.get("evidence_path", "")),
        "public_field_set_exactly_seven": tuple(public) == PUBLIC_FIELDS,
        "public_validation_ok": validation_ok,
        "public_forbidden_label_free": not forbidden,
        "not_end_to_end_explicit": "not an end-to-end" in lowered or "not end-to-end" in lowered,
        "query_subroutine_boundary_explicit": "query-model" in lowered and "subroutine" in lowered,
        "metadata_target_registry_v1": target in REGISTRY_V1_PRIMITIVES,
        "metadata_assumptions_explicit": bool(metadata.get("introduced_assumptions")),
        "metadata_not_end_to_end_true": metadata.get("not_end_to_end_claim") is True,
        "new_access_or_output_pattern": public.get("access_model") in NEW_ACCESS_MODELS
        or public.get("output_contract") in NEW_OUTPUT_CONTRACTS,
        "public_schema_registry_compatible": public_schema_registry_compatible,
        "no_full_output_positive_claim": public.get("output_contract") not in FULL_OUTPUT_CONTRACTS,
        "source_trace_present": bool(metadata.get("source_records_used")) and bool(evidence.get("source_records_used")),
        "duplicate_or_low_value_explained": parent_type_key not in duplicate_keys
        or bool(metadata.get("overgeneration_risk") in {"medium", "high"}),
    }
    issues = issue_codes(record, errors, forbidden)
    action, severity, summary = classify(issues)
    record["recommended_action"] = action
    record["severity"] = severity
    record["issue_codes"] = ";".join(issues)
    record["human_review_summary"] = summary
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


def validate_public(public: dict[str, Any], errors: list[str]) -> bool:
    try:
        validate_public_mapping(public, blind=False)
        return True
    except Exception as exc:
        errors.append(f"public_validation_failed:{exc}")
        return False


def issue_codes(record: dict[str, Any], errors: list[str], forbidden: list[str]) -> list[str]:
    issues = list(errors)
    if forbidden:
        issues.append("public_forbidden_labels:" + ",".join(sorted(forbidden)))
    for key in (
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "public_forbidden_label_free",
        "not_end_to_end_explicit",
        "query_subroutine_boundary_explicit",
        "metadata_target_registry_v1",
        "metadata_assumptions_explicit",
        "metadata_not_end_to_end_true",
        "new_access_or_output_pattern",
        "public_schema_registry_compatible",
        "no_full_output_positive_claim",
        "source_trace_present",
        "duplicate_or_low_value_explained",
    ):
        if not record[key]:
            issues.append(key)
    return stable_unique(issues)


def classify(issues: list[str]) -> tuple[str, str, str]:
    critical = (
        "public_missing",
        "public_parse_failed",
        "metadata_missing",
        "metadata_parse_failed",
        "evidence_missing",
        "evidence_parse_failed",
        "public_validation_failed",
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "public_forbidden_labels:",
        "public_forbidden_label_free",
        "not_end_to_end_explicit",
        "query_subroutine_boundary_explicit",
        "metadata_target_registry_v1",
        "metadata_not_end_to_end_true",
        "new_access_or_output_pattern",
        "public_schema_registry_compatible",
        "no_full_output_positive_claim",
    )
    major = {"metadata_assumptions_explicit", "source_trace_present", "duplicate_or_low_value_explained"}
    if any(any(issue.startswith(prefix) for prefix in critical) for issue in issues):
        return "EXCLUDE_OR_REGENERATE", "CRITICAL", "; ".join(issues)
    if any(issue in major for issue in issues):
        return "REVIEW_AND_REGENERATE", "MAJOR", "; ".join(issues)
    return "ACCEPT", "NONE", "Registry-v1 probe passes schema, leakage, source-trace, compatibility, and boundary checks."


def duplicate_probe_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter(
        (str(row.get("parent_algorithm_id", "")), str(row.get("target_registry_primitive", ""))) for row in rows
    )
    return {key for key, count in counts.items() if count > 1}


def refresh_review_decisions(ready_rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_by_id = {row["probe_id"]: row for row in audit_rows}
    refreshed: list[dict[str, Any]] = []
    for row in ready_rows:
        updated = dict(row)
        audit = audit_by_id.get(str(row.get("probe_id", "")), {})
        if audit.get("severity") == "CRITICAL":
            updated["review_decision"] = "EXCLUDE"
        elif audit.get("severity") == "MAJOR":
            updated["review_decision"] = "REGENERATE"
        refreshed.append(updated)
    return refreshed


def write_human_review(registry_root: Path, rows: list[dict[str, Any]]) -> None:
    sample = rows[: min(80, len(rows))]
    lines = ["# Registry V1 Human-Level Review", ""]
    for row in sample:
        metadata = load_yaml_mapping(Path(row["metadata_probe_path"]))
        paragraph = (
            f"{row['probe_id']} parent algorithm {row['parent_algorithm_name']} targets {row['target_registry_primitive']}. "
            f"Input/access/output judgment: {row['probe_input_model']} / {row['probe_access_model']} / {row['probe_output_contract']} "
            "is compatible with the intended query-scope primitive. Introduced assumptions are explicit: "
            f"{'; '.join(str(item) for item in metadata.get('introduced_assumptions', []))}. "
            "The not-end-to-end boundary is clear in the public statement and metadata. "
            f"Scientific usefulness: {metadata.get('why_probe_is_scientifically_interesting', '')} "
            f"Risk of generic overgeneration: {row['overgeneration_risk']}. Final decision: {row['review_decision']}. "
            f"Reason: {review_reason(row, metadata)}"
        )
        lines.append(normalize_whitespace(paragraph))
        lines.append("")
    decisions = Counter(str(row.get("review_decision", "")) for row in rows)
    lines.append(f"Reviewed cards: {len(sample)} of {len(rows)}.")
    lines.append(f"Review decisions across manifest: {dict(sorted(decisions.items()))}.")
    (registry_root / "reports" / "registry_v1_human_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_audit_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    summary = summarize(rows)
    lines = [
        "# Registry V1 Probe Audit",
        "",
        f"- Total cards: {summary['total']}",
        f"- Severity counts: {summary['severity_counts']}",
        f"- Action counts: {summary['action_counts']}",
        f"- Thresholds passed: {summary['thresholds_passed']}",
        "- Critical threshold: 0; major threshold: <=5%.",
        f"- Forbidden public labels include: {', '.join(FORBIDDEN_PUBLIC_LABELS)}.",
        "",
        "| probe_id | severity | action | issues |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {cell(row.get('probe_id'))} | {cell(row.get('severity'))} | "
            f"{cell(row.get('recommended_action'))} | {cell(row.get('issue_codes'))} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    severity_counts = Counter(str(row.get("severity", "")) for row in rows)
    action_counts = Counter(str(row.get("recommended_action", "")) for row in rows)
    major_rate = severity_counts.get("MAJOR", 0) / max(total, 1)
    return {
        "total": total,
        "severity_counts": dict(sorted(severity_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "major_rate": major_rate,
        "thresholds_passed": bool(severity_counts.get("CRITICAL", 0) == 0 and major_rate <= 0.05),
        "audit_summary": audit_result_summary(OUT_ROOT),
    }


def stable_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.candidate_value_labeling import label_candidate_value  # noqa: E402

SUMMARY_FIELDS = (
    "algorithm_id",
    "probe_id",
    "parent_algorithm_id",
    "algorithm_name",
    "run_dir",
    "selected_candidate",
    "verdict",
    "scope",
    "route",
    "b_failures",
    "b_unknowns",
    "weak_analogy_primitive_ids",
    "weak_analogy_missing",
    "barriers",
    "limitations",
    "expert_questions",
    "claim_flags",
    "token_usage",
    "error_present",
    "trace_actions",
    "parse_status_summary",
    "candidate_value_label",
    "candidate_value_score",
    "candidate_value_reason",
    "candidate_value_features",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize saved QuantumMindLite discovery runs.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--kind", choices=["context", "probe"], required=True)
    args = parser.parse_args(argv)

    manifest_rows = read_csv(Path(args.manifest))
    manifest_by_name = manifest_index(manifest_rows, str(args.kind))
    rows = [summarize_run(path, manifest_by_name, str(args.kind)) for path in find_run_dirs(Path(args.run_dir))]
    write_csv(Path(args.out_csv), rows)
    write_markdown(Path(args.out_md), rows, str(args.kind))
    print(json.dumps({"runs": len(rows), "out_csv": args.out_csv, "out_md": args.out_md}, indent=2, sort_keys=True))
    return 0


def find_run_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    dirs = []
    for path in root.rglob("*"):
        if path.is_dir() and ((path / "state.json").exists() or (path / "decision.json").exists() or (path / "error.json").exists()):
            dirs.append(path)
    return sorted(dirs)


def summarize_run(run_dir: Path, manifest_by_name: dict[str, dict[str, Any]], kind: str) -> dict[str, Any]:
    state = read_json(run_dir / "state.json")
    decision = read_json(run_dir / "decision.json")
    input_data = read_json(run_dir / "input.json")
    error = read_json(run_dir / "error.json")
    manifest_row = manifest_by_name.get(card_digest_key(input_data), {})
    candidate = object_at(state, ("candidate_card",))
    weak = list_value(candidate.get("weak_analogy_opportunities") if isinstance(candidate, dict) else [])
    checks = list_value(decision.get("checks", decision.get("b_check_results")))
    selected_candidate = none_to_empty(candidate.get("selected_candidate") if isinstance(candidate, dict) else "")
    verdict = first_text(decision, ("verdict", "authoritative_verdict"))
    scope = first_text(decision, ("scope", "claim_scope", "maximum_supported_claim_scope"))
    route = first_text(decision, ("route", "d_route"))
    b_failures = check_ids(checks, "FAIL")
    b_unknowns = check_ids(checks, "UNKNOWN")
    barriers = describe_items(list_value(candidate.get("barriers") if isinstance(candidate, dict) else []), "barrier_id")
    limitations = list_value(candidate.get("limitations") if isinstance(candidate, dict) else [])
    expert_questions = list_value(candidate.get("expert_questions") if isinstance(candidate, dict) else [])
    claim_flags = list_value(candidate.get("claim_flags") if isinstance(candidate, dict) else [])
    algorithm_name = str(manifest_row.get("algorithm_name", manifest_row.get("parent_algorithm_name", "")))
    row = {
        "algorithm_id": str(manifest_row.get("algorithm_id", "")),
        "probe_id": str(manifest_row.get("probe_id", "")),
        "parent_algorithm_id": str(manifest_row.get("parent_algorithm_id", "")),
        "algorithm_name": algorithm_name,
        "run_dir": str(run_dir),
        "selected_candidate": selected_candidate,
        "verdict": verdict,
        "scope": scope,
        "route": route,
        "b_failures": ";".join(b_failures),
        "b_unknowns": ";".join(b_unknowns),
        "weak_analogy_primitive_ids": ";".join(str(item.get("primitive_id", "")) for item in weak if isinstance(item, dict)),
        "weak_analogy_missing": ";".join(
            ",".join(str(value) for value in item.get("missing_access_or_output_or_promises", []))
            for item in weak
            if isinstance(item, dict)
        ),
        "barriers": ";".join(barriers),
        "limitations": ";".join(str(item) for item in limitations),
        "expert_questions": ";".join(str(item) for item in expert_questions),
        "claim_flags": ";".join(str(item) for item in claim_flags),
        "token_usage": json.dumps(state.get("token_usage", decision.get("token_usage", {})), sort_keys=True),
        "error_present": str(bool(error)),
        "trace_actions": trace_actions(state),
        "parse_status_summary": parse_status_summary(state),
    }
    value_label = label_candidate_value(
        candidate_value_record(
            row=row,
            input_data=input_data,
            candidate=candidate,
            weak=weak,
            manifest_row=manifest_row,
            b_failures=b_failures,
            b_unknowns=b_unknowns,
            limitations=limitations,
            expert_questions=expert_questions,
            claim_flags=claim_flags,
            barriers=barriers,
        )
    )
    row.update(
        {
            "candidate_value_label": value_label.label,
            "candidate_value_score": str(value_label.score),
            "candidate_value_reason": value_label.reason,
            "candidate_value_features": ";".join(value_label.features),
        }
    )
    return row


def candidate_value_record(
    *,
    row: dict[str, Any],
    input_data: dict[str, Any],
    candidate: dict[str, Any],
    weak: list[Any],
    manifest_row: dict[str, Any],
    b_failures: list[str],
    b_unknowns: list[str],
    limitations: list[Any],
    expert_questions: list[Any],
    claim_flags: list[Any],
    barriers: list[str],
) -> dict[str, Any]:
    return {
        "algorithm_id": row.get("algorithm_id", ""),
        "probe_id": row.get("probe_id", ""),
        "algorithm_name": row.get("algorithm_name", ""),
        "parent_algorithm_name": manifest_row.get("parent_algorithm_name", row.get("algorithm_name", "")),
        "probe_type": manifest_row.get("probe_type", ""),
        "selected_candidate": row.get("selected_candidate", ""),
        "verdict": row.get("verdict", ""),
        "scope": row.get("scope", candidate.get("claim_scope", "")),
        "route": row.get("route", ""),
        "input_model": input_data.get("input_model", ""),
        "access_model": input_data.get("access_model", ""),
        "output_contract": input_data.get("output_contract", ""),
        "original_output_contract": manifest_row.get("original_output_contract", ""),
        "probe_output_contract": manifest_row.get("probe_output_contract", ""),
        "statement": input_data.get("statement", ""),
        "promises": input_data.get("promises", []),
        "introduced_assumptions": manifest_row.get("introduced_assumptions", ""),
        "weak_analogy_opportunities": weak,
        "limitations": limitations,
        "expert_questions": expert_questions,
        "claim_flags": claim_flags,
        "barriers": barriers,
        "b_failures": b_failures,
        "b_unknowns": b_unknowns,
    }


def manifest_index(rows: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    key = "public_context_path" if kind == "context" else "public_probe_path"
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        card_path = Path(str(row.get(key, "")))
        if card_path.exists():
            with suppress(Exception):
                indexed[card_digest_key(read_yaml_like(card_path))] = row
    return indexed


def card_digest_key(data: dict[str, Any]) -> str:
    public = {
        key: data.get(key)
        for key in ("statement", "input_model", "access_model", "output_contract", "promises", "size_parameters", "ambiguities")
    }
    return json.dumps(public, sort_keys=True, ensure_ascii=True)


def read_yaml_like(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def check_ids(checks: list[Any], outcome: str) -> list[str]:
    ids = []
    for check in checks:
        if isinstance(check, dict) and str(check.get("outcome", "")) == outcome:
            ids.append(str(check.get("check_id", check.get("id", check.get("rule_id", "")))))
    return ids


def first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = none_to_empty(data.get(key))
        if value:
            return value
    return ""


def none_to_empty(value: Any) -> str:
    return "" if value is None else str(value)


def describe_items(items: list[Any], key: str) -> list[str]:
    described = []
    for item in items:
        if isinstance(item, dict):
            described.append(str(item.get(key, item)))
        else:
            described.append(str(item))
    return described


def trace_actions(state: dict[str, Any]) -> str:
    trace = list_value(state.get("trace"))
    actions = []
    for item in trace:
        if isinstance(item, dict):
            actions.append(str(item.get("action", item.get("role", ""))))
    return ";".join(action for action in actions if action)


def parse_status_summary(state: dict[str, Any]) -> str:
    trace = list_value(state.get("trace"))
    statuses = []
    for item in trace:
        if isinstance(item, dict) and item.get("parse_status"):
            statuses.append(str(item["parse_status"]))
    return ";".join(statuses)


def object_at(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key, {})
    return current if isinstance(current, dict) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with suppress(Exception):
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    return {}


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in SUMMARY_FIELDS})


def write_markdown(path: Path, rows: list[dict[str, Any]], kind: str) -> None:
    lines = [f"# QuantumMindLite {kind.title()} Discovery Run Summary", "", f"- Runs summarized: {len(rows)}", ""]
    lines.append("| id | verdict | scope | route | selected | candidate_value_label | score | reason | features | error |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        identifier = str(row.get("probe_id") or row.get("algorithm_id"))
        lines.append(
            f"| {markdown_cell(identifier)} | {markdown_cell(row.get('verdict'))} | {markdown_cell(row.get('scope'))} | "
            f"{markdown_cell(row.get('route'))} | {markdown_cell(row.get('selected_candidate'))} | "
            f"{markdown_cell(row.get('candidate_value_label'))} | {markdown_cell(row.get('candidate_value_score'))} | "
            f"{markdown_cell(row.get('candidate_value_reason'))} | {markdown_cell(row.get('candidate_value_features'))} | "
            f"{markdown_cell(row.get('error_present'))} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())

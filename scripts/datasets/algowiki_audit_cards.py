from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    ACCESS_MODELS,
    OUTPUT_CONTRACTS,
    PUBLIC_FIELDS,
    blind_name_leak,
    leakage_matches,
    load_yaml_mapping,
    metadata_from_mapping,
    safe_yaml_dump,
    validate_public_mapping,
)

CSV_FIELDS = (
    "algorithm_id",
    "public_path",
    "metadata_path",
    "precard_path",
    "public_field_set_exactly_seven",
    "public_validation_ok",
    "leakage_free",
    "blind_name_leakage_free",
    "metadata_not_in_public",
    "statement_self_contained",
    "input_semantics_clear",
    "output_semantics_clear",
    "complexity_included_when_available",
    "computational_model_included_when_relevant",
    "provenance_kept_out_of_blind_card",
    "access_model_conservative",
    "output_contract_conservative",
    "public_statement_not_merely_title",
    "public_statement_not_only_complexity_formula",
    "not_enough_io",
    "theorem_link_only_row",
    "duplicate_variant_relation",
    "likely_sorting_barrier",
    "likely_full_output_barrier",
    "likely_numerical_precision_issue",
    "likely_parallel_only_entry",
    "recommended_action",
    "severity",
    "issue_codes",
    "human_review_summary",
)

PROVENANCE_PATTERNS = (
    r"https?://",
    r"\bdoi\b",
    r"\barxiv\b",
    r"\balgorithm\s+wiki\b",
    r"\bsource\s+(row|link|dataset|record)\b",
    r"\bpage\s+url\b",
    r"\bpaperbench\b",
    r"\bmetadata\b",
)

OUTPUT_VERBS = (
    "compute",
    "return",
    "produce",
    "output",
    "decide",
    "estimate",
    "sort",
    "construct",
    "report",
    "find",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Algorithm Wiki public cards against leakage and curation checks.")
    parser.add_argument("--public-dir", default="corpus/algorithm_wiki/public_blind")
    parser.add_argument("--metadata-dir", default="corpus/algorithm_wiki/metadata")
    parser.add_argument("--precard-dir", default="corpus/algorithm_wiki/precards")
    parser.add_argument("--out-jsonl", default="corpus/algorithm_wiki/reports/algowiki_card_audit.jsonl")
    parser.add_argument("--out-csv", default="corpus/algorithm_wiki/reports/algowiki_card_audit.csv")
    parser.add_argument("--out-md", default="corpus/algorithm_wiki/reports/algowiki_card_audit.md")
    parser.add_argument("--allow-named", action="store_true", help="Audit named review cards without blind-only leakage checks.")
    args = parser.parse_args(argv)

    public_dir = Path(args.public_dir)
    allow_named = bool(args.allow_named) or public_dir.name == "public_named"
    records = audit_directory(public_dir, Path(args.metadata_dir), resolve_precard_dir(public_dir, Path(args.precard_dir)), allow_named)
    write_jsonl(Path(args.out_jsonl), records)
    write_csv(Path(args.out_csv), records)
    write_markdown(Path(args.out_md), records)
    print(json.dumps(summary(records), indent=2, sort_keys=True))
    return 0


def audit_directory(public_dir: Path, metadata_dir: Path, precard_dir: Path, allow_named: bool = False) -> list[dict[str, Any]]:
    return [
        audit_card(path, metadata_dir / f"{path.stem}.meta.yaml", precard_dir / f"{path.stem}.precard.yaml", allow_named)
        for path in sorted(public_dir.glob("AW-*.yaml"))
    ]


def resolve_precard_dir(public_dir: Path, requested: Path) -> Path:
    sibling = public_dir.parent / "precards"
    if sibling.exists() and requested == Path("corpus/algorithm_wiki/precards"):
        return sibling
    return requested


def audit_card(public_path: Path, metadata_path: Path, precard_path: Path, allow_named: bool = False) -> dict[str, Any]:
    algorithm_id = public_path.stem
    errors: list[str] = []
    public_data = load_or_error(public_path, errors, "public")
    metadata_data = load_or_error(metadata_path, errors, "metadata")
    precard_present = precard_path.exists()
    if precard_present:
        load_or_error(precard_path, errors, "precard")
    else:
        errors.append("precard missing")

    canonical_name = str(metadata_data.get("canonical_name", ""))
    public_text = safe_yaml_dump(public_data) if public_data else ""
    statement = str(public_data.get("statement", ""))
    input_model = str(public_data.get("input_model", "unknown_input_model"))
    access_model = str(public_data.get("access_model", "unknown_access_model"))
    output_contract = str(public_data.get("output_contract", "unknown_output_contract"))
    metadata = parse_metadata(metadata_data, errors)
    metadata_leaks = metadata_value_leaks(metadata_data, public_text, allow_named)
    leak_terms = leakage_matches(public_text)
    provenance_leaks = [] if allow_named else provenance_matches(public_text)
    validation_ok = validate_public(public_data, canonical_name, errors, allow_named)

    record: dict[str, Any] = {
        "algorithm_id": algorithm_id,
        "public_path": str(public_path),
        "metadata_path": str(metadata_path),
        "precard_path": str(precard_path),
        "public_field_set_exactly_seven": tuple(public_data) == PUBLIC_FIELDS,
        "public_validation_ok": validation_ok,
        "leakage_free": not leak_terms,
        "blind_name_leakage_free": allow_named or not blind_name_leak(canonical_name, public_text),
        "metadata_not_in_public": not metadata_leaks,
        "statement_self_contained": statement_self_contained(statement, input_model, output_contract),
        "input_semantics_clear": input_semantics_clear(statement, input_model, public_data),
        "output_semantics_clear": output_semantics_clear(statement, output_contract),
        "complexity_included_when_available": complexity_included_when_available(statement, metadata_data),
        "computational_model_included_when_relevant": computational_model_included_when_relevant(public_text, metadata_data),
        "provenance_kept_out_of_blind_card": not provenance_leaks,
        "access_model_conservative": access_model_conservative(access_model, public_text),
        "output_contract_conservative": output_contract_conservative(output_contract),
        "public_statement_not_merely_title": public_statement_not_merely_title(statement, canonical_name),
        "public_statement_not_only_complexity_formula": public_statement_not_only_complexity_formula(statement),
        "not_enough_io": not_enough_io(statement, input_model, access_model, output_contract),
        "theorem_link_only_row": theorem_link_only_row(canonical_name, statement),
        "duplicate_variant_relation": duplicate_variant_relation(metadata_data),
        "likely_sorting_barrier": likely_sorting_barrier(metadata_data, output_contract),
        "likely_full_output_barrier": likely_full_output_barrier(output_contract),
        "likely_numerical_precision_issue": likely_numerical_precision_issue(metadata_data, output_contract),
        "likely_parallel_only_entry": likely_parallel_only_entry(metadata_data, statement),
    }
    issue_codes = issue_codes_for(record, errors, leak_terms, metadata_leaks, provenance_leaks, metadata is None)
    action, severity, summary_text = classify(issue_codes, record)
    record["recommended_action"] = action
    record["severity"] = severity
    record["issue_codes"] = ";".join(issue_codes)
    record["human_review_summary"] = summary_text
    return record


def load_or_error(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} missing")
        return {}
    try:
        return load_yaml_mapping(path)
    except Exception as exc:
        errors.append(f"{label} parse failed: {exc}")
        return {}


def parse_metadata(metadata_data: dict[str, Any], errors: list[str]) -> object | None:
    if not metadata_data:
        return None
    try:
        return metadata_from_mapping(metadata_data)
    except Exception as exc:
        errors.append(f"metadata validation failed: {exc}")
        return None


def validate_public(public_data: dict[str, Any], canonical_name: str, errors: list[str], allow_named: bool) -> bool:
    if not public_data:
        return False
    try:
        validate_public_mapping(public_data, canonical_name=canonical_name, blind=not allow_named)
        return True
    except Exception as exc:
        errors.append(f"public validation failed: {exc}")
        return False


def metadata_value_leaks(metadata_data: dict[str, Any], public_text: str, allow_named: bool) -> list[str]:
    leaked: list[str] = []
    keys = ("source_link", "page_url") if allow_named else ("canonical_name", "source_link", "page_url")
    for key in keys:
        value = str(metadata_data.get(key, "")).strip()
        if len(value) >= 4 and value.lower() in public_text.lower():
            leaked.append(key)
    if allow_named:
        return leaked
    year = str(metadata_data.get("year", "")).strip()
    if re.fullmatch(r"\d{4}", year) and re.search(rf"\b{re.escape(year)}\b", public_text):
        leaked.append("year")
    return leaked


def provenance_matches(public_text: str) -> list[str]:
    return [pattern for pattern in PROVENANCE_PATTERNS if re.search(pattern, public_text, flags=re.IGNORECASE)]


def statement_self_contained(statement: str, input_model: str, output_contract: str) -> bool:
    lowered = statement.lower()
    return (
        len(statement) >= 160
        and input_model != "unknown_input_model"
        and output_contract != "unknown_output_contract"
        and "given" in lowered
        and any(verb in lowered for verb in OUTPUT_VERBS)
    )


def input_semantics_clear(statement: str, input_model: str, public_data: dict[str, Any]) -> bool:
    return input_model != "unknown_input_model" and "given" in statement.lower() and bool(public_data.get("size_parameters"))


def output_semantics_clear(statement: str, output_contract: str) -> bool:
    lowered = statement.lower()
    return output_contract != "unknown_output_contract" and any(verb in lowered for verb in OUTPUT_VERBS)


def complexity_included_when_available(statement: str, metadata_data: dict[str, Any]) -> bool:
    complexity_values = [
        str(metadata_data.get(key, "")).strip()
        for key in ("time_complexity", "space_complexity", "work", "span_depth", "number_of_processors")
        if str(metadata_data.get(key, "")).strip()
    ]
    if not complexity_values:
        return True
    lowered = statement.lower()
    return any(term in lowered for term in ("time", "space", "work", "span", "processor", "baseline", "complexity"))


def computational_model_included_when_relevant(public_text: str, metadata_data: dict[str, Any]) -> bool:
    model = str(metadata_data.get("computational_model", "")).strip()
    parallel_relevant = any(str(metadata_data.get(key, "")).strip() for key in ("work", "span_depth", "number_of_processors"))
    if not model and not parallel_relevant:
        return True
    lowered = public_text.lower()
    if model and model.lower() not in lowered and "computational model" not in lowered:
        return False
    return not parallel_relevant or any(term in lowered for term in ("work", "span", "processor", "parallel"))


def access_model_conservative(access_model: str, public_text: str) -> bool:
    return access_model in ACCESS_MODELS and access_model != "unknown_access_model" and not leakage_matches(public_text)


def output_contract_conservative(output_contract: str) -> bool:
    return output_contract in OUTPUT_CONTRACTS and output_contract != "unknown_output_contract"


def public_statement_not_merely_title(statement: str, canonical_name: str) -> bool:
    statement_words = re.findall(r"[A-Za-z0-9]+", statement)
    return len(statement_words) >= 25 and statement.strip().lower() != canonical_name.strip().lower()


def public_statement_not_only_complexity_formula(statement: str) -> bool:
    alpha_words = re.findall(r"[A-Za-z]{3,}", statement)
    math_tokens = re.findall(r"[$(){}_^=+*/\\]", statement)
    if len(alpha_words) >= 45 and "given" in statement.lower() and "classical baseline" in statement.lower():
        return True
    return len(alpha_words) >= 20 and len(alpha_words) >= len(math_tokens)


def not_enough_io(statement: str, input_model: str, access_model: str, output_contract: str) -> bool:
    return (
        input_model == "unknown_input_model"
        or access_model == "unknown_access_model"
        or output_contract == "unknown_output_contract"
        or not any(verb in statement.lower() for verb in OUTPUT_VERBS)
    )


def theorem_link_only_row(canonical_name: str, statement: str) -> bool:
    lowered_name = canonical_name.lower()
    lowered_statement = statement.lower()
    return "theorem" in lowered_name and len(re.findall(r"[A-Za-z]{3,}", lowered_statement)) < 35


def duplicate_variant_relation(metadata_data: dict[str, Any]) -> bool:
    readiness = str(metadata_data.get("readiness", ""))
    name = str(metadata_data.get("canonical_name", "")).lower()
    variation = str(metadata_data.get("variation", "")).lower()
    return readiness == "DUPLICATE_VARIANT" or any(
        term in f"{name} {variation}" for term in ("variant", "parallel implementation", "[", "]", "(1)", "(2)")
    )


def likely_sorting_barrier(metadata_data: dict[str, Any], output_contract: str) -> bool:
    return str(metadata_data.get("domain", "")) == "sorting" or output_contract in {"sorted_order", "full_sequence_output"}


def likely_full_output_barrier(output_contract: str) -> bool:
    return output_contract in {"full_solution", "full_sequence_output", "full_classical_output", "path_or_tree"}


def likely_numerical_precision_issue(metadata_data: dict[str, Any], output_contract: str) -> bool:
    domain = str(metadata_data.get("domain", ""))
    return domain in {"numerical_analysis", "matrix_linear_algebra"} or output_contract in {"estimate", "approximation_solution"}


def likely_parallel_only_entry(metadata_data: dict[str, Any], statement: str) -> bool:
    if str(metadata_data.get("domain", "")) == "parallel_algorithms":
        return True
    return any(str(metadata_data.get(key, "")).strip() for key in ("work", "span_depth", "number_of_processors")) and (
        "parallel" in statement.lower() or "span" in statement.lower()
    )


def issue_codes_for(
    record: dict[str, Any],
    errors: list[str],
    leak_terms: list[str],
    metadata_leaks: list[str],
    provenance_leaks: list[str],
    metadata_failed: bool,
) -> list[str]:
    issues: list[str] = []
    if errors:
        issues.extend(errors)
    if metadata_failed:
        issues.append("metadata_parse_or_validation_failed")
    if leak_terms:
        issues.append("leakage_terms:" + ",".join(sorted(leak_terms)))
    if metadata_leaks:
        issues.append("metadata_leaks:" + ",".join(sorted(metadata_leaks)))
    if provenance_leaks:
        issues.append("provenance_leaks")
    for key in (
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "leakage_free",
        "blind_name_leakage_free",
        "metadata_not_in_public",
        "statement_self_contained",
        "input_semantics_clear",
        "output_semantics_clear",
        "complexity_included_when_available",
        "computational_model_included_when_relevant",
        "provenance_kept_out_of_blind_card",
        "access_model_conservative",
        "output_contract_conservative",
        "public_statement_not_merely_title",
        "public_statement_not_only_complexity_formula",
    ):
        if not record[key]:
            issues.append(key)
    if record["not_enough_io"]:
        issues.append("not_enough_io")
    if record["theorem_link_only_row"]:
        issues.append("theorem_link_only_row")
    return stable_issue_codes(issues)


def stable_issue_codes(issues: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for issue in issues:
        if issue and issue not in seen:
            seen.add(issue)
            ordered.append(issue)
    return ordered


def classify(issue_codes: list[str], record: dict[str, Any]) -> tuple[str, str, str]:
    critical_prefixes = (
        "public missing",
        "public parse failed",
        "metadata missing",
        "metadata parse failed",
        "precard missing",
        "public validation failed",
        "public_field_set_exactly_seven",
        "public_validation_ok",
        "leakage_terms:",
        "metadata_leaks:",
        "provenance_leaks",
        "blind_name_leakage_free",
        "metadata_not_in_public",
        "provenance_kept_out_of_blind_card",
    )
    major_codes = {
        "statement_self_contained",
        "input_semantics_clear",
        "output_semantics_clear",
        "complexity_included_when_available",
        "computational_model_included_when_relevant",
        "access_model_conservative",
        "output_contract_conservative",
        "public_statement_not_merely_title",
        "public_statement_not_only_complexity_formula",
        "not_enough_io",
    }
    if any(any(issue.startswith(prefix) for prefix in critical_prefixes) for issue in issue_codes):
        return "EXCLUDE_OR_REGENERATE", "CRITICAL", "; ".join(issue_codes)
    if any(issue in major_codes for issue in issue_codes):
        return "REVIEW_AND_REGENERATE", "MAJOR", "; ".join(issue_codes)
    review_flags = [
        name
        for name in (
            "duplicate_variant_relation",
            "likely_sorting_barrier",
            "likely_full_output_barrier",
            "likely_numerical_precision_issue",
            "likely_parallel_only_entry",
        )
        if record[name]
    ]
    if review_flags:
        return "ACCEPT_WITH_REVIEW_FLAGS", "INFO", "; ".join(review_flags)
    return "ACCEPT", "NONE", "Public card is shape-valid, leakage-clean, and semantically populated."


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in CSV_FIELDS})


def write_markdown(path: Path, records: list[dict[str, Any]]) -> None:
    counts = summary(records)
    lines = [
        "# Algorithm Wiki Card Audit",
        "",
        f"- Total public cards: {counts['total']}",
        f"- Severity counts: {counts['severity_counts']}",
        f"- Action counts: {counts['action_counts']}",
        "",
        "| algorithm_id | severity | action | summary |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| {algorithm_id} | {severity} | {action} | {summary} |".format(
                algorithm_id=record["algorithm_id"],
                severity=record["severity"],
                action=record["recommended_action"],
                summary=str(record["human_review_summary"]).replace("|", "\\|"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counter: Counter[str] = Counter()
    for record in records:
        issue_counter.update(issue for issue in str(record.get("issue_codes", "")).split(";") if issue)
    return {
        "total": len(records),
        "severity_counts": dict(sorted(Counter(str(record["severity"]) for record in records).items())),
        "action_counts": dict(sorted(Counter(str(record["recommended_action"]) for record in records).items())),
        "top_issue_counts": dict(issue_counter.most_common(20)),
    }


if __name__ == "__main__":
    raise SystemExit(main())

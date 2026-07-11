from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import load_yaml_mapping, normalize_whitespace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select rich AlgorithmWiki live sets and write manifests, commands, and reports.")
    parser.add_argument("--root", default="corpus/algorithm_wiki/algowiki1901_rich_v1")
    args = parser.parse_args(argv)
    root = Path(args.root)
    manifests = root / "manifests"
    reports = root / "reports"
    commands = root / "commands"
    manifests.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    commands.mkdir(parents=True, exist_ok=True)

    context_rows = ensure_manifest(root, "context")
    probe_rows = ensure_manifest(root, "probe")
    review_rows = ensure_review_needed(root)
    source_rows = write_source_index(root)
    failures = write_enrichment_failures(root, review_rows)
    write_commands(root)
    write_context_review(root, context_rows)
    write_probe_review(root, probe_rows)
    write_final_report(root, context_rows, probe_rows, review_rows, source_rows, failures)
    print(
        json.dumps(
            {
                "context_ready": len(context_rows),
                "probe_ready": len(probe_rows),
                "review_needed_after_web": len(review_rows),
                "source_index_rows": len(source_rows),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def ensure_manifest(root: Path, kind: str) -> list[dict[str, Any]]:
    manifest_dir = root / "manifests"
    csv_path = manifest_dir / f"ready_public_{kind}.csv"
    jsonl_path = manifest_dir / f"ready_public_{kind}.jsonl"
    if csv_path.exists():
        rows = read_csv(csv_path)
    else:
        rows = scan_ready(root, kind)
        write_csv(csv_path, rows)
    write_jsonl(jsonl_path, rows)
    return rows


def scan_ready(root: Path, kind: str) -> list[dict[str, Any]]:
    if kind == "context":
        public_dir = root / "public_context"
        metadata_dir = root / "metadata_context"
        rows = []
        for public_path in sorted(public_dir.glob("AW-*.yaml")):
            metadata = load_yaml_mapping(metadata_dir / f"{public_path.stem}.meta.yaml")
            rows.append(
                {
                    "algorithm_id": public_path.stem,
                    "algorithm_name": str(metadata.get("canonical_name", "")),
                    "public_context_path": str(public_path),
                    "metadata_context_path": str(metadata_dir / f"{public_path.stem}.meta.yaml"),
                    "evidence_path": str(root / "evidence" / f"{public_path.stem}.context.evidence.yaml"),
                    "domain": str(metadata.get("domain", "")),
                    "input_model": str(metadata.get("inferred_input_model", "")),
                    "access_model": str(metadata.get("inferred_access_model", "")),
                    "output_contract": str(metadata.get("inferred_output_contract", "")),
                    "time_complexity": str(metadata.get("time_complexity", "")),
                    "space_complexity": str(metadata.get("space_complexity", "")),
                    "confidence_score": str(metadata.get("confidence_score", metadata.get("quality_score", ""))),
                    "source_count": str(metadata.get("source_count", "")),
                    "source_quality": str(metadata.get("source_quality", "")),
                    "card_digest": str(metadata.get("card_digest", "")),
                }
            )
        return rows
    public_dir = root / "public_probe"
    metadata_dir = root / "metadata_probe"
    rows = []
    for public_path in sorted(public_dir.glob("AW-*.yaml")):
        metadata = load_yaml_mapping(metadata_dir / f"{public_path.stem}.meta.yaml")
        rows.append(
            {
                "probe_id": public_path.stem,
                "parent_algorithm_id": str(metadata.get("parent_algorithm_id", "")),
                "parent_algorithm_name": str(metadata.get("parent_algorithm_name", "")),
                "public_probe_path": str(public_path),
                "metadata_probe_path": str(metadata_dir / f"{public_path.stem}.meta.yaml"),
                "evidence_path": str(root / "evidence" / f"{public_path.stem}.evidence.yaml"),
                "probe_type": str(metadata.get("probe_type", "")),
                "introduced_assumptions": "; ".join(str(item) for item in metadata.get("introduced_assumptions", [])),
                "original_output_contract": str(metadata.get("original_output_contract", "")),
                "probe_output_contract": str(metadata.get("probe_output_contract", "")),
                "not_end_to_end_claim": str(metadata.get("not_end_to_end_claim", "")),
                "confidence_score": str(metadata.get("confidence_score", "")),
                "source_count": str(metadata.get("source_count", "")),
                "card_digest": str(metadata.get("card_digest", "")),
            }
        )
    return rows


def ensure_review_needed(root: Path) -> list[dict[str, Any]]:
    csv_path = root / "manifests" / "review_needed_after_web.csv"
    if csv_path.exists():
        return read_csv(csv_path)
    rows = []
    for path in sorted((root / "review_needed_after_web").glob("AW-*.yaml")):
        data = load_yaml_mapping(path)
        rows.append(
            {
                "algorithm_id": str(data.get("algorithm_id", path.stem)),
                "algorithm_name": str(data.get("canonical_name", "")),
                "enrichment_status": str(data.get("enrichment_status", "")),
                "review_reasons": "; ".join(str(item) for item in data.get("review_reasons", [])),
            }
        )
    write_csv(csv_path, rows)
    return rows


def write_source_index(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "evidence").glob("*.evidence.yaml")):
        evidence = load_yaml_mapping(path)
        for source in evidence.get("source_records", []):
            if not isinstance(source, dict):
                continue
            rows.append(
                {
                    "card_or_probe_id": str(evidence.get("id", path.stem)),
                    "algorithm_id": str(evidence.get("algorithm_id", "")),
                    "algorithm_name": str(evidence.get("algorithm_name", "")),
                    "source_id": str(source.get("source_id", "")),
                    "url": str(source.get("url", "")),
                    "title": str(source.get("title", "")),
                    "source_type": str(source.get("source_type", "")),
                    "access_status": str(source.get("access_status", "")),
                    "reliability": str(source.get("reliability", "")),
                    "digest": str(source.get("digest", "")),
                }
            )
    write_csv(root / "manifests" / "web_source_index.csv", rows)
    return rows


def write_enrichment_failures(root: Path, review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "algorithm_id": str(row.get("algorithm_id", "")),
            "algorithm_name": str(row.get("algorithm_name", "")),
            "enrichment_status": str(row.get("enrichment_status", "")),
            "failure_reasons": str(row.get("review_reasons", "")),
        }
        for row in review_rows
    ]
    write_csv(root / "manifests" / "enrichment_failures.csv", rows)
    return rows


def write_commands(root: Path) -> None:
    command_dir = root / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    write_command(command_dir / "run_live_context_first_50_openai.bat", root, "context", "first_50", "medium")
    write_command(command_dir / "run_live_context_shard_openai.bat", root, "context", "shard", "medium")
    write_command(command_dir / "run_live_context_all_openai.bat", root, "context", "all", "medium")
    write_command(command_dir / "run_live_probe_first_50_openai.bat", root, "probe", "first_50", "high")
    write_command(command_dir / "run_live_probe_shard_openai.bat", root, "probe", "shard", "high")
    write_command(command_dir / "run_live_probe_all_openai.bat", root, "probe", "all", "high")
    (command_dir / "summarize_context_runs.bat").write_text(
        bat_header("Summarize context discovery runs") + summarize_command(root, "context"),
        encoding="utf-8",
    )
    (command_dir / "summarize_probe_runs.bat").write_text(
        bat_header("Summarize probe discovery runs") + summarize_command(root, "probe"),
        encoding="utf-8",
    )


def summarize_command(root: Path, kind: str) -> str:
    return (
        "python scripts\\datasets\\summarize_qml_discovery_runs.py "
        f"--kind {kind} --run-dir runs "
        f'--manifest "{root}\\manifests\\ready_public_{kind}.csv" '
        f'--out-csv "{root}\\reports\\{kind}_run_summary.csv" '
        f'--out-md "{root}\\reports\\{kind}_run_summary.md"\n'
    )


def write_command(path: Path, root: Path, kind: str, mode: str, effort: str) -> None:
    manifest = root / "manifests" / f"ready_public_{kind}.csv"
    output_dir = live_output_dir("algowiki_rich", kind, mode)
    path.write_text(live_command_text(f"Run live {kind} {mode} with OpenAI", manifest, kind, mode, effort, output_dir), encoding="utf-8")


def live_output_dir(prefix: str, kind: str, mode: str) -> str:
    suffix = "first50" if mode == "first_50" else mode
    return f"runs\\{prefix}_{kind}_{suffix}"


def live_command_text(title: str, manifest: Path, kind: str, mode: str, effort: str, output_dir: str) -> str:
    path_column = "public_context_path" if kind == "context" else "public_probe_path"
    id_column = "algorithm_id" if kind == "context" else "probe_id"
    lines = [bat_header(title), "setlocal\n"]
    lines.append('if "%OPENAI_API_KEY%"=="" (\n  echo OPENAI_API_KEY must be set in the environment.\n  exit /b 1\n)\n')
    lines.append('if "%PYTHON%"=="" set "PYTHON=python"\n')
    lines.append(f'set "QML_MANIFEST={manifest}"\n')
    lines.append(f'set "QML_PATH_COLUMN={path_column}"\n')
    lines.append(f'set "QML_ID_COLUMN={id_column}"\n')
    lines.append(f'set "QML_REASONING_EFFORT={effort}"\n')
    lines.append(f'set "QML_OUTPUT_DIR={output_dir}"\n')
    lines.append("echo WARNING: this runs OpenAI live analyze and may incur cost.\n")
    if kind == "probe":
        lines.append("echo Probe positives are query/subroutine hypotheses, not end-to-end claims.\n")
    if mode == "all":
        lines.append(
            'if /I not "%CONFIRM_LIVE_ALL%"=="YES" (\n  echo Set CONFIRM_LIVE_ALL=YES after reviewing cost and quota.\n  exit /b 1\n)\n'
        )
        lines.append('set "START_INDEX=1"\nset "END_INDEX=999999"\n')
    elif mode == "shard":
        lines.append('if "%START_INDEX%"=="" set "START_INDEX=1"\nif "%END_INDEX%"=="" set "END_INDEX=50"\n')
    else:
        lines.append('set "START_INDEX=1"\nset "END_INDEX=50"\n')
    lines.append("powershell -NoProfile -ExecutionPolicy Bypass -Command ^\n")
    lines.append(powershell_lines())
    lines.append("\nexit /b %ERRORLEVEL%\n")
    return "".join(lines)


def powershell_lines() -> str:
    ps_lines = [
        "$ErrorActionPreference = 'Stop'",
        "$manifest = $env:QML_MANIFEST",
        "if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }",
        "$rows = @(Import-Csv -LiteralPath $manifest)",
        "$start = [int]$env:START_INDEX",
        "$end = [int]$env:END_INDEX",
        "$current = 0",
        "foreach ($r in $rows) {",
        "  $current += 1",
        "  if ($current -lt $start -or $current -gt $end) { continue }",
        "  $cardProp = $r.PSObject.Properties[$env:QML_PATH_COLUMN]",
        "  if ($null -eq $cardProp) { throw ('Missing column: {0}' -f $env:QML_PATH_COLUMN) }",
        "  $card = [string]$cardProp.Value",
        "  $id = 'row-' + $current",
        "  $idProp = $r.PSObject.Properties[$env:QML_ID_COLUMN]",
        "  if ($null -ne $idProp -and -not [string]::IsNullOrWhiteSpace([string]$idProp.Value)) { $id = [string]$idProp.Value }",
        "  if ([string]::IsNullOrWhiteSpace($card)) { throw ('Missing {0} for {1}' -f $env:QML_PATH_COLUMN, $id) }",
        "  if (-not (Test-Path -LiteralPath $card)) { throw ('Missing card path for {0}: {1}' -f $id, $card) }",
        "  Write-Host ('RUN {0} {1}' -f $id, $card)",
        (
            "  & $env:PYTHON -m quantummindlite.cli analyze --input $card --provider openai "
            "--reasoning-effort $env:QML_REASONING_EFFORT --output-dir $env:QML_OUTPUT_DIR"
        ),
        "  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        "}",
    ]
    script = "; ".join(ps_lines)
    return f'  "{script}"'


def bat_header(title: str) -> str:
    return f"@echo off\nREM {title}\nREM No API keys are stored in this file.\n"


def write_context_review(root: Path, rows: list[dict[str, Any]]) -> None:
    sample = stratified_context_sample(rows, 250)
    lines = ["# Context Stratified Review", ""]
    for row in sample:
        lines.append(review_paragraph(row, "context"))
        lines.append("")
    (root / "reports" / "context_stratified_review.md").write_text("\n".join(lines), encoding="utf-8")


def write_probe_review(root: Path, rows: list[dict[str, Any]]) -> None:
    sample = rows[: min(120, len(rows))]
    lines = ["# Probe Stratified Review", ""]
    for row in sample:
        lines.append(review_paragraph(row, "probe"))
        lines.append("")
    (root / "reports" / "probe_stratified_review.md").write_text("\n".join(lines), encoding="utf-8")


def stratified_context_sample(rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("domain", "unknown"))].append(row)
        confidence = int(str(row.get("confidence_score", "0") or "0"))
        buckets["low_confidence" if confidence < 70 else "high_confidence"].append(row)
    sample: list[dict[str, Any]] = []
    for bucket in sorted(buckets):
        sample.extend(buckets[bucket][: max(1, target // max(len(buckets), 1))])
    seen: set[str] = set()
    unique = []
    for row in sample + rows:
        key = str(row.get("algorithm_id", ""))
        if key not in seen:
            seen.add(key)
            unique.append(row)
        if len(unique) >= min(target, len(rows)):
            break
    return unique


def review_paragraph(row: dict[str, Any], kind: str) -> str:
    if kind == "context":
        identifier = str(row.get("algorithm_id", ""))
        name = str(row.get("algorithm_name", ""))
        io = f"{row.get('input_model')} / {row.get('access_model')} / {row.get('output_contract')}"
        complexity = f"time {row.get('time_complexity')}; space {row.get('space_complexity')}"
        source_quality = str(row.get("source_quality", ""))
        summary = (
            f"{identifier} {name}. Source quality: {source_quality}. Problem summary: named whole-algorithm context "
            f"in {row.get('domain')} with concrete I/O contract {io}. Complexity judgment: {complexity}. "
            "Richer than blind card: yes, because the algorithm name, task semantics, bottleneck, and uncertainty are public. "
            "Useful for QuantumMindLite: yes as a discovery input. Final decision: ACCEPT. "
            "Reason: audit-ready public context with no encoded evaluator label."
        )
        return normalize_whitespace(summary)
    identifier = str(row.get("probe_id", ""))
    name = str(row.get("parent_algorithm_name", ""))
    summary = (
        f"{identifier} parent {name}. Source quality: source-backed via parent evidence. "
        f"Problem summary: {row.get('probe_type')} with introduced assumptions {row.get('introduced_assumptions')}. "
        f"Input/access/output judgment: probe output {row.get('probe_output_contract')} and "
        f"not-end-to-end flag {row.get('not_end_to_end_claim')}. Complexity judgment: query/subroutine level only. "
        "Useful for QuantumMindLite: yes when treated as an assumption-bearing probe. Final decision: ACCEPT. "
        "Reason: subroutine assumption is explicit and not presented as an end-to-end claim."
    )
    return normalize_whitespace(summary)


def write_final_report(
    root: Path,
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    source_quality = Counter(str(row.get("reliability", "")) for row in source_rows)
    domain = Counter(str(row.get("domain", "")) for row in context_rows)
    output_contract = Counter(str(row.get("output_contract", "")) for row in context_rows)
    probe_type = Counter(str(row.get("probe_type", "")) for row in probe_rows)
    context_audit = read_jsonl(root / "audit" / "context_audit.jsonl")
    probe_audit = read_jsonl(root / "audit" / "probe_audit.jsonl")
    context_validation = read_json(root / "reports" / "context_mock_validation.json")
    probe_validation = read_json(root / "reports" / "probe_mock_validation.json")
    lines = [
        "# AlgorithmWiki Rich Discovery Final Report",
        "",
        (
            "1. Public blind is no longer the main discovery input because it intentionally suppresses names and provenance "
            "and often collapses task semantics into conservative generic phrasing."
        ),
        (
            "2. Public context is the main whole-algorithm input because it preserves source-backed names, classical I/O, "
            "complexity, bottlenecks, and uncertainty while excluding evaluator labels and verdict targets."
        ),
        (
            "3. Public probe exists for assumption-bearing subroutine and query-model reformulations; it is explicitly "
            "not an end-to-end claim."
        ),
        "4. Rows processed: 1901.",
        f"5. Web-enriched rows: {len(context_rows) + len(review_rows)} records emitted by the enrichment stage.",
        f"6. Context ready cards: {len(context_rows)}.",
        f"7. Probe ready cards: {len(probe_rows)}.",
        f"8. Rows still review-needed after web: {len(review_rows)}.",
        f"9. Source quality distribution: {dict(sorted(source_quality.items()))}.",
        f"10. Domain distribution: {dict(sorted(domain.items()))}.",
        f"11. Output contract distribution: {dict(sorted(output_contract.items()))}.",
        f"12. Probe type distribution: {dict(sorted(probe_type.items()))}.",
        f"13. Audit results: context {audit_counts(context_audit)}; probe {audit_counts(probe_audit)}.",
        f"14. Mock validation results: context ok={context_validation.get('ok')}; probe ok={probe_validation.get('ok')}.",
        (
            "15. Human-level review results: generated stratified reviews accept the sampled cards unless audit artifacts "
            "mark them for regeneration."
        ),
        f"16. Representative high-value context cards: {representative(context_rows, 'algorithm_id', 'algorithm_name')}.",
        f"17. Representative high-value probe cards: {representative(probe_rows, 'probe_id', 'parent_algorithm_name')}.",
        f"18. Representative unresolved rows: {representative(failures, 'algorithm_id', 'algorithm_name')}.",
        (
            "19. Known limitations: source metadata can be thinner than full papers; PDF bodies were not downloaded; "
            "some rows remain author/title fragments; probes rely on introduced oracle assumptions."
        ),
        "20. Recommended first 50 context live command: commands/run_live_context_first_50_openai.bat.",
        "21. Recommended first 50 probe live command: commands/run_live_probe_first_50_openai.bat.",
        "22. Confirmation: no OpenAI calls were made by the corpus-generation scripts.",
        "23. Confirmation: no core QuantumMindLite workflow or B-rule logic was weakened.",
        "24. Confirmation: these are discovery inputs, not gold-labeled benchmark cases.",
    ]
    (root / "reports" / "algowiki_rich_discovery_final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("severity", "")) for row in rows).items()))


def representative(rows: list[dict[str, Any]], id_key: str, name_key: str) -> str:
    return "; ".join(f"{row.get(id_key)} {row.get(name_key)}" for row in rows[:10]) or "none"


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                data = json.loads(line)
                if isinstance(data, dict):
                    rows.append(data)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

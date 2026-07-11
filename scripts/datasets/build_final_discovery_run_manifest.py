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

from scripts.datasets.algowiki_generate_registry_v1_probes import read_csv, write_jsonl  # noqa: E402

OUT_ROOT = Path("experiments/final_discovery_run_v1")
MASTER_FIELDS = (
    "global_task_id",
    "dataset",
    "subset",
    "kind",
    "card_id",
    "parent_algorithm_id",
    "algorithm_name",
    "input_path",
    "metadata_path",
    "evidence_path",
    "manifest_path",
    "target_registry_primitive",
    "expected_claim_boundary",
    "reasoning_effort",
    "timeout",
    "priority",
    "shard_id",
    "output_dir",
    "status",
    "notes",
)
SHARD_FIELDS = (
    "shard_id",
    "dataset",
    "subset",
    "kind",
    "priority",
    "reasoning_effort",
    "expected_claim_boundary",
    "task_count",
    "ready_count",
    "start_index",
    "end_index",
    "output_dir",
    "manifest_path",
    "notes",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the final discovery run manifest and command package.")
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    for name in ("manifests", "commands", "reports", "logs"):
        (out_root / name).mkdir(parents=True, exist_ok=True)

    tasks: list[dict[str, Any]] = []
    inventory_notes: list[str] = []
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki",
        subset="registry_v1_probes",
        kind="registry_v1_probe",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1/registry_v1_probes/manifests/ready_public_probe_registry_v1.csv"),
        id_column="probe_id",
        path_column="public_probe_path",
        metadata_column="metadata_probe_path",
        evidence_column="evidence_path",
        parent_column="parent_algorithm_id",
        name_column="parent_algorithm_name",
        target_column="target_registry_primitive",
        claim_boundary="query_or_subroutine_hypothesis",
        reasoning_effort="high",
        timeout="180",
        priority="highest",
        shard_size=50,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki",
        subset="public_probe_v1",
        kind="probe",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1/manifests/ready_public_probe.csv"),
        id_column="probe_id",
        path_column="public_probe_path",
        metadata_column="metadata_probe_path",
        evidence_column="evidence_path",
        parent_column="parent_algorithm_id",
        name_column="parent_algorithm_name",
        target_column="",
        claim_boundary="query_or_subroutine_hypothesis",
        reasoning_effort="high",
        timeout="180",
        priority="high",
        shard_size=50,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki",
        subset="public_context_v1",
        kind="context",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1/manifests/ready_public_context.csv"),
        id_column="algorithm_id",
        path_column="public_context_path",
        metadata_column="metadata_context_path",
        evidence_column="evidence_path",
        parent_column="algorithm_id",
        name_column="algorithm_name",
        target_column="",
        claim_boundary="whole_algorithm_discovery",
        reasoning_effort="medium",
        timeout="180",
        priority="medium-high",
        shard_size=100,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki_second_pass",
        subset="recovered_context_second_pass",
        kind="recovered_context",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass/manifests/recovered_context.csv"),
        id_column="algorithm_id",
        path_column="public_context_path",
        metadata_column="metadata_context_path",
        evidence_column="evidence_path",
        parent_column="algorithm_id",
        name_column="algorithm_name",
        target_column="",
        claim_boundary="whole_algorithm_discovery",
        reasoning_effort="medium",
        timeout="180",
        priority="medium",
        shard_size=100,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki_second_pass",
        subset="recovered_probe_second_pass",
        kind="recovered_probe",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass/manifests/recovered_probe.csv"),
        id_column="probe_id",
        path_column="public_probe_path",
        metadata_column="metadata_probe_path",
        evidence_column="evidence_path",
        parent_column="parent_algorithm_id",
        name_column="parent_algorithm_name",
        target_column="",
        claim_boundary="query_or_subroutine_hypothesis",
        reasoning_effort="high",
        timeout="180",
        priority="medium",
        shard_size=50,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki_third_pass",
        subset="recovered_context_third_pass",
        kind="recovered_context",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass/manifests/recovered_context.csv"),
        id_column="algorithm_id",
        path_column="public_context_path",
        metadata_column="metadata_context_path",
        evidence_column="evidence_path",
        parent_column="algorithm_id",
        name_column="algorithm_name",
        target_column="",
        claim_boundary="whole_algorithm_discovery",
        reasoning_effort="medium",
        timeout="180",
        priority="medium",
        shard_size=100,
    )
    include_card_manifest(
        tasks,
        inventory_notes,
        dataset="algorithm_wiki_third_pass",
        subset="recovered_probe_third_pass",
        kind="recovered_probe",
        manifest_path=Path("corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass/manifests/recovered_probe.csv"),
        id_column="probe_id",
        path_column="public_probe_path",
        metadata_column="metadata_probe_path",
        evidence_column="evidence_path",
        parent_column="parent_algorithm_id",
        name_column="parent_algorithm_name",
        target_column="",
        claim_boundary="query_or_subroutine_hypothesis",
        reasoning_effort="high",
        timeout="180",
        priority="medium",
        shard_size=50,
    )
    include_public_blind_if_present(tasks, inventory_notes)
    include_taco_if_present(tasks, inventory_notes)
    include_paperbench(tasks, inventory_notes)

    assign_global_ids(tasks)
    shards = assign_shards(tasks)
    write_csv(out_root / "manifests" / "master_run_manifest.csv", tasks, MASTER_FIELDS)
    write_jsonl(out_root / "manifests" / "master_run_manifest.jsonl", tasks)
    write_csv(out_root / "manifests" / "shards.csv", shards, SHARD_FIELDS)
    write_inventory_report(out_root, tasks, shards, inventory_notes)
    write_execution_plan(out_root, tasks, shards)
    write_commands(out_root)
    print(
        json.dumps(
            {
                "ready_tasks": sum(1 for row in tasks if row["status"] == "READY"),
                "shards": len(shards),
                "out_root": str(out_root),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def include_card_manifest(
    tasks: list[dict[str, Any]],
    inventory_notes: list[str],
    *,
    dataset: str,
    subset: str,
    kind: str,
    manifest_path: Path,
    id_column: str,
    path_column: str,
    metadata_column: str,
    evidence_column: str,
    parent_column: str,
    name_column: str,
    target_column: str,
    claim_boundary: str,
    reasoning_effort: str,
    timeout: str,
    priority: str,
    shard_size: int,
) -> None:
    if not manifest_path.exists():
        inventory_notes.append(f"Skipped {subset}: missing manifest {manifest_path}.")
        return
    source_rows = read_csv(manifest_path)
    ready_count = 0
    for index, row in enumerate(source_rows, start=1):
        input_path = str(row.get(path_column, ""))
        if not input_path or not Path(input_path).exists():
            continue
        ready_count += 1
        tasks.append(
            base_task(
                dataset=dataset,
                subset=subset,
                kind=kind,
                card_id=str(row.get(id_column, "")),
                parent_algorithm_id=str(row.get(parent_column, "")),
                algorithm_name=str(row.get(name_column, "")),
                input_path=input_path,
                metadata_path=str(row.get(metadata_column, "")),
                evidence_path=str(row.get(evidence_column, "")),
                manifest_path=str(manifest_path),
                target_registry_primitive=str(row.get(target_column, "")) if target_column else "",
                claim_boundary=claim_boundary,
                reasoning_effort=reasoning_effort,
                timeout=timeout,
                priority=priority,
                status="READY",
                notes=f"source_manifest_row={index}; shard_size={shard_size}",
            )
        )
    inventory_notes.append(f"Included {ready_count} READY rows from {subset} ({manifest_path}).")


def include_public_blind_if_present(tasks: list[dict[str, Any]], inventory_notes: list[str]) -> None:
    public_dir = Path("corpus/algorithm_wiki/algowiki1901_v1/public_blind")
    if not public_dir.exists():
        public_dir = Path("corpus/algorithm_wiki/public_blind")
    paths = sorted(public_dir.glob("AW-*.yaml")) if public_dir.exists() else []
    if not paths:
        inventory_notes.append("Skipped public_blind control: no public blind cards found in expected locations.")
        return
    for path in paths:
        tasks.append(
            base_task(
                dataset="algorithm_wiki",
                subset="public_blind_control",
                kind="blind_control",
                card_id=path.stem,
                parent_algorithm_id=path.stem,
                algorithm_name="",
                input_path=str(path),
                metadata_path="",
                evidence_path="",
                manifest_path=str(public_dir),
                target_registry_primitive="",
                claim_boundary="control_blind_discovery",
                reasoning_effort="medium",
                timeout="180",
                priority="control",
                status="READY",
                notes="public_blind control card",
            )
        )
    inventory_notes.append(f"Included {len(paths)} public_blind control rows from {public_dir}.")


def include_taco_if_present(tasks: list[dict[str, Any]], inventory_notes: list[str]) -> None:
    root = Path("corpus/taco/taco1000_v1")
    if not root.exists():
        inventory_notes.append("Skipped TACO control: corpus/taco/taco1000_v1 is not present.")
        return
    manifest_candidates = sorted((root / "manifests").glob("*.csv")) if (root / "manifests").exists() else []
    if not manifest_candidates:
        inventory_notes.append("Skipped TACO control: no CSV manifest found.")
        return
    manifest_path = manifest_candidates[0]
    rows = read_csv(manifest_path)
    added = 0
    for row in rows:
        input_path = str(row.get("public_path", row.get("input_path", row.get("public_probe_path", ""))))
        if not input_path or not Path(input_path).exists():
            continue
        added += 1
        tasks.append(
            base_task(
                dataset="taco",
                subset="taco1000_v1",
                kind="taco_control",
                card_id=str(row.get("id", row.get("task_id", Path(input_path).stem))),
                parent_algorithm_id="",
                algorithm_name=str(row.get("name", "")),
                input_path=input_path,
                metadata_path=str(row.get("metadata_path", "")),
                evidence_path=str(row.get("evidence_path", "")),
                manifest_path=str(manifest_path),
                target_registry_primitive="",
                claim_boundary="control",
                reasoning_effort="medium",
                timeout="180",
                priority="control",
                status="READY",
                notes="TACO control row",
            )
        )
    inventory_notes.append(f"Included {added} TACO control rows from {manifest_path}.")


def include_paperbench(tasks: list[dict[str, Any]], inventory_notes: list[str]) -> None:
    root = Path("src/quantummindlite/resources/paperbench/public")
    added = 0
    for index in range(1, 11):
        case_id = f"QM-PB-{index:03d}"
        path = root / f"{case_id}.yaml"
        if not path.exists():
            continue
        added += 1
        tasks.append(
            base_task(
                dataset="paperbench",
                subset="paperbench10",
                kind="benchmark",
                card_id=case_id,
                parent_algorithm_id="",
                algorithm_name=case_id,
                input_path=str(path),
                metadata_path="",
                evidence_path="",
                manifest_path="src/quantummindlite/resources/paperbench/manifest.yaml",
                target_registry_primitive="",
                claim_boundary="benchmark_fixture_self_test",
                reasoning_effort="high",
                timeout="180",
                priority="benchmark",
                status="READY",
                notes="Command-based benchmark row; run with quantummindlite.cli benchmark.",
            )
        )
    inventory_notes.append(f"Included {added} PaperBench-10 command rows.")


def base_task(
    *,
    dataset: str,
    subset: str,
    kind: str,
    card_id: str,
    parent_algorithm_id: str,
    algorithm_name: str,
    input_path: str,
    metadata_path: str,
    evidence_path: str,
    manifest_path: str,
    target_registry_primitive: str,
    claim_boundary: str,
    reasoning_effort: str,
    timeout: str,
    priority: str,
    status: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "global_task_id": "",
        "dataset": dataset,
        "subset": subset,
        "kind": kind,
        "card_id": card_id,
        "parent_algorithm_id": parent_algorithm_id,
        "algorithm_name": algorithm_name,
        "input_path": input_path,
        "metadata_path": metadata_path,
        "evidence_path": evidence_path,
        "manifest_path": manifest_path,
        "target_registry_primitive": target_registry_primitive,
        "expected_claim_boundary": claim_boundary,
        "reasoning_effort": reasoning_effort,
        "timeout": timeout,
        "priority": priority,
        "shard_id": "",
        "output_dir": "",
        "status": status,
        "notes": notes,
    }


def assign_global_ids(tasks: list[dict[str, Any]]) -> None:
    tasks.sort(key=lambda row: (priority_rank(str(row["priority"])), str(row["dataset"]), str(row["subset"]), str(row["card_id"])))
    for index, row in enumerate(tasks, start=1):
        row["global_task_id"] = f"FDV1-{index:05d}"


def assign_shards(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shard_sizes = {
        "registry_v1_probes": 50,
        "public_probe_v1": 50,
        "public_context_v1": 100,
        "recovered_context_second_pass": 100,
        "recovered_probe_second_pass": 50,
        "recovered_context_third_pass": 100,
        "recovered_probe_third_pass": 50,
        "public_blind_control": 100,
        "taco1000_v1": 100,
        "paperbench10": 10,
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in tasks:
        grouped[str(row["subset"])].append(row)
    shards: list[dict[str, Any]] = []
    for subset in sorted(grouped, key=lambda value: priority_rank(str(grouped[value][0]["priority"]))):
        rows = grouped[subset]
        size = shard_sizes.get(subset, 50)
        for shard_index, start in enumerate(range(0, len(rows), size), start=1):
            chunk = rows[start : start + size]
            shard_id = f"fdv1_{slug(subset)}_{shard_index:03d}"
            output_dir = f"runs/final_discovery_run_v1/{shard_id}"
            for row in chunk:
                row["shard_id"] = shard_id
                row["output_dir"] = output_dir
            shards.append(
                {
                    "shard_id": shard_id,
                    "dataset": str(chunk[0]["dataset"]),
                    "subset": subset,
                    "kind": str(chunk[0]["kind"]),
                    "priority": str(chunk[0]["priority"]),
                    "reasoning_effort": str(chunk[0]["reasoning_effort"]),
                    "expected_claim_boundary": str(chunk[0]["expected_claim_boundary"]),
                    "task_count": str(len(chunk)),
                    "ready_count": str(sum(1 for row in chunk if row["status"] == "READY")),
                    "start_index": str(start + 1),
                    "end_index": str(start + len(chunk)),
                    "output_dir": output_dir,
                    "manifest_path": "experiments/final_discovery_run_v1/manifests/master_run_manifest.csv",
                    "notes": "Use commands/run_shard.bat with this SHARD_ID.",
                }
            )
    return shards


def write_inventory_report(out_root: Path, tasks: list[dict[str, Any]], shards: list[dict[str, Any]], notes: list[str]) -> None:
    by_subset = Counter(str(row["subset"]) for row in tasks if row["status"] == "READY")
    by_kind = Counter(str(row["kind"]) for row in tasks if row["status"] == "READY")
    lines = [
        "# Final Dataset Inventory",
        "",
        f"- Total READY tasks: {sum(by_subset.values())}",
        f"- Total shards: {len(shards)}",
        f"- READY by subset: {dict(sorted(by_subset.items()))}",
        f"- READY by kind: {dict(sorted(by_kind.items()))}",
        "",
        "## Inclusion Notes",
    ]
    lines.extend(f"- {note}" for note in notes)
    lines.extend(["", "## Shards", "", "| shard_id | subset | ready_count | output_dir |", "| --- | --- | ---: | --- |"])
    for shard in shards:
        lines.append(f"| {shard['shard_id']} | {shard['subset']} | {shard['ready_count']} | {shard['output_dir']} |")
    (out_root / "reports" / "final_dataset_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_execution_plan(out_root: Path, tasks: list[dict[str, Any]], shards: list[dict[str, Any]]) -> None:
    first_registry = next((row for row in shards if row["subset"] == "registry_v1_probes"), {})
    first_probe = next((row for row in shards if row["subset"] == "public_probe_v1"), {})
    first_context = next((row for row in shards if row["subset"] == "public_context_v1"), {})
    lines = [
        "# Final Experiment Execution Plan",
        "",
        "No live runs were executed while building this package. Commands require `OPENAI_API_KEY` in the environment "
        "and warn about cost before running.",
        "",
        "Recommended order:",
        "1. Offline gate: rerun format, lint, mypy, pytest, and validate-paperbench.",
        "2. Registry-v1 probe first50: `experiments\\final_discovery_run_v1\\commands\\run_registry_v1_probe_first50.bat`.",
        "3. Summarize and inspect: `experiments\\final_discovery_run_v1\\commands\\summarize_finished_runs.bat`.",
        "4. Public probe next shard: set `SHARD_ID` to the next `public_probe_v1` shard and run `commands\\run_shard.bat`.",
        "5. Public context first100: `experiments\\final_discovery_run_v1\\commands\\run_context_first100.bat`.",
        "6. Recovered probes/context if present: run their medium-priority shards after inspecting earlier summaries.",
        "7. Controls last: PaperBench, public-blind if present, and TACO if present.",
        "8. Only then scale to all remaining shards using explicit `SHARD_ID` values; no live-all command is generated.",
        "",
        f"First registry shard: {first_registry.get('shard_id', 'none')}.",
        f"First public probe shard: {first_probe.get('shard_id', 'none')}.",
        f"First public context shard: {first_context.get('shard_id', 'none')}.",
        "",
        "Claim boundaries: registry-v1 and probe positives are query/subroutine hypotheses only; context cards are "
        "discovery inputs, not certified speedup claims.",
        f"Total READY tasks in master manifest: {sum(1 for row in tasks if row['status'] == 'READY')}.",
    ]
    (out_root / "reports" / "final_experiment_execution_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_commands(out_root: Path) -> None:
    command_dir = out_root / "commands"
    write_run_shard(command_dir / "run_shard.bat", out_root)
    write_wrapper(command_dir / "run_registry_v1_probe_first50.bat", out_root, "registry_v1_probes", "1", "50")
    write_wrapper(command_dir / "run_probe_first50.bat", out_root, "public_probe_v1", "1", "50")
    write_wrapper(command_dir / "run_context_first100.bat", out_root, "public_context_v1", "1", "100")
    write_summarize(command_dir / "summarize_finished_runs.bat", out_root)
    write_missing(command_dir / "check_missing_outputs.bat", out_root)


def write_run_shard(path: Path, out_root: Path) -> None:
    manifest = out_root / "manifests" / "master_run_manifest.csv"
    logs = out_root / "logs"
    lines = [
        "@echo off\n",
        "REM Run one final discovery shard. No API keys are stored in this file.\n",
        "setlocal\n",
        'if "%OPENAI_API_KEY%"=="" (\n  echo OPENAI_API_KEY must be set in the environment.\n  exit /b 1\n)\n',
        'if "%PYTHON%"=="" set "PYTHON=python"\n',
        f'set "FINAL_MANIFEST={manifest}"\n',
        f'set "FINAL_LOG_DIR={logs}"\n',
        "echo WARNING: this runs OpenAI live analyze/benchmark commands and may incur cost.\n",
        "echo Probe positives are query/subroutine hypotheses, not end-to-end speedup claims.\n",
        'if "%SHARD_ID%"=="" (\n  if "%START_INDEX%"=="" set "START_INDEX=1"\n  if "%END_INDEX%"=="" set "END_INDEX=50"\n)\n',
        "powershell -NoProfile -ExecutionPolicy Bypass -Command ^\n  ",
        powershell_run_shard(),
        "\nexit /b %ERRORLEVEL%\n",
    ]
    path.write_text("".join(lines), encoding="utf-8")


def powershell_run_shard() -> str:
    script = "; ".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$manifest = $env:FINAL_MANIFEST",
            "if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }",
            "$logDir = $env:FINAL_LOG_DIR",
            "New-Item -ItemType Directory -Force -Path $logDir | Out-Null",
            "$rows = @(Import-Csv -LiteralPath $manifest | Where-Object { $_.status -eq 'READY' })",
            "if (-not [string]::IsNullOrWhiteSpace($env:RUN_SUBSET)) { $rows = @($rows | Where-Object { $_.subset -eq $env:RUN_SUBSET }) }",
            "if (-not [string]::IsNullOrWhiteSpace($env:SHARD_ID)) { "
            "$rows = @($rows | Where-Object { $_.shard_id -eq $env:SHARD_ID }) "
            "} else { $start=[int]$env:START_INDEX; $end=[int]$env:END_INDEX; $i=0; "
            "$rows = @($rows | Where-Object { $i += 1; $i -ge $start -and $i -le $end }) }",
            "if ($rows.Count -eq 0) { throw 'No READY rows matched the requested shard/range.' }",
            "foreach ($r in $rows) {",
            "  $inputPath = [string]$r.input_path",
            "  if ([string]::IsNullOrWhiteSpace($inputPath) -or -not (Test-Path -LiteralPath $inputPath)) { "
            "Write-Host ('SKIP missing input {0}: {1}' -f $r.global_task_id, $inputPath); continue }",
            "  New-Item -ItemType Directory -Force -Path ([string]$r.output_dir) | Out-Null",
            "  $stdout = Join-Path $logDir ($r.global_task_id + '.stdout.log')",
            "  $stderr = Join-Path $logDir ($r.global_task_id + '.stderr.log')",
            "  $cmdArgs = @('-m','quantummindlite.cli')",
            "  if ($r.kind -eq 'benchmark') { $cmdArgs += @('benchmark','--case-id',[string]$r.card_id) } "
            "else { $cmdArgs += @('analyze','--input',$inputPath) }",
            "  $cmdArgs += @('--provider','openai','--reasoning-effort',[string]$r.reasoning_effort,'--output-dir',[string]$r.output_dir)",
            "  if (-not [string]::IsNullOrWhiteSpace([string]$r.timeout)) { $cmdArgs += @('--timeout',[string]$r.timeout) }",
            "  Write-Host ('RUN {0} {1} {2}' -f $r.global_task_id, $r.kind, $inputPath)",
            "  & $env:PYTHON @cmdArgs > $stdout 2> $stderr",
            "  if ($LASTEXITCODE -ne 0) { Write-Host ('FAILED {0}; see {1} and {2}' -f $r.global_task_id, "
            "$stdout, $stderr); exit $LASTEXITCODE }",
            "}",
        ]
    )
    return f'"{script}"'


def write_wrapper(path: Path, out_root: Path, subset: str, start: str, end: str) -> None:
    lines = [
        "@echo off\n",
        "REM Wrapper for a recommended first slice. No API keys are stored in this file.\n",
        "setlocal\n",
        f'set "RUN_SUBSET={subset}"\n',
        f'set "START_INDEX={start}"\n',
        f'set "END_INDEX={end}"\n',
        'set "SHARD_ID="\n',
        'call "%~dp0run_shard.bat"\n',
        "exit /b %ERRORLEVEL%\n",
    ]
    path.write_text("".join(lines), encoding="utf-8")


def write_summarize(path: Path, out_root: Path) -> None:
    manifest = out_root / "manifests" / "master_run_manifest.csv"
    logs = out_root / "logs"
    out_csv = out_root / "reports" / "final_finished_run_summary.csv"
    out_md = out_root / "reports" / "final_finished_run_summary.md"
    script = "; ".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$manifest = '{manifest}'",
            f"$logs = '{logs}'",
            "$rows = @(Import-Csv -LiteralPath $manifest)",
            "$summary = foreach ($r in $rows) { "
            "$stdout = Join-Path $logs ($r.global_task_id + '.stdout.log'); "
            "$stderr = Join-Path $logs ($r.global_task_id + '.stderr.log'); "
            "[pscustomobject]@{ global_task_id=$r.global_task_id; subset=$r.subset; kind=$r.kind; "
            "card_id=$r.card_id; shard_id=$r.shard_id; stdout_log_present=(Test-Path -LiteralPath $stdout); "
            "stderr_log_present=(Test-Path -LiteralPath $stderr); output_dir=$r.output_dir; "
            "run_dir_count=@(Get-ChildItem -Directory -Path $r.output_dir -ErrorAction SilentlyContinue).Count } }",
            f"$summary | Export-Csv -NoTypeInformation -Path '{out_csv}'",
            f"'# Final Finished Run Summary' | Set-Content -Path '{out_md}'",
            f"('Rows summarized: ' + $summary.Count) | Add-Content -Path '{out_md}'",
            "Write-Host ('Wrote {0}' -f '" + str(out_csv) + "')",
        ]
    )
    path.write_text(
        "@echo off\nREM Summarize finished final discovery runs. No API keys are stored in this file.\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"\n',
        encoding="utf-8",
    )


def write_missing(path: Path, out_root: Path) -> None:
    manifest = out_root / "manifests" / "master_run_manifest.csv"
    logs = out_root / "logs"
    out_csv = out_root / "reports" / "missing_outputs.csv"
    script = "; ".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$manifest = '{manifest}'",
            f"$logs = '{logs}'",
            "$rows = @(Import-Csv -LiteralPath $manifest | Where-Object { $_.status -eq 'READY' })",
            "$missing = foreach ($r in $rows) { "
            "$stdout = Join-Path $logs ($r.global_task_id + '.stdout.log'); "
            "if (-not (Test-Path -LiteralPath $stdout)) { $r } }",
            f"$missing | Export-Csv -NoTypeInformation -Path '{out_csv}'",
            "Write-Host ('Missing output rows: {0}' -f @($missing).Count)",
            "if (@($missing).Count -gt 0) { exit 1 }",
        ]
    )
    path.write_text(
        "@echo off\nREM Check missing final discovery run logs. No API keys are stored in this file.\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"\n',
        encoding="utf-8",
    )


def priority_rank(priority: str) -> int:
    return {
        "highest": 0,
        "high": 1,
        "medium-high": 2,
        "medium": 3,
        "benchmark": 4,
        "control": 5,
    }.get(priority, 9)


def slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


if __name__ == "__main__":
    raise SystemExit(main())

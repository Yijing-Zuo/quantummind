from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from quantummindlite.evaluation import load_manifest, load_public_case
from quantummindlite.models import (
    AnalysisCard,
    BarrierAssessment,
    BarrierSpec,
    CandidateCard,
    ProblemCard,
    RunState,
)
from quantummindlite.registry import (
    barrier_catalog_public_view,
    load_barrier_catalog,
    load_registry,
    load_source_catalog,
    project_root,
    registry_public_view,
    source_catalog_public_view,
    structure_vocabulary,
)
from quantummindlite.storage import digest_json
from quantummindlite.validation import build_decision

try:
    from scripts.baseline_methods import STRATEGIES, BaselineOutput, mock_reply
except ImportError:  # direct invocation: python scripts/run_baselines.py
    from baseline_methods import STRATEGIES, BaselineOutput, mock_reply

# Literature-derived baselines over the same tasks, public knowledge, and
# artifact chain as QuantumMind (citations in baseline_methods.py). Task
# sources: the frozen PaperBench cases (default) or any final-discovery-run
# master manifest via --task-manifest, keyed by global_task_id so baseline
# rows pair with QuantumMind rows in ODS scoring.

_PROBLEM_FIELDS = ("statement", "input_model", "access_model", "output_contract", "promises", "size_parameters", "ambiguities")


@dataclass(frozen=True)
class Task:
    task_id: str
    card: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run literature-derived baselines over PaperBench or discovery-manifest tasks.")
    parser.add_argument("--baseline", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--provider", choices=["mock", "openai"], default=os.environ.get("QUANTUMMINDLITE_PROVIDER", "mock"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", default=os.environ.get("QUANTUMMINDLITE_REASONING_EFFORT"))
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--k", type=int, default=3, help="Sample count for self_consistency (ignored by other baselines).")
    parser.add_argument("--case-id", action="append", help="Restrict PaperBench mode to specific case IDs (repeatable).")
    parser.add_argument("--task-manifest", default=None, help="Master run manifest CSV; switches the task source to discovery tasks.")
    parser.add_argument("--shard", action="append", help="With --task-manifest: restrict to these shard_id values (repeatable).")
    parser.add_argument("--limit", type=int, default=None, help="With --task-manifest: run at most N tasks (pilot batches).")
    parser.add_argument("--system-id", default=None, help="Manifest system_id. Default: baseline_<name>_<provider>.")
    parser.add_argument("--output-root", default="runs_baselines", help="Run directories land under <output-root>/<system-id>/<task-id>.")
    parser.add_argument("--fresh", action="store_true", help="Re-run tasks even when completed artifacts already exist.")
    parser.add_argument("--root", default=None, help="Project root override.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else project_root(Path.cwd())
    system_id = args.system_id or f"baseline_{args.baseline}_{args.provider}"
    output_root = Path(args.output_root)
    output_root = output_root if output_root.is_absolute() else root / output_root
    registry = load_registry(root)
    barrier_catalog = load_barrier_catalog(root)
    context_base = {
        "structure_vocabulary": structure_vocabulary(registry),
        "registry_public_view": registry_public_view(registry, selectable_only=True),
        "barrier_catalog_public_view": barrier_catalog_public_view(barrier_catalog),
        "source_catalog_public_view": source_catalog_public_view(load_source_catalog(root)),
    }
    tasks = _load_tasks(args, root)
    strategy = STRATEGIES[args.baseline]
    call, model_label = _make_call_fn(args)

    results: list[dict[str, Any]] = []
    for task in tasks:
        run_dir = output_root / system_id / task.task_id
        if not args.fresh and (run_dir / "state.json").is_file() and (run_dir / "decision.json").is_file():
            results.append({"task_id": task.task_id, "status": "cached", "run_dir": _portable(run_dir, root)})
            continue
        inputs = {"public_case": task.card, **context_base}
        started = perf_counter()
        try:
            output, stages = strategy(call, inputs, args.k)
        except Exception as exc:
            results.append({"task_id": task.task_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        state = _build_state(system_id, args.baseline, task.card, output, barrier_catalog)
        decision = build_decision(state, registry)
        summary_trace = {
            "baseline_id": args.baseline,
            "task_id": task.task_id,
            "provider": args.provider,
            "model": model_label,
            "status": "ok",
            "stage_count": len(stages),
            "latency": round(perf_counter() - started, 6),
            "input_digest": digest_json(inputs),
            "output_digest": digest_json(output.model_dump(mode="json")),
        }
        _write_run(run_dir, task.card, state, decision, [*({"stage_detail": stage} for stage in stages), summary_trace])
        results.append(
            {
                "task_id": task.task_id,
                "status": "ok",
                "run_dir": _portable(run_dir, root),
                "verdict": decision.authoritative_verdict.value,
                "selected": (state.candidate_card.selected_candidate if state.candidate_card else None) or "NO_CANDIDATE",
                "route": decision.d_route.value,
            }
        )

    manifest_path = _write_ods_manifest(output_root, system_id, root)
    errors = [item for item in results if item["status"] == "error"]
    print(
        json.dumps(
            {
                "system_id": system_id,
                "baseline": args.baseline,
                "provider": args.provider,
                "model": model_label,
                "benchmark_label": "fixture_self_test" if args.provider == "mock" else "live_model_run",
                "task_source": "task_manifest" if args.task_manifest else "paperbench",
                "tasks": results,
                "manifest_csv": _portable(manifest_path, root),
                "completed": sum(1 for item in results if item["status"] in {"ok", "cached"}),
                "errors": len(errors),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if errors else 0


def _load_tasks(args: argparse.Namespace, root: Path) -> list[Task]:
    if args.task_manifest is None:
        case_ids = args.case_id or list(load_manifest(root)["ready_cases"])
        tasks = []
        for case_id in case_ids:
            dump = load_public_case(case_id, root).model_dump(mode="json")
            tasks.append(Task(task_id=case_id, card={key: dump[key] for key in _PROBLEM_FIELDS}))
        return tasks
    manifest_path = Path(args.task_manifest)
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    shards = set(args.shard or [])
    tasks = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("status", "")).strip().upper() not in {"", "READY"}:
                continue
            if shards and str(row.get("shard_id", "")) not in shards:
                continue
            task_id = str(row.get("global_task_id", "")).strip()
            input_path = str(row.get("input_path", "")).strip().replace("\\", "/")
            if not task_id or not input_path:
                continue
            tasks.append(Task(task_id=task_id, card=_load_card(root / input_path)))
            if args.limit is not None and len(tasks) >= args.limit:
                break
    if not tasks:
        raise SystemExit(f"no READY tasks matched in {manifest_path}")
    return tasks


def _load_card(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"card {path} is not a mapping")
    card = {key: data.get(key) for key in _PROBLEM_FIELDS}
    ProblemCard.model_validate(card)
    return card


def _make_call_fn(args: argparse.Namespace) -> tuple[Any, str]:
    if args.provider == "mock":
        return mock_reply, "mock-baseline"
    if os.environ.get("QUANTUMMINDLITE_LIVE_OPENAI") != "1":
        raise SystemExit("live OpenAI calls require QUANTUMMINDLITE_LIVE_OPENAI=1")
    model = args.model or os.environ.get("QUANTUMMINDLITE_OPENAI_MODEL", "")
    if not model:
        raise SystemExit("openai provider requires --model or QUANTUMMINDLITE_OPENAI_MODEL")
    from openai import OpenAI

    client = OpenAI()

    def call(instructions: str, inputs: dict[str, Any], schema: type[Any]) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": json.dumps({"inputs": inputs}, sort_keys=True, default=str),
            "text_format": schema,
            "store": False,
        }
        if args.reasoning_effort:
            kwargs["reasoning"] = {"effort": args.reasoning_effort}
        if args.timeout is not None:
            kwargs["timeout"] = args.timeout
        last_error: Exception | None = None
        for _attempt in (1, 2):
            try:
                response = client.responses.parse(**kwargs)
            except Exception as exc:
                last_error = exc
                continue
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                last_error = RuntimeError("OpenAI response did not contain output_parsed")
                continue
            try:
                return parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
            except ValidationError as exc:
                last_error = exc
                continue
        raise RuntimeError(f"baseline call failed after 2 attempts: {last_error!r}")

    return call, model


def _build_state(
    system_id: str,
    baseline_id: str,
    card: dict[str, Any],
    output: BaselineOutput,
    barrier_catalog: dict[str, BarrierSpec],
) -> RunState:
    problem = ProblemCard.model_validate(card)
    analysis = AnalysisCard(
        formalized_problem=output.formalized_problem,
        canonical_structure_ids=output.canonical_structure_ids,
        absent_or_weak_structures=output.absent_or_weak_structures,
        classical_baseline=output.classical_baseline or "UNKNOWN",
        bottleneck=output.bottleneck,
        complexity_model=output.complexity_model,
    )
    barriers: list[BarrierAssessment] = []
    for item in output.barriers:
        spec = barrier_catalog.get(item.barrier_id)
        barriers.append(
            BarrierAssessment(
                barrier_id=item.barrier_id,
                description=spec.description if spec else (item.note or item.barrier_id),
                applicable=item.applicable,
                blocked_scopes=spec.blocked_scopes if spec else [],
            )
        )
    candidate = CandidateCard(
        primitive_matches=output.primitive_matches,
        barriers=barriers,
        selected_candidate=output.selected_candidate,
        no_candidate_reason=None if output.selected_candidate else output.no_candidate_reason,
        prior_art_status=output.prior_art_status,
        novelty_status=output.novelty_status,
        scheme_steps=output.scheme_steps,
        classical_baseline=output.classical_baseline or "UNKNOWN",
        quantum_query_complexity=output.quantum_query_complexity,
        gate_complexity=output.gate_complexity,
        total_complexity=output.total_complexity,
        claim_scope=output.claim_scope,
        limitations=output.limitations,
        expert_questions=output.expert_questions,
        self_assessment=output.self_assessment,
    )
    message = {
        "baseline_system_id": system_id,
        "baseline_id": baseline_id,
        "action": "baseline_strategy_call",
        "payload_digest": digest_json(output.model_dump(mode="json")),
    }
    return RunState(problem_card=problem, analysis_card=analysis, candidate_card=candidate, messages=[message])


def _write_run(run_dir: Path, card: dict[str, Any], state: RunState, decision: Any, trace_rows: list[dict[str, Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _dump(run_dir / "input.json", card)
    _dump(run_dir / "state.json", state.model_dump(mode="json"))
    _dump(run_dir / "decision.json", decision.model_dump(mode="json"))
    with (run_dir / "trace.jsonl").open("w", encoding="utf-8") as handle:
        for row in trace_rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_ods_manifest(output_root: Path, system_id: str, root: Path) -> Path:
    rows = []
    for state_path in sorted((output_root / system_id).glob("*/state.json")):
        run_dir = state_path.parent
        if (run_dir / "decision.json").is_file():
            rows.append({"system_id": system_id, "task_id": run_dir.name, "run_dir": _portable(run_dir, root)})
    manifest_path = output_root / f"{system_id}_manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["system_id", "task_id", "run_dir"])
        writer.writeheader()
        writer.writerows(rows)
    return manifest_path


def _portable(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


if __name__ == "__main__":
    raise SystemExit(main())

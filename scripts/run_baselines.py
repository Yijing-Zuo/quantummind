from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import Field, ValidationError

from quantummindlite.evaluation import PublicCase, load_manifest, load_public_case
from quantummindlite.models import (
    AnalysisCard,
    BarrierAssessment,
    BarrierSpec,
    CandidateCard,
    ClaimScope,
    EvidenceState,
    NoveltyStatus,
    PrimitiveMatch,
    PriorArtStatus,
    ProblemCard,
    RunState,
    StrictModel,
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

# Single-call baselines: the same base model and the same public knowledge the
# system's agents can see, with none of the staged workflow, merge-time
# normalization, or bounce-back machinery. The deterministic validator and all
# downstream screening/scoring run unchanged on the resulting artifacts, per
# docs/ODS_V1.md ("same task set, public registries, deterministic validators
# ... to QuantumMind and every baseline").

_PROBLEM_FIELDS = ("statement", "input_model", "access_model", "output_contract", "promises", "size_parameters", "ambiguities")

_SHARED_RULES = """
Output exactly one BaselineOutput object.
Use primitive_id values only from registry_public_view and barrier_id values
only from barrier_catalog_public_view; if nothing fits, report no match rather
than inventing an identifier.
Select a candidate only when the represented access model, output contract,
and promises support an asymptotic quantum speedup claim at the stated scope.
Otherwise set selected_candidate to null and give a concrete no_candidate_reason.
Report barriers honestly, including ones that block your own proposal.
Do not overstate prior-art or novelty status: without a supporting public
source, use UNKNOWN / UNASSESSED.
"""

ZERO_SHOT_PROMPT = (
    "You are a single-call assessor. Given one public problem card plus public "
    "registries of quantum primitives, barriers, and sources, decide in one shot "
    "whether the problem supports an asymptotic quantum-speedup hypothesis, and "
    "fill every BaselineOutput field." + _SHARED_RULES
)

COT_PROMPT = (
    "You are a single-call assessor. Work through the problem step by step before "
    "answering: formalize the task; identify canonical structures and the "
    "classical baseline and bottleneck; compare each plausible primitive's "
    "prerequisites against the represented access model, output contract, and "
    "promises; assess applicable barriers; check prior art in the public source "
    "catalog; only then commit to a scheme or a no-candidate verdict. After "
    "reasoning, fill every BaselineOutput field." + _SHARED_RULES
)

BASELINES = {"zero_shot": ZERO_SHOT_PROMPT, "cot": COT_PROMPT}


class BaselineBarrier(StrictModel):
    barrier_id: str
    applicable: EvidenceState
    note: str = ""


class BaselineOutput(StrictModel):
    formalized_problem: str
    canonical_structure_ids: list[str] = Field(default_factory=list)
    absent_or_weak_structures: list[str] = Field(default_factory=list)
    classical_baseline: str = "UNKNOWN"
    bottleneck: str = ""
    complexity_model: str = ""
    primitive_matches: list[PrimitiveMatch] = Field(default_factory=list)
    barriers: list[BaselineBarrier] = Field(default_factory=list)
    selected_candidate: str | None = None
    no_candidate_reason: str | None = None
    scheme_steps: list[str] = Field(default_factory=list)
    quantum_query_complexity: str | None = None
    gate_complexity: str | None = None
    total_complexity: str | None = None
    claim_scope: ClaimScope = ClaimScope.NONE
    limitations: list[str] = Field(default_factory=list)
    expert_questions: list[str] = Field(default_factory=list)
    prior_art_status: PriorArtStatus = PriorArtStatus.UNKNOWN
    novelty_status: NoveltyStatus = NoveltyStatus.UNASSESSED
    self_assessment: str = "diagnostic_only"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run single-call baselines over the PaperBench public cases.")
    parser.add_argument("--baseline", choices=sorted(BASELINES), required=True)
    parser.add_argument("--provider", choices=["mock", "openai"], default=os.environ.get("QUANTUMMINDLITE_PROVIDER", "mock"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", default=os.environ.get("QUANTUMMINDLITE_REASONING_EFFORT"))
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--case-id", action="append", help="Restrict to specific case IDs (repeatable). Default: all ready cases.")
    parser.add_argument("--system-id", default=None, help="Manifest system_id. Default: baseline_<name>_<provider>.")
    parser.add_argument("--output-root", default="runs_baselines", help="Run directories land under <output-root>/<system-id>/<case-id>.")
    parser.add_argument("--fresh", action="store_true", help="Re-run cases even when completed artifacts already exist.")
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
    case_ids = args.case_id or list(load_manifest(root)["ready_cases"])
    prompt = BASELINES[args.baseline]

    results: list[dict[str, Any]] = []
    for case_id in case_ids:
        public = load_public_case(case_id, root)
        run_dir = output_root / system_id / case_id
        if not args.fresh and (run_dir / "state.json").is_file() and (run_dir / "decision.json").is_file():
            results.append({"case_id": case_id, "status": "cached", "run_dir": _portable(run_dir, root)})
            continue
        inputs = {"public_case": public.model_dump(mode="json"), **context_base}
        started = perf_counter()
        try:
            output, trace = _generate(args, prompt, inputs, public)
        except Exception as exc:
            results.append({"case_id": case_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        state = _build_state(system_id, args.baseline, public, output, barrier_catalog)
        decision = build_decision(state, registry)
        trace.update(
            {
                "baseline_id": args.baseline,
                "case_id": case_id,
                "latency": round(perf_counter() - started, 6),
                "prompt_digest": digest_json(prompt),
                "input_digest": digest_json(inputs),
                "output_digest": digest_json(output.model_dump(mode="json")),
            }
        )
        _write_run(run_dir, public, state, decision, trace)
        results.append(
            {
                "case_id": case_id,
                "status": "ok",
                "run_dir": _portable(run_dir, root),
                "verdict": decision.authoritative_verdict.value,
                "selected": (state.candidate_card.selected_candidate if state.candidate_card else None) or "NO_CANDIDATE",
                "route": decision.d_route.value,
            }
        )

    manifest_path = _write_manifest(output_root, system_id, root)
    errors = [item for item in results if item["status"] == "error"]
    print(
        json.dumps(
            {
                "system_id": system_id,
                "provider": args.provider,
                "model": args.model or os.environ.get("QUANTUMMINDLITE_OPENAI_MODEL", "") if args.provider == "openai" else "mock-baseline",
                "benchmark_label": "fixture_self_test" if args.provider == "mock" else "live_model_run",
                "cases": results,
                "manifest_csv": _portable(manifest_path, root),
                "completed": sum(1 for item in results if item["status"] in {"ok", "cached"}),
                "errors": len(errors),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if errors else 0


def _generate(
    args: argparse.Namespace,
    prompt: str,
    inputs: dict[str, Any],
    public: PublicCase,
) -> tuple[BaselineOutput, dict[str, Any]]:
    if args.provider == "mock":
        return _mock_output(public), {"provider": "mock", "model": "mock-baseline", "status": "ok", "attempt_count": 1}
    return _openai_output(args, prompt, inputs)


def _mock_output(public: PublicCase) -> BaselineOutput:
    return BaselineOutput(
        formalized_problem=public.statement,
        classical_baseline="UNKNOWN",
        bottleneck="unspecified",
        complexity_model=public.access_model,
        no_candidate_reason="Mock baseline placeholder: no assessment was performed.",
        limitations=["deterministic placeholder output for pipeline validation only"],
        self_assessment="mock_placeholder",
    )


def _openai_output(args: argparse.Namespace, prompt: str, inputs: dict[str, Any]) -> tuple[BaselineOutput, dict[str, Any]]:
    if os.environ.get("QUANTUMMINDLITE_LIVE_OPENAI") != "1":
        raise RuntimeError("live OpenAI calls require QUANTUMMINDLITE_LIVE_OPENAI=1")
    model = args.model or os.environ.get("QUANTUMMINDLITE_OPENAI_MODEL", "")
    if not model:
        raise RuntimeError("openai provider requires --model or QUANTUMMINDLITE_OPENAI_MODEL")
    from openai import OpenAI

    client = OpenAI()
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": prompt,
        "input": json.dumps({"inputs": inputs}, sort_keys=True),
        "text_format": BaselineOutput,
        "store": False,
    }
    if args.reasoning_effort:
        kwargs["reasoning"] = {"effort": args.reasoning_effort}
    if args.timeout is not None:
        kwargs["timeout"] = args.timeout
    last_error: Exception | None = None
    for attempt in (1, 2):
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
            output = parsed if isinstance(parsed, BaselineOutput) else BaselineOutput.model_validate(parsed)
        except ValidationError as exc:
            last_error = exc
            continue
        usage = getattr(response, "usage", None)
        usage_dump = usage.model_dump(mode="json") if hasattr(usage, "model_dump") else None
        return output, {
            "provider": "openai",
            "model": str(getattr(response, "model", model)),
            "status": "ok",
            "attempt_count": attempt,
            "usage": usage_dump,
        }
    raise RuntimeError(f"baseline generation failed after 2 attempts: {last_error!r}")


def _build_state(
    system_id: str,
    baseline_id: str,
    public: PublicCase,
    output: BaselineOutput,
    barrier_catalog: dict[str, BarrierSpec],
) -> RunState:
    public_dump = public.model_dump(mode="json")
    problem = ProblemCard.model_validate({key: public_dump[key] for key in _PROBLEM_FIELDS})
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
        "action": "baseline_single_call",
        "payload_digest": digest_json(output.model_dump(mode="json")),
    }
    return RunState(problem_card=problem, analysis_card=analysis, candidate_card=candidate, messages=[message])


def _write_run(run_dir: Path, public: PublicCase, state: RunState, decision: Any, trace: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _dump(run_dir / "input.json", public.model_dump(mode="json"))
    _dump(run_dir / "state.json", state.model_dump(mode="json"))
    _dump(run_dir / "decision.json", decision.model_dump(mode="json"))
    with (run_dir / "trace.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, sort_keys=True) + "\n")


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_manifest(output_root: Path, system_id: str, root: Path) -> Path:
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

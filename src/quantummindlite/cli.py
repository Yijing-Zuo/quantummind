from __future__ import annotations

import argparse
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .evaluation import (
    GoldFamily,
    GoldRelation,
    PublicFamily,
    load_manifest,
    load_public_case,
    load_yaml_model,
    score_case,
    validate_paperbench,
    write_freeze_manifest,
)
from .llm import LLMProvider, MockLLMProvider
from .models import (
    BarrierAssessment,
    CandidateCard,
    ClaimScope,
    DecisionCard,
    EvidenceState,
    NoveltyStatus,
    PriorArtStatus,
    RunState,
    Verdict,
)
from .openai_provider import OpenAIStructuredProvider
from .registry import load_registry, project_root, resource_root
from .storage import digest_json
from .validation import build_decision
from .workflow import Orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantummindlite")
    sub = parser.add_subparsers(dest="cmd", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--input", required=True)
    _add_runtime_options(analyze)
    bench = sub.add_parser("benchmark")
    bench.add_argument("--case-id", required=True)
    _add_runtime_options(bench)
    benchmark_all = sub.add_parser("benchmark-all")
    _add_runtime_options(benchmark_all)
    family = sub.add_parser("benchmark-family")
    family.add_argument("--family-id", required=True)
    _add_runtime_options(family)
    sub.add_parser("validate-paperbench")
    freeze = sub.add_parser("freeze-paperbench")
    freeze.add_argument("--confirm", action="store_true")
    inspect = sub.add_parser("inspect-run")
    inspect.add_argument("--run-dir", required=True)
    sub.add_parser("count-loc")
    args = parser.parse_args(argv)
    root = resource_root()
    if args.cmd == "analyze":
        data = _load_input(Path(args.input))
        provider = _make_provider(args, parser)
        result = Orchestrator(provider=provider, root=root).run(data, output_dir=_output_dir(args.output_dir))
        print(result.run_dir)
        return 0
    if args.cmd == "benchmark":
        provider = _make_provider(args, parser)
        public = load_public_case(args.case_id, root)
        result = Orchestrator(provider=provider, root=root).run(public.model_dump(mode="json"), output_dir=_output_dir(args.output_dir))
        score = score_case(args.case_id, result.state, result.decision, root)
        score_payload = _with_run_metadata(score.model_dump(mode="json"), provider)
        (result.run_dir / "score.json").write_text(
            json.dumps(score_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(result.run_dir)
        print(json.dumps(score_payload, indent=2, sort_keys=True))
        return 0
    if args.cmd == "benchmark-all":
        provider = _make_provider(args, parser)
        print(json.dumps(_benchmark_all(root, args.output_dir, provider), indent=2, sort_keys=True))
        return 0
    if args.cmd == "benchmark-family":
        provider = _make_provider(args, parser)
        validation = validate_family(root, args.family_id)
        if not validation["ok"]:
            print(json.dumps(validation, indent=2, sort_keys=True))
            return 1

        def run_variant(public_case: Any) -> tuple[RunState, DecisionCard]:
            family_run = Orchestrator(provider=provider, root=root).run(
                public_case.model_dump(mode="json"), output_dir=_output_dir(args.output_dir)
            )
            return family_run.state, family_run.decision

        payload = _with_run_metadata(score_family(root, args.family_id, run_variant), provider)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.cmd == "validate-paperbench":
        validation_result = validate_paperbench(root)
        print(json.dumps(validation_result, indent=2, sort_keys=True))
        return 0 if validation_result["ok"] else 1
    if args.cmd == "freeze-paperbench":
        if not args.confirm:
            parser.error("freeze-paperbench requires --confirm")
        print(json.dumps(write_freeze_manifest(root), indent=2, sort_keys=True))
        return 0
    if args.cmd == "inspect-run":
        run_dir = Path(args.run_dir)
        data = {
            name: json.loads((run_dir / name).read_text(encoding="utf-8"))
            for name in ("input.json", "state.json", "decision.json")
            if (run_dir / name).exists()
        }
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    if args.cmd == "count-loc":
        loc_result = count_loc(root)
        print(json.dumps(loc_result, indent=2, sort_keys=True))
        return 0 if loc_result["ok"] else 1
    raise AssertionError(args.cmd)


def _load_input(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = (yaml.safe_load(text) or {}) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("input must be an object")
    return data


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["mock", "openai"], default=os.environ.get("QUANTUMMINDLITE_PROVIDER", "mock"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--timeout", type=float, default=_env_float("QUANTUMMINDLITE_TIMEOUT"))
    parser.add_argument("--output-dir", default=os.environ.get("QUANTUMMINDLITE_OUTPUT_DIR", "runs"))


def _output_dir(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _make_provider(args: argparse.Namespace, parser: argparse.ArgumentParser) -> LLMProvider:
    if args.provider == "mock":
        return MockLLMProvider()
    try:
        return OpenAIStructuredProvider(model=args.model, reasoning_effort=args.reasoning_effort, timeout=args.timeout)
    except RuntimeError as exc:
        parser.error(str(exc))
    raise AssertionError("parser.error should exit")


def _benchmark_all(root: Path, output_dir: str, provider: LLMProvider) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    out = _output_dir(output_dir)
    for case_id in load_manifest(root)["ready_cases"]:
        public = load_public_case(case_id, root)
        try:
            result = Orchestrator(provider=provider, root=root).run(public.model_dump(mode="json"), output_dir=out)
            score = score_case(case_id, result.state, result.decision, root)
            payload = _with_run_metadata(score.model_dump(mode="json"), provider)
            (result.run_dir / "score.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception as exc:
            payload = _with_run_metadata(
                {
                    "case_id": case_id,
                    "error": str(exc),
                    "raw_reasoning_score": {"raw_pass": False},
                    "system_score": {"system_pass": False},
                },
                provider,
            )
        per_case.append(payload)
    macro_raw = sum(int(item["raw_reasoning_score"]["raw_pass"]) for item in per_case) / len(per_case)
    macro_system = sum(int(item["system_score"]["system_pass"]) for item in per_case) / len(per_case)
    guardrail = guardrail_suite_report(root)
    case_pass = all(item["raw_reasoning_score"]["raw_pass"] and item["system_score"]["system_pass"] for item in per_case)
    return _with_run_metadata(
        {
            "cases": per_case,
            "guardrail_suite": guardrail,
            "guardrail_pass": guardrail["guardrail_pass"],
            "macro_raw_pass": macro_raw,
            "macro_system_pass": macro_system,
            "overall_pass": bool(case_pass and guardrail["guardrail_pass"]),
        },
        provider,
    )


def validate_family(root: Path | None, family_id: str) -> dict[str, Any]:
    base = resource_root(root)
    public = load_yaml_model(base / "paperbench" / "families" / "public" / f"{family_id}.yaml", PublicFamily)
    gold = load_yaml_model(base / "paperbench" / "families" / "gold" / f"{family_id}.yaml", GoldFamily)
    errors: list[str] = []
    if public.family_id != gold.family_id:
        errors.append("family ID mismatch")
    if digest_json(public.model_dump(mode="json")) != gold.public_digest:
        errors.append("public/gold family digest mismatch")
    for relation in gold.relations:
        if not relation.diagnostic_only and (relation.seed_projection is None or relation.variant_projection is None):
            errors.append(f"{relation.variant_id}: non-diagnostic relation lacks projections")
    return {"family_id": family_id, "ok": not errors, "errors": errors}


def score_family(root: Path | None, family_id: str, run_variant: Any) -> dict[str, Any]:
    base = resource_root(root)
    public = load_yaml_model(base / "paperbench" / "families" / "public" / f"{family_id}.yaml", PublicFamily)
    gold = load_yaml_model(base / "paperbench" / "families" / "gold" / f"{family_id}.yaml", GoldFamily)
    seed = next(item for item in public.variants if item.variant_id == public.seed_variant_id)
    seed_state, seed_decision = run_variant(seed.public_case)
    seed_projection = _projection(seed_state, seed_decision)
    exact = scored = 0
    details: list[dict[str, Any]] = []
    for relation in gold.relations:
        variant = next(item for item in public.variants if item.variant_id == relation.variant_id)
        state, decision = run_variant(variant.public_case)
        variant_projection = _projection(state, decision)
        predicted = _relation(seed_state, seed_decision, state, decision)
        seed_exact = relation.seed_projection is None or seed_projection == relation.seed_projection.model_dump(mode="json")
        variant_exact = relation.variant_projection is None or variant_projection == relation.variant_projection.model_dump(mode="json")
        relation_exact = predicted == relation.expected_relation and _field_delta_ok(seed_projection, variant_projection, relation)
        pair_exact = seed_exact and variant_exact and relation_exact
        if not relation.diagnostic_only:
            scored += 1
            exact += int(pair_exact)
        details.append(
            {
                "variant_id": relation.variant_id,
                "expected_relation": relation.expected_relation,
                "predicted_relation": predicted,
                "seed_exact": seed_exact,
                "variant_exact": variant_exact,
                "relation_exact": relation_exact,
                "pair_exact": pair_exact,
                "diagnostic_only": relation.diagnostic_only,
            }
        )
    return {
        "family_id": family_id,
        "pair_exact": exact,
        "scored_pairs": scored,
        "family_exact": bool(scored and exact == scored),
        "details": details,
    }


def guardrail_suite_report(root: Path | None = None, mutations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    base = resource_root(root)
    registry = load_registry(base)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        clean_pos = Orchestrator(root=base).run(load_public_case("QM-PB-001", base).model_dump(mode="json"), output_dir=out).state
        clean_neg = Orchestrator(root=base).run(load_public_case("QM-PB-006", base).model_dump(mode="json"), output_dir=out).state
    replay = build_decision(deepcopy(clean_pos), registry).model_dump(mode="json") == build_decision(
        deepcopy(clean_pos), registry
    ).model_dump(mode="json")
    clean = [
        build_decision(deepcopy(clean_pos), registry).authoritative_verdict,
        build_decision(deepcopy(clean_neg), registry).authoritative_verdict,
    ]
    expected_clean = [Verdict.POSITIVE, Verdict.NEGATIVE]
    false_block = sum(1 for verdict, expected in zip(clean, expected_clean, strict=True) if verdict is not expected) / 2
    details: list[dict[str, Any]] = []
    for row in mutations or _guardrail_mutations():
        state = deepcopy(clean_neg if row.get("base") == "negative" else clean_pos)
        row["mutate"](state)
        verdict = build_decision(state, registry).authoritative_verdict
        expected = row.get("expected")
        caught = verdict is expected if expected else verdict is not Verdict.POSITIVE
        details.append(
            {
                "mutation_id": row["id"],
                "expected": expected.value if expected else "NOT_POSITIVE",
                "actual": verdict.value,
                "caught": caught,
            }
        )
    caught_count = sum(int(item["caught"]) for item in details)
    return {
        "mutation_count": len(details),
        "caught_count": caught_count,
        "guardrail_pass": bool(len(details) == 10 and caught_count == 10 and false_block == 0 and replay),
        "validator_catch_rate": caught_count / len(details) if details else 1.0,
        "false_block_rate_on_clean_states": false_block,
        "deterministic_replay": replay,
        "details": details,
    }


def _with_run_metadata(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    payload["run_provider"] = getattr(provider, "provider_name", "unknown")
    payload["run_model"] = getattr(provider, "model_name", "unknown")
    payload["benchmark_label"] = "fixture_self_test" if payload["run_provider"] == "mock" else "live_model_run"
    return payload


def _projection(state: RunState, decision: DecisionCard) -> dict[str, Any]:
    candidate = state.candidate_card or CandidateCard()
    return {
        "selected_primitive": candidate.selected_candidate,
        "verdict": decision.authoritative_verdict.value,
        "scope": decision.maximum_supported_claim_scope.value,
    }


def _field_delta_ok(seed: dict[str, Any], variant: dict[str, Any], relation: GoldRelation) -> bool:
    return all(seed[field] != variant[field] for field in relation.required_changed_fields) and all(
        seed[field] == variant[field] for field in relation.required_invariant_fields
    )


def _relation(seed_state: RunState, seed_decision: DecisionCard, state: RunState, decision: DecisionCard) -> str:
    seed_candidate = seed_state.candidate_card or CandidateCard()
    candidate = state.candidate_card or CandidateCard()
    if decision.authoritative_verdict in {Verdict.CONDITIONAL, Verdict.INVALID}:
        return "FORCE_ABSTAIN"
    if decision.authoritative_verdict is Verdict.NEGATIVE and seed_decision.authoritative_verdict is Verdict.POSITIVE:
        return "WEAKEN"
    return "DIRECTIONAL_CHANGE" if candidate.selected_candidate != seed_candidate.selected_candidate else "PRESERVE"


def _candidate(state: RunState) -> CandidateCard:
    if state.candidate_card is None:
        raise ValueError("mutation requires CandidateCard")
    return state.candidate_card


def _add_query_blocker(state: RunState) -> None:
    _candidate(state).barriers.append(
        BarrierAssessment(
            barrier_id="loading_condition_readout",
            description="blocks query",
            applicable=EvidenceState.SUPPORTED,
            blocked_scopes=[ClaimScope.QUERY],
        )
    )


def _guardrail_mutations() -> list[dict[str, Any]]:
    return [
        {"id": "B1", "expected": Verdict.INVALID, "mutate": _selected_mismatch},
        {"id": "B2", "expected": Verdict.INVALID, "mutate": _wrong_structure},
        {"id": "B3", "expected": Verdict.CONDITIONAL, "mutate": lambda s: _candidate(s).scheme_steps.clear()},
        {"id": "B4", "expected": Verdict.INVALID, "mutate": lambda s: setattr(_problem(s), "access_model", "sample_only")},
        {"id": "B5", "expected": Verdict.INVALID, "mutate": lambda s: setattr(_problem(s), "output_contract", "bad")},
        {"id": "B6", "expected": Verdict.CONDITIONAL, "mutate": lambda s: setattr(_problem(s), "promises", [])},
        {"id": "B7", "expected": Verdict.NEGATIVE, "mutate": _add_query_blocker},
        {"id": "B8", "expected": Verdict.INVALID, "mutate": _scope_escalation},
        {"id": "B9", "expected": Verdict.INVALID, "mutate": _prior_art_overclaim},
        {"id": "B10", "expected": Verdict.INVALID, "mutate": _gold_leak},
    ]


def _wrong_structure(state: RunState) -> None:
    if state.analysis_card is None:
        raise ValueError("mutation requires AnalysisCard")
    state.analysis_card.canonical_structure_ids = ["wrong"]


def _problem(state: RunState) -> Any:
    if state.problem_card is None:
        raise ValueError("mutation requires ProblemCard")
    return state.problem_card


def _selected_mismatch(state: RunState) -> None:
    _candidate(state).selected_candidate = "bad"


def _scope_escalation(state: RunState) -> None:
    _candidate(state).claim_scope = ClaimScope.END_TO_END


def _gold_leak(state: RunState) -> None:
    state.messages.append({"gold": {"expected_selected_primitive": "x"}})


def _prior_art_overclaim(state: RunState) -> None:
    candidate = _candidate(state)
    candidate.prior_art_status = PriorArtStatus.KNOWN_CASE_RECOVERY
    candidate.novelty_status = NoveltyStatus.GLOBAL_NOVELTY_CLAIM


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else None


def count_loc(root: Path | None = None) -> dict[str, Any]:
    base = project_root(root) / "src" / "quantummindlite"
    if not base.exists():
        base = Path(__file__).resolve().parent
    files = sorted(base.rglob("*.py"))
    per_file: dict[str, dict[str, int]] = {}
    total = 0
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        physical = len(lines)
        code = sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))
        total += code
        relative = path.relative_to(base).as_posix()
        per_file[relative] = {"physical": physical, "nonblank_noncomment": code}
    limits = {"production_files": 18, "total_nonblank_noncomment": 4000, "physical_per_file": 600}
    return {
        "production_files": len(files),
        "total_nonblank_noncomment": total,
        "per_file": per_file,
        "limits": limits,
        "ok": (
            len(files) <= limits["production_files"]
            and total <= limits["total_nonblank_noncomment"]
            and all(item["physical"] <= limits["physical_per_file"] for item in per_file.values())
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())

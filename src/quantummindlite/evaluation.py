from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import Field

from .models import CandidateCard, ClaimScope, DecisionCard, Route, RunState, SpeedupClass, StrictModel, Verdict
from .registry import load_registry, load_source_catalog, resource_root
from .storage import digest_json
from .validation import RULE_IDS, build_decision, route_decision

T = TypeVar("T", bound=StrictModel)


class PublicCase(StrictModel):
    case_id: str
    statement: str
    input_model: str
    access_model: str
    output_contract: str
    promises: list[str] = Field(default_factory=list)
    size_parameters: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class GoldCase(StrictModel):
    case_id: str
    access_model: str
    output_contract: str
    required_structure_ids: list[str]
    expected_selected_primitive: str | None = None
    expected_speedup_class: SpeedupClass
    required_caveat_ids: list[str] = Field(default_factory=list)
    allowed_verdicts: list[Verdict]
    maximum_claim_scope: ClaimScope
    expected_route: Route
    forbidden_claim_ids: list[str] = Field(default_factory=list)
    evidence_mapping: dict[str, list[str]]


class EvidenceCase(StrictModel):
    case_id: str
    title: str
    authors: list[str]
    year: int
    venue: str
    official_url: str
    result_location: str
    result_type: str
    paraphrased_support: str
    problem_model: str
    promise: str
    access_model: str
    output_contract: str
    classical_complexity: str
    quantum_complexity: str
    claim_scope: ClaimScope
    caveats: list[str]
    source_status: str


class ScoreReport(StrictModel):
    case_id: str
    raw_reasoning_score: dict[str, Any]
    system_score: dict[str, Any]
    public_digest: str
    gold_digest: str
    evidence_digest: str


class FamilyVariant(StrictModel):
    variant_id: str
    public_case: PublicCase


class PublicFamily(StrictModel):
    family_id: str
    seed_variant_id: str
    variants: list[FamilyVariant]


class Projection(StrictModel):
    selected_primitive: str | None = None
    verdict: Verdict
    scope: ClaimScope


class GoldRelation(StrictModel):
    variant_id: str
    expected_relation: str
    diagnostic_only: bool = False
    seed_projection: Projection | None = None
    variant_projection: Projection | None = None
    required_changed_fields: list[str] = Field(default_factory=list)
    required_invariant_fields: list[str] = Field(default_factory=list)


class GoldFamily(StrictModel):
    family_id: str
    seed_variant_id: str
    relations: list[GoldRelation]
    public_digest: str


PUBLIC_FORBIDDEN_TERMS = {
    "grover",
    "shor",
    "hhl",
    "harrow",
    "hassidim",
    "lloyd",
    "ambainis",
    "hoyer",
    "neerbek",
    "shi",
    "van dam",
    "beals",
    "amplitude amplification",
    "amplitude estimation",
    "qft",
    "quantum walk",
    "expected_primitive",
    "expected_verdict",
    "official_url",
    "theorem",
}


def load_yaml_model(path: Path, model: type[T]) -> T:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return model.model_validate(data)


def load_public_case(case_id: str, root: Path | None = None) -> PublicCase:
    return load_yaml_model(resource_root(root) / "paperbench" / "public" / f"{case_id}.yaml", PublicCase)


def load_gold_case(case_id: str, root: Path | None = None) -> GoldCase:
    return load_yaml_model(resource_root(root) / "paperbench" / "gold" / f"{case_id}.yaml", GoldCase)


def load_evidence_case(case_id: str, root: Path | None = None) -> EvidenceCase:
    return load_yaml_model(resource_root(root) / "paperbench" / "evidence" / f"{case_id}.yaml", EvidenceCase)


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    path = resource_root(root) / "paperbench" / "manifest.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def validate_paperbench(root: Path | None = None) -> dict[str, Any]:
    base = resource_root(root)
    manifest = load_manifest(base)
    ready = list(manifest.get("ready_cases", []))
    source_ids = set(load_source_catalog(base))
    registry = load_registry(base)
    errors: list[str] = []
    if len(ready) != 10:
        errors.append("manifest must contain exactly ten ready cases")
    for case_id in ready:
        public = load_public_case(case_id, base)
        gold = load_gold_case(case_id, base)
        evidence = load_evidence_case(case_id, base)
        errors.extend(_validate_case(public, gold, evidence, source_ids, registry))
    errors.extend(_validate_freeze_manifest(base))
    return {"ready_count": len(ready), "errors": errors, "ok": not errors}


def score_case(case_id: str, state: RunState, decision: DecisionCard, root: Path | None = None) -> ScoreReport:
    base = resource_root(root)
    public = load_public_case(case_id, base)
    gold = load_gold_case(case_id, base)
    evidence = load_evidence_case(case_id, base)
    registry = load_registry(base)
    candidate = state.candidate_card or CandidateCard()
    recomputed = build_decision(state, registry)
    integrity_ok = decision.model_dump(mode="json") == recomputed.model_dump(mode="json")
    raw = _raw_score(state, candidate, gold, registry)
    system = _system_score(raw["raw_pass"], candidate, recomputed, gold, integrity_ok)
    return ScoreReport(
        case_id=case_id,
        raw_reasoning_score=raw,
        system_score=system,
        public_digest=digest_json(public.model_dump(mode="json")),
        gold_digest=digest_json(gold.model_dump(mode="json")),
        evidence_digest=digest_json(evidence.model_dump(mode="json")),
    )


def build_freeze_manifest(root: Path | None = None) -> dict[str, Any]:
    base = resource_root(root)
    manifest = load_manifest(base)
    files = {rel: _file_digest(path) for rel, path in _freeze_paths(base).items()}
    return {
        "freeze_id": f"{manifest.get('benchmark_id', 'PaperBench')}-{manifest.get('version', 'unknown')}",
        "benchmark_version": manifest.get("version", "unknown"),
        "created_at": datetime.now(UTC).isoformat(),
        "git": _git_state(base),
        "b_rule_implementation": {"identifier": "quantummindlite.validation:RULE_IDS", "rule_ids": list(RULE_IDS)},
        "files": files,
    }


def write_freeze_manifest(root: Path | None = None) -> dict[str, Any]:
    base = resource_root(root)
    data = build_freeze_manifest(base)
    (base / "paperbench" / "freeze_manifest.yaml").write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return data


def _validate_case(public: PublicCase, gold: GoldCase, evidence: EvidenceCase, source_ids: set[str], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if len({public.case_id, gold.case_id, evidence.case_id}) != 1:
        errors.append(f"{public.case_id}: public/gold/evidence IDs differ")
    if public.access_model != gold.access_model or public.access_model != evidence.access_model:
        errors.append(f"{public.case_id}: access model mismatch")
    if public.output_contract != gold.output_contract or public.output_contract != evidence.output_contract:
        errors.append(f"{public.case_id}: output contract mismatch")
    for key in _gold_schema_fields():
        mapped = gold.evidence_mapping.get(key, [])
        if not mapped:
            errors.append(f"{public.case_id}: gold field {key} lacks evidence mapping")
        if any(source_id not in source_ids for source_id in mapped):
            errors.append(f"{public.case_id}: gold field {key} maps to unknown source_id")
    if _scope_rank(gold.maximum_claim_scope) > _scope_rank(evidence.claim_scope):
        errors.append(f"{public.case_id}: gold scope exceeds evidence scope")
    routes = {route_decision(verdict, []) for verdict in gold.allowed_verdicts}
    if len(routes) != 1 or gold.expected_route not in routes:
        errors.append(f"{public.case_id}: allowed_verdicts do not map to expected_route")
    if gold.expected_speedup_class is SpeedupClass.ASYMPTOTIC and gold.expected_selected_primitive:
        spec = registry.get(gold.expected_selected_primitive)
        if spec is None:
            errors.append(f"{public.case_id}: expected primitive missing from registry")
        elif _scope_rank(gold.maximum_claim_scope) > _scope_rank(spec.supported_claim_scope):
            errors.append(f"{public.case_id}: gold scope exceeds registered primitive scope")
    if not evidence.official_url.startswith("https://"):
        errors.append(f"{public.case_id}: official URL missing")
    if "CLASSICAL:" not in evidence.classical_complexity:
        errors.append(f"{public.case_id}: classical complexity must be scope-tagged")
    if gold.expected_speedup_class is not SpeedupClass.NONE and "QUERY:" not in evidence.quantum_complexity:
        errors.append(f"{public.case_id}: quantum complexity must be scope-tagged")
    text = json.dumps(public.model_dump(mode="json"), sort_keys=True).lower()
    errors.extend(f"{public.case_id}: public file contains forbidden clue {term!r}" for term in PUBLIC_FORBIDDEN_TERMS if term in text)
    return errors


def _raw_score(state: RunState, candidate: CandidateCard, gold: GoldCase, registry: dict[str, Any]) -> dict[str, Any]:
    structures = set(state.analysis_card.canonical_structure_ids if state.analysis_card else [])
    structure_ok = set(gold.required_structure_ids) <= structures
    primitive_ok = _primitive_ok(candidate, gold)
    speedup_ok = _speedup_ok(candidate, gold, registry)
    caveat_recall = _caveat_recall(candidate, gold)
    scheme_complete = True if gold.expected_speedup_class is not SpeedupClass.ASYMPTOTIC else _scheme_complete(candidate)
    candidate_scope_ok = _candidate_scope_ok(candidate, gold, registry)
    raw_pass = bool(structure_ok and primitive_ok and speedup_ok and caveat_recall >= 1.0 and scheme_complete and candidate_scope_ok)
    return {
        "structure_ok": structure_ok,
        "primitive_ok": primitive_ok,
        "speedup_class_ok": speedup_ok,
        "required_caveat_recall": caveat_recall,
        "scheme_complete": scheme_complete,
        "candidate_scope_ok": candidate_scope_ok,
        "raw_pass": raw_pass,
    }


def _system_score(
    raw_pass: bool, candidate: CandidateCard, decision: DecisionCard, gold: GoldCase, decision_integrity_ok: bool
) -> dict[str, Any]:
    verdict_ok = decision.authoritative_verdict in gold.allowed_verdicts
    scope_ok = decision.maximum_supported_claim_scope is gold.maximum_claim_scope
    route_ok = decision.d_route is gold.expected_route
    caveats_ok = _caveat_recall(candidate, gold) >= 1.0
    overclaim_ok = not (set(candidate.claim_flags) & set(gold.forbidden_claim_ids))
    integrity_ok = decision_integrity_ok and tuple(item.rule_id for item in decision.b_check_results) == RULE_IDS
    return {
        "raw_pass": raw_pass,
        "verdict_ok": verdict_ok,
        "scope_ok": scope_ok,
        "route_ok": route_ok,
        "required_caveats_preserved": caveats_ok,
        "unsupported_overclaim_absent": overclaim_ok,
        "deterministic_integrity_ok": integrity_ok,
        "route": decision.d_route.value,
        "system_pass": bool(raw_pass and verdict_ok and scope_ok and route_ok and caveats_ok and overclaim_ok and integrity_ok),
    }


def _primitive_ok(candidate: CandidateCard, gold: GoldCase) -> bool:
    if gold.expected_selected_primitive is None:
        return candidate.selected_candidate is None and bool(candidate.no_candidate_reason)
    return candidate.selected_candidate == gold.expected_selected_primitive


def _speedup_ok(candidate: CandidateCard, gold: GoldCase, registry: dict[str, Any]) -> bool:
    if candidate.selected_candidate is None:
        return gold.expected_speedup_class is SpeedupClass.NONE
    spec = registry.get(candidate.selected_candidate)
    return bool(spec and spec.speedup_class is gold.expected_speedup_class)


def _caveat_recall(candidate: CandidateCard, gold: GoldCase) -> float:
    required = set(gold.required_caveat_ids)
    if not required:
        return 1.0
    observed = {item.barrier_id for item in candidate.barriers}
    return len(required & observed) / len(required)


def _candidate_scope_ok(candidate: CandidateCard, gold: GoldCase, registry: dict[str, Any]) -> bool:
    if gold.expected_speedup_class is SpeedupClass.CONSTANT_FACTOR_ONLY and candidate.selected_candidate in registry:
        return candidate.claim_scope is registry[candidate.selected_candidate].supported_claim_scope
    return candidate.claim_scope is gold.maximum_claim_scope


def _scheme_complete(candidate: CandidateCard) -> bool:
    if not candidate.scheme_steps or candidate.classical_baseline == "UNKNOWN":
        return False
    if candidate.claim_scope is ClaimScope.QUERY:
        return bool(candidate.quantum_query_complexity)
    if candidate.claim_scope is ClaimScope.GATE:
        return bool(candidate.gate_complexity)
    if candidate.claim_scope is ClaimScope.END_TO_END:
        return bool(candidate.total_complexity)
    return False


def _validate_freeze_manifest(base: Path) -> list[str]:
    path = base / "paperbench" / "freeze_manifest.yaml"
    if not path.exists():
        return ["freeze manifest missing"]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    expected = data.get("files", {})
    actual = {rel: _file_digest(file_path) for rel, file_path in _freeze_paths(base).items()}
    errors = [f"freeze digest mismatch: {rel}" for rel, digest in expected.items() if actual.get(rel) != digest]
    errors.extend(f"freeze manifest missing path: {rel}" for rel in actual if rel not in expected)
    ids = data.get("b_rule_implementation", {}).get("rule_ids", [])
    if ids != list(RULE_IDS):
        errors.append("freeze B-rule identifier mismatch")
    return errors


def _freeze_paths(base: Path) -> dict[str, Path]:
    paths = {
        "paperbench/manifest.yaml": base / "paperbench" / "manifest.yaml",
        "configs/primitives.yaml": base / "configs" / "primitives.yaml",
        "configs/sources.yaml": base / "configs" / "sources.yaml",
    }
    code_files = (
        "_graph_compile.py",
        "_graph_projection.py",
        "_graph_verify.py",
        "agent.py",
        "cli.py",
        "evaluation.py",
        "graph.py",
        "llm.py",
        "messages.py",
        "models.py",
        "openai_provider.py",
        "registry.py",
        "storage.py",
        "validation.py",
        "workflow.py",
    )
    paths.update({f"python/{name}": _code_path(base, name) for name in code_files})
    folders = (
        "prompts",
        "paperbench/public",
        "paperbench/gold",
        "paperbench/evidence",
        "paperbench/families/public",
        "paperbench/families/gold",
    )
    for folder in folders:
        pattern = "*.yaml" if "paperbench" in folder else "*.md"
        paths.update({str(path.relative_to(base)).replace("\\", "/"): path for path in sorted((base / folder).glob(pattern))})
    return dict(sorted(paths.items()))


def _code_path(base: Path, name: str) -> Path:
    copied = base / "src" / "quantummindlite" / name
    return copied if copied.exists() else Path(__file__).with_name(name)


def _file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git_state(base: Path) -> dict[str, Any]:
    def run(args: list[str]) -> str:
        return subprocess.check_output(args, cwd=base, text=True, stderr=subprocess.DEVNULL).strip()

    try:
        status = run(["git", "status", "--porcelain"])
        try:
            commit = run(["git", "rev-parse", "HEAD"])
            state = "ok"
        except Exception:
            commit = None
            state = "no commits"
        return {"commit": commit, "dirty": bool(status), "status": state}
    except Exception:
        return {"commit": None, "dirty": None, "status": "git unavailable"}


def _gold_schema_fields() -> tuple[str, ...]:
    return (
        "required_structure_ids",
        "expected_selected_primitive",
        "expected_speedup_class",
        "required_caveat_ids",
        "allowed_verdicts",
        "maximum_claim_scope",
        "expected_route",
        "forbidden_claim_ids",
    )


def _scope_rank(scope: ClaimScope) -> int:
    return {ClaimScope.NONE: 0, ClaimScope.QUERY: 1, ClaimScope.GATE: 2, ClaimScope.END_TO_END: 3}[scope]

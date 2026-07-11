from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from quantummindlite.cli import _benchmark_all, guardrail_suite_report, score_family
from quantummindlite.evaluation import PublicCase, load_public_case, score_case, validate_paperbench
from quantummindlite.llm import MockLLMProvider, ProviderResult
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import BarrierAssessment, ClaimScope, DecisionCard, EvidenceState, RunState
from quantummindlite.registry import resource_root
from quantummindlite.workflow import Orchestrator


class FailFirstCaseProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.failed = False

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.NOVELTY_AUDIT and not self.failed:
            self.failed = True
            raise ValueError("synthetic live-path failure")
        return super().generate(role, action, prompt, inputs, output_model)


def _run_case(case_id: str, tmp_path: Path) -> tuple[RunState, DecisionCard]:
    public = load_public_case(case_id)
    result = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
    return result.state, result.decision


def _copy_benchmark_root(tmp_path: Path) -> Path:
    root = resource_root()
    shutil.copytree(root / "paperbench", tmp_path / "paperbench")
    shutil.copytree(root / "configs", tmp_path / "configs")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tmp'\n", encoding="utf-8")
    return tmp_path


def _copy_freeze_root(tmp_path: Path) -> Path:
    root = _copy_benchmark_root(tmp_path)
    shutil.copytree(resource_root() / "prompts", root / "prompts")
    shutil.copytree(Path.cwd() / "src", root / "src")
    return root


def _rewrite_yaml(path: Path, updates: dict[str, Any]) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.update(updates)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_wrong_expected_route_fails_system_pass(tmp_path: Path) -> None:
    state, decision = _run_case("QM-PB-001", tmp_path)
    root = _copy_benchmark_root(tmp_path / "copy")
    _rewrite_yaml(root / "paperbench" / "gold" / "QM-PB-001.yaml", {"expected_route": "STOP"})
    score = score_case("QM-PB-001", state, decision, root)
    assert not score.system_score["route_ok"]
    assert not score.system_score["system_pass"]


def test_required_structure_subset_and_raw_failure_force_system_failure(tmp_path: Path) -> None:
    state, decision = _run_case("QM-PB-001", tmp_path)
    root = _copy_benchmark_root(tmp_path / "copy")
    _rewrite_yaml(
        root / "paperbench" / "gold" / "QM-PB-001.yaml",
        {"required_structure_ids": ["black_box_witness_search", "extra_required_structure"]},
    )
    score = score_case("QM-PB-001", state, decision, root)
    assert not score.raw_reasoning_score["structure_ok"]
    assert not score.raw_reasoning_score["raw_pass"]
    assert score.system_score["verdict_ok"]
    assert not score.system_score["system_pass"]


def test_unselected_plausible_primitive_does_not_earn_credit(tmp_path: Path) -> None:
    state, decision = _run_case("QM-PB-001", tmp_path)
    assert state.candidate_card is not None
    state.candidate_card.selected_candidate = None
    score = score_case("QM-PB-001", state, decision)
    assert not score.raw_reasoning_score["primitive_ok"]
    assert not score.system_score["system_pass"]


def test_missing_caveat_id_fails_recall(tmp_path: Path) -> None:
    state, decision = _run_case("QM-PB-001", tmp_path)
    assert state.candidate_card is not None
    state.candidate_card.limitations = []
    state.candidate_card.barriers = []
    state.candidate_card.limitations = ["oracle_construction"]
    score = score_case("QM-PB-001", state, decision)
    assert score.raw_reasoning_score["required_caveat_recall"] == 0.0
    assert not score.system_score["required_caveats_preserved"]


def test_stale_positive_decision_fails_integrity_after_state_mutation(tmp_path: Path) -> None:
    state, old_decision = _run_case("QM-PB-001", tmp_path)
    assert state.candidate_card is not None
    state.candidate_card.barriers.append(
        BarrierAssessment(
            barrier_id="loading_condition_readout",
            description="blocks the claimed query scope",
            applicable=EvidenceState.SUPPORTED,
            blocked_scopes=[ClaimScope.QUERY],
        )
    )
    score = score_case("QM-PB-001", state, old_decision)
    assert not score.system_score["deterministic_integrity_ok"]
    assert not score.system_score["system_pass"]


def test_scheme_completeness_uses_scope_specific_complexity(tmp_path: Path) -> None:
    state, decision = _run_case("QM-PB-003", tmp_path)
    assert state.candidate_card is not None
    state.candidate_card.claim_scope = ClaimScope.GATE
    state.candidate_card.quantum_query_complexity = None
    state.candidate_card.gate_complexity = "gate: polynomial under reversible evaluation"
    root = _copy_benchmark_root(tmp_path / "copy")
    _rewrite_yaml(root / "paperbench" / "gold" / "QM-PB-003.yaml", {"maximum_claim_scope": "GATE"})
    score = score_case("QM-PB-003", state, decision, root)
    assert score.raw_reasoning_score["scheme_complete"]


def test_guardrail_metrics_change_when_mutation_is_not_caught() -> None:
    report = guardrail_suite_report(mutations=[{"id": "uncaught_noop", "mutate": lambda state: None}])
    assert report["validator_catch_rate"] == 0.0
    assert report["caught_count"] == 0


def test_guardrail_suite_has_one_real_mutation_per_b_rule() -> None:
    report = guardrail_suite_report()
    ids = {item["mutation_id"] for item in report["details"]}
    assert ids == {f"B{index}" for index in range(1, 11)}
    assert report["guardrail_pass"]


def test_benchmark_all_reports_overall_pass(tmp_path: Path) -> None:
    result = _benchmark_all(resource_root(), str(tmp_path), MockLLMProvider())
    assert result["guardrail_pass"]
    assert result["overall_pass"]


def test_benchmark_all_records_case_error_and_continues(tmp_path: Path) -> None:
    result = _benchmark_all(resource_root(), str(tmp_path), FailFirstCaseProvider())
    errors = [item for item in result["cases"] if item.get("error")]
    assert len(result["cases"]) == 10
    assert len(errors) == 1
    assert "synthetic live-path failure" in errors[0]["error"]
    assert not result["overall_pass"]
    error_files = list(tmp_path.glob("*/error.json"))
    assert len(error_files) == 1
    assert "NOVELTY_AUDIT" in error_files[0].read_text(encoding="utf-8")
    assert (error_files[0].parent / "partial_state.json").exists()
    assert (error_files[0].parent / "trace.jsonl").exists()


def test_pair_relation_correct_but_projection_wrong_fails_pair_exact(tmp_path: Path) -> None:
    root = _copy_benchmark_root(tmp_path / "copy")
    gold_path = root / "paperbench" / "families" / "gold" / "PB-001-family.yaml"
    data = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    data["relations"][0]["seed_projection"]["selected_primitive"] = "amplitude_estimation"
    gold_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def run_variant(public: PublicCase) -> tuple[RunState, DecisionCard]:
        result = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
        return result.state, result.decision

    score = score_family(root, "PB-001-family", run_variant)
    first = score["details"][0]
    assert first["predicted_relation"] == first["expected_relation"]
    assert not first["seed_exact"]
    assert not first["pair_exact"]
    assert not score["family_exact"]


def test_tampered_freeze_manifest_fails_validation(tmp_path: Path) -> None:
    root = _copy_freeze_root(tmp_path / "copy")
    public_file = root / "paperbench" / "public" / "QM-PB-001.yaml"
    public_file.write_text(public_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = validate_paperbench(root)
    assert not result["ok"]
    assert "freeze digest mismatch" in " ".join(result["errors"])


def test_tampered_evaluator_code_fails_freeze_validation(tmp_path: Path) -> None:
    root = _copy_freeze_root(tmp_path / "copy")
    evaluator = root / "src" / "quantummindlite" / "evaluation.py"
    evaluator.write_text(evaluator.read_text(encoding="utf-8").replace("def _raw_score", "def _raw_score_tampered", 1), encoding="utf-8")
    result = validate_paperbench(root)
    assert not result["ok"]
    assert "freeze digest mismatch: python/evaluation.py" in " ".join(result["errors"])


def test_gold_allowed_verdict_route_inconsistency_fails_validation(tmp_path: Path) -> None:
    root = _copy_freeze_root(tmp_path / "copy")
    _rewrite_yaml(root / "paperbench" / "gold" / "QM-PB-004.yaml", {"allowed_verdicts": ["POSITIVE", "CONDITIONAL"]})
    result = validate_paperbench(root)
    assert not result["ok"]
    assert "allowed_verdicts do not map to expected_route" in " ".join(result["errors"])

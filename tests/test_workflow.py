from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantummindlite.agent import Agent
from quantummindlite.evaluation import load_public_case, score_case
from quantummindlite.llm import MockLLMProvider, ProviderResult, ProviderTrace
from quantummindlite.messages import ACTION_SEQUENCE, ActionType, Role
from quantummindlite.models import MatchStrength, Route, Verdict
from quantummindlite.workflow import Orchestrator


class RecordingProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.inputs_by_action: dict[ActionType, list[dict[str, Any]]] = {}
        self.calls: list[ActionType] = []

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        self.calls.append(action)
        self.inputs_by_action.setdefault(action, []).append(inputs)
        return super().generate(role, action, prompt, inputs, output_model)


class LiveLikeNoveltyProvider(RecordingProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.MATCH_PRIMITIVES:
            self.calls.append(action)
            self.inputs_by_action.setdefault(action, []).append(inputs)
            match_payload: dict[str, Any] = {
                "primitive_matches": [
                    {
                        "primitive_id": "amplitude_amplification",
                        "strength": "PLAUSIBLE",
                        "prerequisites": ["marked_item_exists"],
                    }
                ]
            }
            output_model.model_validate(match_payload)
            return ProviderResult(match_payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        if action is ActionType.NOVELTY_AUDIT:
            self.calls.append(action)
            self.inputs_by_action.setdefault(action, []).append(inputs)
            novelty_payload: dict[str, Any] = {"novelty_status": "NOT_GLOBALLY_NOVEL"}
            output_model.model_validate(novelty_payload)
            return ProviderResult(novelty_payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


class UnsupportedNoveltyProvider(LiveLikeNoveltyProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.MATCH_PRIMITIVES:
            self.calls.append(action)
            self.inputs_by_action.setdefault(action, []).append(inputs)
            payload: dict[str, Any] = {"primitive_matches": []}
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


def test_workflow_stage_order_and_agent_reuse(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-001")
    orchestrator = Orchestrator()
    assert all(isinstance(agent, Agent) for agent in orchestrator.agents.values())
    result = orchestrator.run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert result.stage_order == [action.value for action in ACTION_SEQUENCE]
    assert result.state.problem_card is not None
    assert result.state.analysis_card is not None
    assert result.state.candidate_card is not None
    assert result.decision.authoritative_verdict is Verdict.POSITIVE
    assert result.state.problem_card.statement == public.statement
    assert result.state.problem_card.input_model == public.input_model
    assert result.state.problem_card.access_model == public.access_model
    assert result.state.problem_card.output_contract == public.output_contract
    assert result.state.problem_card.promises == public.promises
    assert result.state.problem_card.size_parameters == public.size_parameters
    assert (result.run_dir / "input.json").exists()
    assert (result.run_dir / "state.json").exists()
    assert (result.run_dir / "decision.json").exists()
    assert (result.run_dir / "trace.jsonl").exists()


def test_orchestrator_has_no_automatic_revision_mode() -> None:
    assert "max_revision_rounds" not in inspect.signature(Orchestrator).parameters


def test_deterministic_mock_replay(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-005")
    first = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
    second = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert first.state.model_dump(mode="json") == second.state.model_dump(mode="json")
    assert first.decision.model_dump(mode="json") == second.decision.model_dump(mode="json")


def test_benchmark_score_written_after_state_and_decision(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-006")
    result = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
    score = score_case("QM-PB-006", result.state, result.decision)
    (result.run_dir / "score.json").write_text(score.model_dump_json(indent=2), encoding="utf-8")
    assert (result.run_dir / "state.json").stat().st_size > 0
    assert (result.run_dir / "decision.json").stat().st_size > 0
    assert (result.run_dir / "score.json").stat().st_size > 0


def test_registry_context_is_least_privilege_and_public(tmp_path: Path) -> None:
    provider = RecordingProvider()
    public = load_public_case("QM-PB-001")
    Orchestrator(provider=provider).run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert "registry_public_view" not in provider.inputs_by_action[ActionType.FORMALIZE][0]
    assert "registry_public_view" not in provider.inputs_by_action[ActionType.ANALYZE_STRUCTURE][0]
    assert "structure_vocabulary" in provider.inputs_by_action[ActionType.ANALYZE_STRUCTURE][0]
    assert "structure_vocabulary" not in provider.inputs_by_action[ActionType.MATCH_PRIMITIVES][0]
    assert "barrier_catalog_public_view" in provider.inputs_by_action[ActionType.BARRIER_PRECHECK][0]
    assert "barrier_catalog_public_view" in provider.inputs_by_action[ActionType.REVIEW_SCHEME][0]
    assert "barrier_catalog_public_view" not in provider.inputs_by_action[ActionType.MATCH_PRIMITIVES][0]
    assert "registry_public_view" in provider.inputs_by_action[ActionType.MATCH_PRIMITIVES][0]
    assert "source_catalog_public_view" in provider.inputs_by_action[ActionType.PRIOR_ART][0]
    assert "primitive_matches" in provider.inputs_by_action[ActionType.NOVELTY_AUDIT][0]
    assert "candidate_card" not in provider.inputs_by_action[ActionType.GENERATE_SCHEME][0]
    public_views = [
        provider.inputs_by_action[ActionType.MATCH_PRIMITIVES][0]["registry_public_view"],
        provider.inputs_by_action[ActionType.PRIOR_ART][0]["source_catalog_public_view"],
    ]
    matcher_registry = provider.inputs_by_action[ActionType.MATCH_PRIMITIVES][0]["registry_public_view"]
    assert all(item["speedup_class"] != "NONE" for item in matcher_registry)
    precheck_barriers = provider.inputs_by_action[ActionType.BARRIER_PRECHECK][0]["barrier_catalog_public_view"]
    review_barriers = provider.inputs_by_action[ActionType.REVIEW_SCHEME][0]["barrier_catalog_public_view"]
    assert {item["barrier_id"] for item in precheck_barriers} == {"oracle_construction", "query_only_scope"}
    assert {item["barrier_id"] for item in review_barriers} == {"oracle_construction", "query_only_scope"}
    assert "qm-pb-" not in str(public_views).lower()
    for action_inputs in provider.inputs_by_action.values():
        for inputs in action_inputs:
            text = str(inputs).lower()
            assert "expected_" not in text
            assert "gold" not in text
            assert "evidence_mapping" not in text


def test_no_targeted_revision_round_runs(tmp_path: Path) -> None:
    provider = RecordingProvider()
    public = load_public_case("QM-PB-001")
    result = Orchestrator(provider=provider).run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert provider.calls.count(ActionType.FORMALIZE) == 1
    assert provider.calls.count(ActionType.ANALYZE_STRUCTURE) == 1
    assert provider.calls.count(ActionType.MATCH_PRIMITIVES) == 1
    assert provider.calls.count(ActionType.GENERATE_SCHEME) == 1
    assert provider.calls.count(ActionType.REVIEW_SCHEME) == 1
    assert provider.calls.count(ActionType.NOVELTY_AUDIT) == 1
    assert provider.calls.count(ActionType.CONSISTENCY_REVIEW) == 1
    assert len(result.stage_order) == len(ACTION_SEQUENCE)


def test_live_like_novelty_known_case_uses_plausible_public_source(tmp_path: Path) -> None:
    provider = LiveLikeNoveltyProvider()
    public = load_public_case("QM-PB-001")
    result = Orchestrator(provider=provider).run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.novelty_status.value == "NOT_GLOBALLY_NOVEL"
    novelty_inputs = provider.inputs_by_action[ActionType.NOVELTY_AUDIT][0]
    assert novelty_inputs["primitive_matches"] == [
        {
            "primitive_id": "amplitude_amplification",
            "strength": "PLAUSIBLE",
            "prerequisites": ["marked_item_exists"],
        }
    ]


def test_unsupported_not_globally_novel_is_downgraded_not_crashed(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-001")
    result = Orchestrator(provider=UnsupportedNoveltyProvider()).run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.novelty_status.value == "UNASSESSED"


def test_estimation_like_explicit_algorithm_card_is_weak_analogy(tmp_path: Path) -> None:
    public = {
        "statement": "Estimate a numerical quantity produced by a classical randomized approximation routine.",
        "input_model": "algorithm_wiki_algorithm_record",
        "access_model": "explicit_numeric_parameters",
        "output_contract": "approximation_solution",
        "promises": [],
        "size_parameters": ["n", "epsilon"],
        "ambiguities": ["No coherent estimation oracle or bounded-random-variable promise is represented."],
    }
    result = Orchestrator().run(public, output_dir=tmp_path)
    candidate = result.state.candidate_card
    assert candidate is not None
    assert len(candidate.primitive_matches) == 1
    match = candidate.primitive_matches[0]
    assert match.primitive_id == "amplitude_estimation"
    assert match.strength is MatchStrength.WEAK_ANALOGY
    assert match.prerequisites == [
        "represented access/output promises must hold",
        "access_model='explicit_numeric_parameters' not in ['coherent_estimation_oracle']",
        "output_contract='approximation_solution' not in ['additive_estimate']",
        "missing required promises: bounded_random_variable, coherent_access",
    ]
    assert candidate.selected_candidate is None
    assert candidate.weak_analogy_opportunities
    note = candidate.weak_analogy_opportunities[0]
    assert note.primitive_id == "amplitude_estimation"
    assert "access_model='explicit_numeric_parameters'" in note.missing_access_or_output_or_promises[0]
    assert "Structural similarity" in note.why_not_selected
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE
    assert result.decision.d_route is Route.STOP

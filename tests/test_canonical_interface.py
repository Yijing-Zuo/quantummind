from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from quantummindlite.evaluation import load_public_case
from quantummindlite.llm import MockLLMProvider, ProviderResult, ProviderTrace
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import CheckOutcome, Verdict
from quantummindlite.registry import barrier_catalog_public_view, load_barrier_catalog, load_registry, structure_vocabulary
from quantummindlite.workflow import Orchestrator


class ScriptedProvider(MockLLMProvider):
    def __init__(self, overrides: dict[ActionType, dict[str, Any]]) -> None:
        self.overrides = overrides
        self.inputs_by_action: dict[ActionType, list[dict[str, Any]]] = {}

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        self.inputs_by_action.setdefault(action, []).append(inputs)
        if action in self.overrides:
            payload = {key: value for key, value in self.overrides[action].items() if key in output_model.model_fields}
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


class R2ParaphrasingProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.FORMALIZE and "access_model" in output_model.model_fields:
            public = inputs["public_case"]
            payload = {
                "statement": public["statement"],
                "input_model": public["input_model"],
                "access_model": "Coherent Boolean oracle access to the predicate",
                "output_contract": "Output one witness satisfying the predicate",
                "promises": ["At least one marked item exists."],
                "size_parameters": public["size_parameters"],
                "ambiguities": public.get("ambiguities", []),
            }
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


class SchemeProseProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.GENERATE_SCHEME:
            payload = super().generate(role, action, prompt, inputs, output_model).payload
            payload["limitations"] = ["Output one witness satisfying the predicate; at least one marked item exists."]
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


def test_r2_formalizer_paraphrases_cannot_alter_problem_card(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-001")
    result = Orchestrator(provider=R2ParaphrasingProvider()).run(public.model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.problem_card is not None
    assert result.state.problem_card.statement == public.statement
    assert result.state.problem_card.input_model == public.input_model
    assert result.state.problem_card.access_model == public.access_model
    assert result.state.problem_card.output_contract == public.output_contract
    assert result.state.problem_card.promises == public.promises
    assert result.state.problem_card.size_parameters == public.size_parameters


def test_scheme_prose_does_not_feed_b5_or_b6(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-001")
    result = Orchestrator(provider=SchemeProseProvider()).run(public.model_dump(mode="json"), output_dir=tmp_path)
    outcomes = {item.rule_id: item.outcome for item in result.decision.b_check_results}
    assert outcomes["B5_OUTPUT_CONTRACT_COMPATIBLE"] is CheckOutcome.PASS
    assert outcomes["B6_REQUIRED_PROMISES_REPRESENTED"] is CheckOutcome.PASS
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_unknown_structure_id_is_rejected_before_merge(tmp_path: Path) -> None:
    payload = MockLLMProvider()._analyze(
        "witness_search",
        load_public_case("QM-PB-001").model_dump(mode="json"),
    )
    payload["canonical_structure_ids"] = ["unstructured_search"]
    with pytest.raises(ValueError, match="unknown canonical_structure_ids"):
        Orchestrator(provider=ScriptedProvider({ActionType.ANALYZE_STRUCTURE: payload})).run(
            load_public_case("QM-PB-001").model_dump(mode="json"),
            output_dir=tmp_path,
        )


def test_legitimate_no_candidate_output_is_normalized(tmp_path: Path) -> None:
    no_candidate_payload = {
        "selected_candidate": None,
        "no_candidate_reason": "No represented registry primitive applies.",
        "scheme_steps": ["try a generic quantum routine anyway"],
        "classical_baseline": "Theta(N log N)",
        "quantum_query_complexity": "query: unknown",
        "gate_complexity": "gate: unknown",
        "total_complexity": "total: unknown",
        "claim_scope": "QUERY",
        "limitations": ["comparison_lower_bound"],
        "expert_questions": ["Could extra structure be promised?"],
        "claim_flags": [],
        "self_assessment": "negative_or_out_of_scope",
    }
    result = Orchestrator(provider=ScriptedProvider({ActionType.GENERATE_SCHEME: no_candidate_payload})).run(
        load_public_case("QM-PB-006").model_dump(mode="json"),
        output_dir=tmp_path,
    )
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.scheme_steps == []
    assert result.state.candidate_card.quantum_query_complexity is None
    assert result.state.candidate_card.gate_complexity is None
    assert result.state.candidate_card.total_complexity is None
    assert result.state.candidate_card.claim_scope.value == "NONE"
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE


def test_no_candidate_with_plausible_match_fails_b1(tmp_path: Path) -> None:
    payload = MockLLMProvider()._scheme(
        "ordered_search",
        load_public_case("QM-PB-007").model_dump(mode="json"),
        {"classical_baseline": "Theta(log N)"},
    )
    payload["selected_candidate"] = None
    payload["no_candidate_reason"] = "Constant-factor pathways are not candidates."
    payload["scheme_steps"] = []
    payload["quantum_query_complexity"] = None
    payload["claim_scope"] = "NONE"
    result = Orchestrator(provider=ScriptedProvider({ActionType.GENERATE_SCHEME: payload})).run(
        load_public_case("QM-PB-007").model_dump(mode="json"),
        output_dir=tmp_path,
    )
    b1 = next(item for item in result.decision.b_check_results if item.rule_id == "B1_SELECTED_MATCH_CONSISTENCY")
    assert b1.outcome is CheckOutcome.FAIL
    assert result.decision.authoritative_verdict is Verdict.INVALID


def test_all_registry_structure_ids_are_accepted(tmp_path: Path) -> None:
    payload = MockLLMProvider()._analyze(
        "witness_search",
        load_public_case("QM-PB-001").model_dump(mode="json"),
    )
    payload["canonical_structure_ids"] = structure_vocabulary(load_registry())
    result = Orchestrator(provider=ScriptedProvider({ActionType.ANALYZE_STRUCTURE: payload})).run(
        load_public_case("QM-PB-001").model_dump(mode="json"),
        output_dir=tmp_path,
    )
    assert result.state.analysis_card is not None
    assert result.state.analysis_card.canonical_structure_ids == structure_vocabulary(load_registry())


def test_valid_structure_plus_invented_synonym_is_rejected(tmp_path: Path) -> None:
    payload = MockLLMProvider()._analyze(
        "witness_search",
        load_public_case("QM-PB-001").model_dump(mode="json"),
    )
    payload["canonical_structure_ids"] = ["black_box_witness_search", "unstructured_search"]
    with pytest.raises(ValueError, match="unknown canonical_structure_ids"):
        Orchestrator(provider=ScriptedProvider({ActionType.ANALYZE_STRUCTURE: payload})).run(
            load_public_case("QM-PB-001").model_dump(mode="json"),
            output_dir=tmp_path,
        )


def test_unknown_primitive_id_is_rejected_before_merge(tmp_path: Path) -> None:
    payload = {
        "primitive_matches": [
            {
                "primitive_id": "amplitude_amplification_like",
                "strength": "PLAUSIBLE",
                "prerequisites": ["marked_item_exists"],
            }
        ]
    }
    with pytest.raises(ValueError, match="unknown primitive_ids"):
        Orchestrator(provider=ScriptedProvider({ActionType.MATCH_PRIMITIVES: payload})).run(
            load_public_case("QM-PB-001").model_dump(mode="json"),
            output_dir=tmp_path,
        )


def test_structure_vocabulary_does_not_require_gold_or_evidence(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "paperbench").mkdir()
    (tmp_path / "paperbench" / "manifest.yaml").write_text("ready_cases: []\n", encoding="utf-8")
    (tmp_path / "configs" / "primitives.yaml").write_text(
        "\n".join(
            [
                "primitives:",
                "  - primitive_id: toy_primitive",
                "    required_structure_ids: [toy_structure]",
                "    allowed_access_models: [toy_access]",
                "    allowed_output_contracts: [toy_output]",
                "    required_promises: [toy_promise]",
                "    supported_claim_scope: QUERY",
                "    speedup_class: ASYMPTOTIC",
                '    classical_complexity: "CLASSICAL: toy"',
                '    quantum_complexity: "QUERY: toy"',
                "    common_barriers: []",
                "    source_ids: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert structure_vocabulary(load_registry(tmp_path)) == ["toy_structure"]
    assert not (tmp_path / "paperbench" / "gold").exists()
    assert not (tmp_path / "paperbench" / "evidence").exists()


def test_barrier_catalog_validates_common_barrier_references(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "paperbench").mkdir()
    (tmp_path / "paperbench" / "manifest.yaml").write_text("ready_cases: []\n", encoding="utf-8")
    (tmp_path / "configs" / "primitives.yaml").write_text(
        "\n".join(
            [
                "barriers: []",
                "primitives:",
                "  - primitive_id: toy_primitive",
                "    required_structure_ids: [toy_structure]",
                "    allowed_access_models: [toy_access]",
                "    allowed_output_contracts: [toy_output]",
                "    required_promises: [toy_promise]",
                "    supported_claim_scope: QUERY",
                "    speedup_class: ASYMPTOTIC",
                '    classical_complexity: "CLASSICAL: toy"',
                '    quantum_complexity: "QUERY: toy"',
                "    common_barriers: [missing_barrier]",
                "    source_ids: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="common_barriers"):
        load_registry(tmp_path)


def test_barrier_catalog_public_view_has_no_gold_or_evidence_terms() -> None:
    view = barrier_catalog_public_view(load_barrier_catalog())
    assert {item["barrier_id"] for item in view}
    text = str(view).lower()
    assert "qm-pb-" not in text
    assert "expected_" not in text
    assert "gold" not in text


def test_runtime_context_filters_gold_and_evidence_like_extra_keys(tmp_path: Path) -> None:
    public = load_public_case("QM-PB-001").model_dump(mode="json")
    public["gold"] = {"expected_selected_primitive": "amplitude_amplification"}
    public["evidence_mapping"] = {"expected_selected_primitive": ["hidden"]}
    provider = ScriptedProvider({})
    Orchestrator(provider=provider).run(public, output_dir=tmp_path)
    for action_inputs in provider.inputs_by_action.values():
        for inputs in action_inputs:
            text = str(inputs).lower()
            assert "gold" not in text
            assert "expected_selected_primitive" not in text
            assert "evidence_mapping" not in text

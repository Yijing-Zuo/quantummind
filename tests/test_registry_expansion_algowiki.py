from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from quantummindlite.llm import MockLLMProvider, ProviderResult, ProviderTrace
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import (
    AnalysisCard,
    CandidateCard,
    CheckOutcome,
    ClaimScope,
    MatchStrength,
    PrimitiveMatch,
    ProblemCard,
    Route,
    RunState,
    SpeedupClass,
    Verdict,
)
from quantummindlite.registry import load_registry, load_runtime_registry, load_source_catalog, resource_root
from quantummindlite.validation import RULE_IDS, build_decision
from quantummindlite.workflow import Orchestrator

NEW_PRIMITIVES = (
    "quantum_minimum_finding",
    "quantum_backtracking_tree_search",
    "quantum_walk_marked_vertex_search",
    "quantum_counting",
)

NEW_BARRIERS = ("backtracking_tree_bounds", "walk_spectral_gap")

DEFERRED_PRIMITIVES = (
    "hamiltonian_simulation",
    "block_encoding_qsvt_linear_algebra",
    "quantum_phase_estimation_eigenvalue",
)


class OverrideProvider(MockLLMProvider):
    def __init__(self, overrides: dict[ActionType, dict[str, Any]]) -> None:
        self.overrides = overrides

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action in self.overrides:
            payload = self.overrides[action]
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


def _resource_yaml(name: str) -> dict[str, Any]:
    path = resource_root() / "configs" / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _positive_state(primitive_id: str) -> RunState:
    spec = load_registry()[primitive_id]
    return RunState(
        problem_card=ProblemCard(
            statement=f"Synthetic positive fixture for {primitive_id}.",
            input_model="synthetic_query_model",
            access_model=spec.allowed_access_models[0],
            output_contract=spec.allowed_output_contracts[0],
            promises=list(spec.required_promises),
            size_parameters=["N: represented problem size"],
        ),
        analysis_card=AnalysisCard(
            formalized_problem=f"Synthetic formalization for {primitive_id}.",
            canonical_structure_ids=list(spec.required_structure_ids),
            absent_or_weak_structures=[],
            classical_baseline=spec.classical_complexity,
            bottleneck="query complexity under represented oracle access",
            complexity_model="query_model",
        ),
        candidate_card=CandidateCard(
            primitive_matches=[PrimitiveMatch(primitive_id=primitive_id, strength=MatchStrength.PLAUSIBLE)],
            selected_candidate=primitive_id,
            scheme_steps=["prepare represented oracle", "apply registered primitive", "return contracted output"],
            classical_baseline=spec.classical_complexity,
            quantum_query_complexity=spec.quantum_complexity,
            claim_scope=ClaimScope.QUERY,
        ),
    )


def _incompatible_selected_state(
    primitive_id: str,
    *,
    access_model: str,
    output_contract: str,
    promises: list[str],
    structures: list[str],
) -> RunState:
    spec = load_registry()[primitive_id]
    return RunState(
        problem_card=ProblemCard(
            statement="Synthetic incompatible full-output or mismatched-access fixture.",
            input_model="synthetic_query_model",
            access_model=access_model,
            output_contract=output_contract,
            promises=promises,
        ),
        analysis_card=AnalysisCard(
            formalized_problem="Synthetic incompatible fixture.",
            canonical_structure_ids=structures,
            absent_or_weak_structures=[],
            classical_baseline=spec.classical_complexity,
            bottleneck="full output or missing oracle structure",
            complexity_model="query_model",
        ),
        candidate_card=CandidateCard(
            primitive_matches=[PrimitiveMatch(primitive_id=primitive_id, strength=MatchStrength.PLAUSIBLE)],
            selected_candidate=primitive_id,
            scheme_steps=["attempt to apply primitive"],
            classical_baseline=spec.classical_complexity,
            quantum_query_complexity=spec.quantum_complexity,
            claim_scope=ClaimScope.QUERY,
        ),
    )


def test_registry_expansion_entries_load_and_are_unique() -> None:
    registry, barriers = load_runtime_registry()
    sources = load_source_catalog()
    primitive_yaml = _resource_yaml("primitives.yaml")
    source_yaml = _resource_yaml("sources.yaml")

    primitive_ids = [item["primitive_id"] for item in primitive_yaml["primitives"]]
    barrier_ids = [item["barrier_id"] for item in primitive_yaml["barriers"]]
    source_ids = [item["source_id"] for item in source_yaml["sources"]]

    assert len(primitive_ids) == len(set(primitive_ids))
    assert len(barrier_ids) == len(set(barrier_ids))
    assert len(source_ids) == len(set(source_ids))

    for primitive_id in NEW_PRIMITIVES:
        spec = registry[primitive_id]
        assert spec.supported_claim_scope is ClaimScope.QUERY
        assert spec.speedup_class is SpeedupClass.ASYMPTOTIC
        assert spec.allowed_access_models
        assert spec.allowed_output_contracts
        assert spec.required_promises
        assert spec.common_barriers
        assert spec.source_ids
        assert all(source_id in sources for source_id in spec.source_ids)

    for barrier_id in NEW_BARRIERS:
        assert barrier_id in barriers
        assert ClaimScope.QUERY in barriers[barrier_id].blocked_scopes

    assert not (set(DEFERRED_PRIMITIVES) & set(registry))


@pytest.mark.parametrize("primitive_id", NEW_PRIMITIVES)
def test_new_primitives_have_positive_query_scope_validator_fixtures(primitive_id: str) -> None:
    decision = build_decision(_positive_state(primitive_id), load_registry())

    assert tuple(item.rule_id for item in decision.b_check_results) == RULE_IDS
    assert len(decision.b_check_results) == 10
    assert decision.authoritative_verdict is Verdict.POSITIVE
    assert decision.maximum_supported_claim_scope is ClaimScope.QUERY
    assert decision.d_route is Route.EXPERT_REVIEW


@pytest.mark.parametrize("primitive_id", NEW_PRIMITIVES)
def test_missing_required_promise_prevents_positive_for_new_primitives(primitive_id: str) -> None:
    state = _positive_state(primitive_id)
    assert state.problem_card is not None
    state.problem_card.promises = state.problem_card.promises[1:]

    decision = build_decision(state, load_registry())
    b6 = next(item for item in decision.b_check_results if item.rule_id == "B6_REQUIRED_PROMISES_REPRESENTED")

    assert b6.outcome is CheckOutcome.UNKNOWN
    assert decision.authoritative_verdict is Verdict.CONDITIONAL


@pytest.mark.parametrize(
    ("primitive_id", "access_model", "output_contract", "promises", "structures"),
    [
        ("quantum_minimum_finding", "comparison_oracle", "sorted_order", ["total_order"], ["comparison_sorting"]),
        (
            "quantum_minimum_finding",
            "random_access_array",
            "full_sequence_output",
            ["finite_candidate_set", "total_ordered_objective", "coherent_objective_oracle"],
            ["unstructured_minimum_selection"],
        ),
        (
            "quantum_minimum_finding",
            "edge_list_input",
            "path_or_tree",
            ["finite_candidate_set", "total_ordered_objective", "coherent_objective_oracle"],
            ["unstructured_minimum_selection"],
        ),
        (
            "quantum_backtracking_tree_search",
            "local_graph_transition_oracle",
            "full_solution",
            ["bounded_backtracking_tree", "bounded_tree_depth", "marked_leaf_exists"],
            ["bounded_backtracking_tree"],
        ),
        (
            "quantum_walk_marked_vertex_search",
            "local_graph_transition_oracle",
            "one_witness",
            ["marked_vertex_or_edge", "query_model_subroutine"],
            ["reversible_markov_chain_marked_vertex_search"],
        ),
        (
            "quantum_counting",
            "coherent_boolean_oracle",
            "all_marked_items",
            ["finite_search_space", "coherent_boolean_oracle_available", "count_precision_specified"],
            ["marked_set_cardinality_estimation"],
        ),
        (
            "quantum_counting",
            "coherent_boolean_oracle",
            "full_classical_output",
            ["finite_search_space", "coherent_boolean_oracle_available", "count_precision_specified"],
            ["marked_set_cardinality_estimation"],
        ),
    ],
)
def test_new_primitives_do_not_make_full_or_mismatched_outputs_positive(
    primitive_id: str,
    access_model: str,
    output_contract: str,
    promises: list[str],
    structures: list[str],
) -> None:
    state = _incompatible_selected_state(
        primitive_id,
        access_model=access_model,
        output_contract=output_contract,
        promises=promises,
        structures=structures,
    )

    decision = build_decision(state, load_registry())

    assert decision.authoritative_verdict is not Verdict.POSITIVE


@pytest.mark.parametrize(
    ("statement", "access_model", "output_contract"),
    [
        ("Given graph edges, output a minimum spanning tree.", "edge_list_input", "path_or_tree"),
        ("Given a graph, output the complete shortest path.", "local_graph_transition_oracle", "full_solution"),
        ("Given a predicate, output every marked item.", "coherent_boolean_oracle", "all_marked_items"),
        ("Given an array, output the full sorted order.", "comparison_oracle", "sorted_order"),
    ],
)
def test_full_output_no_candidate_states_remain_negative(
    statement: str,
    access_model: str,
    output_contract: str,
) -> None:
    state = RunState(
        problem_card=ProblemCard(
            statement=statement,
            input_model="explicit_problem",
            access_model=access_model,
            output_contract=output_contract,
        ),
        candidate_card=CandidateCard(no_candidate_reason="full-output task is outside the approved query-scope entries"),
    )

    decision = build_decision(state, load_registry())

    assert decision.authoritative_verdict is Verdict.NEGATIVE
    assert decision.maximum_supported_claim_scope is ClaimScope.NONE


def test_graph_walk_probe_shape_downgrades_new_walk_match_without_gap_promises(tmp_path: Path) -> None:
    provider = OverrideProvider(
        {
            ActionType.MATCH_PRIMITIVES: {
                "primitive_matches": [
                    {
                        "primitive_id": "quantum_walk_marked_vertex_search",
                        "strength": "PLAUSIBLE",
                        "prerequisites": ["attempted graph-walk match"],
                    }
                ]
            },
            ActionType.GENERATE_SCHEME: {
                "selected_candidate": "quantum_walk_marked_vertex_search",
                "scheme_steps": ["attempt quantum walk search"],
                "classical_baseline": "Theta(N)",
                "quantum_query_complexity": "QUERY: O(sqrt(N))",
                "gate_complexity": None,
                "total_complexity": None,
                "claim_scope": "QUERY",
                "limitations": ["missing spectral gap and marked fraction"],
                "expert_questions": [],
                "claim_flags": [],
                "self_assessment": "should be normalized away",
            },
        }
    )
    public = {
        "statement": "A* Algorithm graph-walk probe over local transitions; return one witness, not a full path.",
        "input_model": "explicit_graph_problem",
        "access_model": "local_graph_transition_oracle",
        "output_contract": "one_witness",
        "promises": ["marked_vertex_or_edge", "query_model_subroutine"],
        "size_parameters": ["V: vertices", "E: edges"],
        "ambiguities": ["representative AlgorithmWiki first-50 graph_walk_probe shape"],
    }

    result = Orchestrator(provider=provider).run(public, output_dir=tmp_path)

    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate is None
    assert result.state.candidate_card.primitive_matches[0].strength is MatchStrength.WEAK_ANALOGY
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE


def test_search_witness_probe_still_selects_amplitude_amplification(tmp_path: Path) -> None:
    public = {
        "statement": "AlgorithmWiki search-witness probe: return one feasible object from a coherent predicate.",
        "input_model": "explicit_combinatorial_problem",
        "access_model": "coherent_boolean_oracle",
        "output_contract": "one_witness",
        "promises": ["marked_item_exists"],
        "size_parameters": ["N: candidates"],
        "ambiguities": ["subroutine only"],
    }

    result = Orchestrator().run(public, output_dir=tmp_path)

    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "amplitude_amplification"
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_estimation_probe_still_selects_amplitude_estimation(tmp_path: Path) -> None:
    public = {
        "statement": "AlgorithmWiki estimation-sampling probe: estimate a bounded mean to additive epsilon.",
        "input_model": "explicit_numerical_problem",
        "access_model": "coherent_estimation_oracle",
        "output_contract": "additive_estimate",
        "promises": ["bounded_random_variable", "coherent_access"],
        "size_parameters": ["epsilon: additive precision"],
        "ambiguities": ["subroutine only"],
    }

    result = Orchestrator().run(public, output_dir=tmp_path)

    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "amplitude_estimation"
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_element_distinctness_still_uses_existing_quantum_walk_entry(tmp_path: Path) -> None:
    public = {
        "statement": "Given value queries, find a colliding pair or certify all values are distinct.",
        "input_model": "explicit_combinatorial_problem",
        "access_model": "value_query_oracle",
        "output_contract": "collision_or_distinctness",
        "promises": ["query_model_values"],
        "size_parameters": ["N: values"],
        "ambiguities": ["query model only"],
    }

    result = Orchestrator().run(public, output_dir=tmp_path)

    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "quantum_walk_element_distinctness"
    assert result.decision.authoritative_verdict is Verdict.POSITIVE

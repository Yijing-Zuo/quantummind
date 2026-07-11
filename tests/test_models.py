from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from quantummindlite.messages import ACTION_SEQUENCE, ACTION_SPEC_BY_TYPE, ACTION_SPECS, ActionType, Role
from quantummindlite.models import (
    AnalysisCard,
    BarrierFinding,
    BarrierSpec,
    CandidateCard,
    ClaimScope,
    FormalizationOutput,
    PrimitiveMatch,
    ProblemCard,
)


def test_card_round_trips_and_rejects_extra_fields() -> None:
    problem = ProblemCard(
        statement="Return a marked item.",
        input_model="black-box",
        access_model="coherent_boolean_oracle",
        output_contract="one_witness",
        promises=["marked_item_exists"],
        size_parameters=["N"],
        ambiguities=[],
    )
    assert ProblemCard.model_validate(problem.model_dump()).statement == problem.statement
    with pytest.raises(ValidationError):
        ProblemCard.model_validate({**problem.model_dump(), "extra": "nope"})
    assert FormalizationOutput(ambiguities=["ambiguous oracle cost"]).ambiguities == ["ambiguous oracle cost"]
    with pytest.raises(ValidationError):
        FormalizationOutput.model_validate({"access_model": "prose rewrite"})


def test_invalid_enum_and_removed_matcher_selection_fields() -> None:
    with pytest.raises(ValidationError):
        PrimitiveMatch.model_validate({"primitive_id": "x", "strength": "MAYBE"})
    with pytest.raises(ValidationError):
        PrimitiveMatch.model_validate({"primitive_id": "x", "strength": "PLAUSIBLE", "selected": True})
    with pytest.raises(ValidationError):
        BarrierFinding.model_validate({"barrier_id": "oracle_construction", "description": "x", "applicable": "UNKNOWN", "scope": "QUERY"})
    with pytest.raises(ValidationError):
        BarrierSpec.model_validate(
            {
                "barrier_id": "duplicate_scope",
                "description": "x",
                "blocked_scopes": ["QUERY", "QUERY"],
            }
        )


def test_four_primary_cards_are_sufficient() -> None:
    analysis = AnalysisCard(
        formalized_problem="p",
        canonical_structure_ids=["black_box_witness_search"],
        classical_baseline="Theta(N)",
        bottleneck="oracle queries",
        complexity_model="query",
    )
    candidate = CandidateCard(selected_candidate="amplitude_amplification", claim_scope=ClaimScope.QUERY)
    assert analysis.canonical_structure_ids == ["black_box_witness_search"]
    assert candidate.claim_scope is ClaimScope.QUERY


def test_action_roles_and_ownership_are_explicit() -> None:
    assert ACTION_SEQUENCE == (
        ActionType.FORMALIZE,
        ActionType.ANALYZE_STRUCTURE,
        ActionType.MATCH_PRIMITIVES,
        ActionType.BARRIER_PRECHECK,
        ActionType.PRIOR_ART,
        ActionType.GENERATE_SCHEME,
        ActionType.REVIEW_SCHEME,
        ActionType.NOVELTY_AUDIT,
        ActionType.CONSISTENCY_REVIEW,
    )
    assert ACTION_SPEC_BY_TYPE[ActionType.BARRIER_PRECHECK].role is Role.BARRIER_CRITIC
    assert ACTION_SPEC_BY_TYPE[ActionType.REVIEW_SCHEME].role is Role.BARRIER_CRITIC
    assert ACTION_SPEC_BY_TYPE[ActionType.PRIOR_ART].role is Role.LITERATURE_ANALYST
    assert ACTION_SPEC_BY_TYPE[ActionType.NOVELTY_AUDIT].role is Role.LITERATURE_ANALYST
    assert ACTION_SPEC_BY_TYPE[ActionType.FORMALIZE].merge_policy == "merge_formalization"


def test_each_action_has_one_strict_action_spec() -> None:
    assert len(ACTION_SPECS) == len(ActionType)
    assert set(ACTION_SPEC_BY_TYPE) == set(ActionType)
    assert len({spec.action for spec in ACTION_SPECS}) == len(ACTION_SPECS)
    for spec in ACTION_SPECS:
        assert issubclass(spec.output_model, BaseModel)
        assert spec.output_model.model_config.get("extra") == "forbid"
        assert spec.prompt_filename.endswith(".md")
        assert spec.allowed_context_keys
        assert spec.merge_policy

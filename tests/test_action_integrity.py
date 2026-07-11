from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from quantummindlite.evaluation import load_public_case
from quantummindlite.llm import MockLLMProvider, ProviderResult, ProviderTrace
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import ClaimScope, EvidenceState
from quantummindlite.workflow import Orchestrator


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


def _run(provider: MockLLMProvider, tmp_path: Path) -> Any:
    public = load_public_case("QM-PB-001")
    return Orchestrator(provider=provider).run(public.model_dump(mode="json"), output_dir=tmp_path)


@pytest.mark.parametrize("field", ["primitive_matches", "barriers", "access_model", "output_contract", "promises"])
def test_scheme_generator_cannot_write_unowned_fields(field: str, tmp_path: Path) -> None:
    payload = MockLLMProvider()._scheme("witness_search", {"output_contract": "one_witness"}, {"classical_baseline": "Theta(N)"})
    payload[field] = [] if field in {"primitive_matches", "barriers", "promises"} else "prose rewrite"
    with pytest.raises(ValidationError):
        _run(OverrideProvider({ActionType.GENERATE_SCHEME: payload}), tmp_path)


def test_unrelated_action_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _run(
            OverrideProvider(
                {
                    ActionType.MATCH_PRIMITIVES: {
                        "primitive_matches": [],
                        "barriers": [],
                    }
                }
            ),
            tmp_path,
        )


def test_post_review_empty_barriers_cannot_erase_precheck_barrier(tmp_path: Path) -> None:
    result = _run(
        OverrideProvider(
            {
                ActionType.BARRIER_PRECHECK: {
                    "barriers": [
                        {
                            "barrier_id": "oracle_construction",
                            "description": "requires represented oracle construction",
                            "applicable": "SUPPORTED",
                        }
                    ]
                },
                ActionType.REVIEW_SCHEME: {"barriers": []},
            }
        ),
        tmp_path,
    )
    assert result.state.candidate_card is not None
    ids = [item.barrier_id for item in result.state.candidate_card.barriers]
    assert "oracle_construction" in ids
    assert "query_only_scope" in ids


def test_weaker_duplicate_barrier_cannot_downgrade_supported_or_catalog_severity(tmp_path: Path) -> None:
    result = _run(
        OverrideProvider(
            {
                ActionType.BARRIER_PRECHECK: {
                    "barriers": [
                        {
                            "barrier_id": "oracle_construction",
                            "description": "strong evidence",
                            "applicable": "SUPPORTED",
                        }
                    ]
                },
                ActionType.REVIEW_SCHEME: {
                    "barriers": [
                        {
                            "barrier_id": "oracle_construction",
                            "description": "weaker duplicate",
                            "applicable": "UNKNOWN",
                        }
                    ]
                },
            }
        ),
        tmp_path,
    )
    assert result.state.candidate_card is not None
    barrier = next(item for item in result.state.candidate_card.barriers if item.barrier_id == "oracle_construction")
    assert barrier.applicable is EvidenceState.SUPPORTED
    assert barrier.blocked_scopes == [ClaimScope.GATE, ClaimScope.END_TO_END]


def test_matcher_need_not_select_for_scheme_to_choose_candidate(tmp_path: Path) -> None:
    result = _run(
        OverrideProvider(
            {
                ActionType.MATCH_PRIMITIVES: {
                    "primitive_matches": [
                        {
                            "primitive_id": "amplitude_amplification",
                            "strength": "PLAUSIBLE",
                            "prerequisites": ["marked_item_exists"],
                        }
                    ]
                },
                ActionType.GENERATE_SCHEME: {
                    "selected_candidate": "amplitude_amplification",
                    "scheme_steps": ["prepare oracle", "amplify", "measure witness"],
                    "classical_baseline": "Theta(N/M)",
                    "quantum_query_complexity": "query: O(sqrt(N/M))",
                    "claim_scope": "QUERY",
                },
            }
        ),
        tmp_path,
    )
    assert result.decision.authoritative_verdict.value == "POSITIVE"

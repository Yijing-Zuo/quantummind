from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from quantummindlite.evaluation import load_public_case
from quantummindlite.llm import MockLLMProvider, ProviderResult, ProviderTrace
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import CheckOutcome, ClaimScope, Route, Verdict
from quantummindlite.workflow import Orchestrator


class LiveLikeProvider(MockLLMProvider):
    def __init__(self) -> None:
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
        if action is ActionType.BARRIER_PRECHECK:
            payload = self._barrier_payload()
            try:
                output_model.model_validate(payload)
            except ValidationError:
                payload = {
                    "barriers": [
                        {
                            "barrier_id": item["barrier_id"],
                            "description": item["description"],
                            "applicable": item["applicable"],
                        }
                        for item in payload["barriers"]
                    ]
                }
                output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)

    def _barrier_payload(self) -> dict[str, Any]:
        return {"barriers": []}


class InventedBarrierProvider(LiveLikeProvider):
    def _barrier_payload(self) -> dict[str, Any]:
        return {
            "barriers": [
                {
                    "barrier_id": "query_model_has_oracle_overhead",
                    "description": "free-form invented caveat",
                    "applicable": "UNKNOWN",
                    "scope": "QUERY",
                    "critical": True,
                },
                {
                    "barrier_id": "not_a_catalog_barrier",
                    "description": "another invented ID",
                    "applicable": "SUPPORTED",
                    "scope": "END_TO_END",
                    "critical": False,
                },
            ]
        }


class QueryOnlyCriticalProvider(LiveLikeProvider):
    def _barrier_payload(self) -> dict[str, Any]:
        return {
            "barriers": [
                {
                    "barrier_id": "query_only_scope",
                    "description": "query-only caveat mislabelled as query blocker",
                    "applicable": "SUPPORTED",
                    "scope": "QUERY",
                    "critical": True,
                }
            ]
        }


class OrderedLowerBoundProvider(LiveLikeProvider):
    def _barrier_payload(self) -> dict[str, Any]:
        return {
            "barriers": [
                {
                    "barrier_id": "ordered_access_lower_bound",
                    "description": "constant-factor lower bound is present",
                    "applicable": "SUPPORTED",
                    "scope": "QUERY",
                    "critical": True,
                }
            ]
        }


class RevisionCrashProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.consistency_calls = 0

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        result = super().generate(role, action, prompt, inputs, output_model)
        if action is ActionType.CONSISTENCY_REVIEW and "revision_request" in output_model.model_fields:
            self.consistency_calls += 1
            payload = dict(result.payload)
            payload["revision_request"] = (
                "rewrite every part of the scheme, selected candidate, no-candidate reason, barriers, "
                "complexity fields, novelty status, and all final claims in one broad revision request; " * 4
                if self.consistency_calls > 1
                else "scheme_steps: revise the whole scheme"
            )
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return result


class RevisionErasesOrderedSearchProvider(MockLLMProvider):
    def __init__(self) -> None:
        self.scheme_calls = 0

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        result = super().generate(role, action, prompt, inputs, output_model)
        payload = dict(result.payload)
        if action is ActionType.GENERATE_SCHEME:
            self.scheme_calls += 1
            if self.scheme_calls > 1:
                payload.update(
                    {
                        "selected_candidate": None,
                        "no_candidate_reason": "Lower bound means no quantum pathway exists.",
                        "scheme_steps": [],
                        "quantum_query_complexity": None,
                        "claim_scope": "NONE",
                    }
                )
        if action is ActionType.CONSISTENCY_REVIEW and "revision_request" in output_model.model_fields:
            payload["revision_request"] = "scheme_steps: revise selected candidate"
        output_model.model_validate(payload)
        return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))


class ConsistencyProseProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        result = super().generate(role, action, prompt, inputs, output_model)
        if action is ActionType.CONSISTENCY_REVIEW:
            payload = {"consistency_review_notes": ["Change selected_candidate to no candidate."]}
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return result


def _orchestrator(provider: MockLLMProvider) -> Orchestrator:
    return Orchestrator(provider=provider)


def test_invented_barrier_ids_fail_closed(tmp_path: Path) -> None:
    with pytest.raises((ValueError, ValidationError), match="unknown barrier"):
        Orchestrator(provider=InventedBarrierProvider()).run(load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path)


def test_query_only_scope_does_not_block_query_claim(tmp_path: Path) -> None:
    result = Orchestrator(provider=QueryOnlyCriticalProvider()).run(
        load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path
    )
    b7 = next(item for item in result.decision.b_check_results if item.rule_id == "B7_APPLICABLE_CRITICAL_BARRIER")
    assert b7.outcome is CheckOutcome.PASS
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_ordered_lower_bound_does_not_veto_pathway_before_b3(tmp_path: Path) -> None:
    result = Orchestrator(provider=OrderedLowerBoundProvider()).run(
        load_public_case("QM-PB-007").model_dump(mode="json"),
        output_dir=tmp_path,
    )
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "ordered_search"
    outcomes = {item.rule_id: item.outcome for item in result.decision.b_check_results}
    assert outcomes["B7_APPLICABLE_CRITICAL_BARRIER"] is CheckOutcome.PASS
    assert outcomes["B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE"] is CheckOutcome.FAIL
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE


def test_second_consistency_review_cannot_crash_run(tmp_path: Path) -> None:
    result = _orchestrator(RevisionCrashProvider()).run(load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path)
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_revision_cannot_replace_ordered_search_with_no_candidate(tmp_path: Path) -> None:
    provider = RevisionErasesOrderedSearchProvider()
    result = _orchestrator(provider).run(load_public_case("QM-PB-007").model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "ordered_search"
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE


def test_omitted_common_barriers_are_inserted_as_unknown(tmp_path: Path) -> None:
    result = Orchestrator().run(load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    barriers = {item.barrier_id: item for item in result.state.candidate_card.barriers}
    assert barriers["oracle_construction"].applicable.value == "UNKNOWN"
    assert barriers["query_only_scope"].applicable.value == "UNKNOWN"


@pytest.mark.parametrize(
    ("case_id", "primitive_id"),
    [
        ("QM-PB-007", "ordered_search"),
        ("QM-PB-008", "oracle_interrogation"),
        ("QM-PB-009", "parity_query"),
    ],
)
def test_constant_factor_pathways_remain_selected_and_fail_through_b3(case_id: str, primitive_id: str, tmp_path: Path) -> None:
    result = Orchestrator().run(load_public_case(case_id).model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == primitive_id
    outcomes = {item.rule_id: item.outcome for item in result.decision.b_check_results}
    assert outcomes["B3_ASYMPTOTIC_SPEEDUP_CERTIFICATE"] is CheckOutcome.FAIL
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE
    assert result.decision.maximum_supported_claim_scope is ClaimScope.NONE
    assert result.decision.d_route is Route.STOP


def test_no_automatic_revision_code_or_cli_option_remains() -> None:
    assert "max_revision_rounds" not in inspect.signature(Orchestrator).parameters
    help_result = subprocess.run(
        [sys.executable, "-m", "quantummindlite.cli", "analyze", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "max-revision" not in help_result.stdout


def test_consistency_reviewer_prose_cannot_mutate_scheme(tmp_path: Path) -> None:
    result = Orchestrator(provider=ConsistencyProseProvider()).run(
        load_public_case("QM-PB-007").model_dump(mode="json"),
        output_dir=tmp_path,
    )
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "ordered_search"


@pytest.mark.parametrize(
    ("case_id", "primitive_id", "verdict", "scope", "route"),
    [
        ("QM-PB-001", "amplitude_amplification", Verdict.POSITIVE, ClaimScope.QUERY, Route.EXPERT_REVIEW),
        ("QM-PB-006", None, Verdict.NEGATIVE, ClaimScope.NONE, Route.STOP),
        ("QM-PB-007", "ordered_search", Verdict.NEGATIVE, ClaimScope.NONE, Route.STOP),
        ("QM-PB-009", "parity_query", Verdict.NEGATIVE, ClaimScope.NONE, Route.STOP),
        ("QM-PB-010", None, Verdict.NEGATIVE, ClaimScope.NONE, Route.STOP),
    ],
)
def test_required_mock_case_outcomes(
    case_id: str,
    primitive_id: str | None,
    verdict: Verdict,
    scope: ClaimScope,
    route: Route,
    tmp_path: Path,
) -> None:
    result = Orchestrator().run(load_public_case(case_id).model_dump(mode="json"), output_dir=tmp_path)
    candidate = result.state.candidate_card
    assert candidate is not None
    assert candidate.selected_candidate == primitive_id
    assert result.decision.authoritative_verdict is verdict
    assert result.decision.maximum_supported_claim_scope is scope
    assert result.decision.d_route is route


class R3NoisyBarrierProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action in {ActionType.BARRIER_PRECHECK, ActionType.REVIEW_SCHEME}:
            payload = {
                "barriers": [
                    {
                        "barrier_id": "oracle_construction",
                        "description": "relevant query-boundary caveat",
                        "applicable": "SUPPORTED",
                    },
                    {
                        "barrier_id": "query_only_scope",
                        "description": "relevant query-only caveat",
                        "applicable": "SUPPORTED",
                    },
                    {
                        "barrier_id": "state_preparation",
                        "description": "irrelevant R3-style unknown blocker",
                        "applicable": "UNKNOWN",
                    },
                    {
                        "barrier_id": "coherent_access",
                        "description": "another irrelevant R3-style blocker",
                        "applicable": "UNKNOWN",
                    },
                ]
            }
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


class R3AlternativePlausibleProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        if action is ActionType.MATCH_PRIMITIVES:
            payload = {
                "primitive_matches": [
                    {
                        "primitive_id": "quantum_linear_systems_state_output",
                        "strength": "PLAUSIBLE",
                        "prerequisites": ["sparse_matrix", "bounded_condition_number", "prepared_rhs"],
                    },
                    {
                        "primitive_id": "amplitude_estimation",
                        "strength": "PLAUSIBLE",
                        "prerequisites": ["coherent solution-state preparation"],
                    },
                ]
            }
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        if action in {ActionType.BARRIER_PRECHECK, ActionType.REVIEW_SCHEME}:
            payload = {
                "barriers": [
                    {"barrier_id": "coherent_access", "description": "alternative-only uncertainty", "applicable": "UNKNOWN"},
                    {"barrier_id": "precision_dependence", "description": "alternative-only caveat", "applicable": "SUPPORTED"},
                    {"barrier_id": "state_preparation", "description": "public promise satisfies it", "applicable": "UNKNOWN"},
                    {"barrier_id": "condition_number", "description": "public promise satisfies it", "applicable": "UNKNOWN"},
                    {"barrier_id": "readout", "description": "output contract satisfies it", "applicable": "UNKNOWN"},
                ]
            }
            output_model.model_validate(payload)
            return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))
        return super().generate(role, action, prompt, inputs, output_model)


class R3DiagnosticSelectionProvider(MockLLMProvider):
    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        problem = inputs.get("problem_card", {})
        comparison = problem.get("access_model") == "comparison_oracle"
        primitive = "comparison_sorting_no_asymptotic_speedup" if comparison else "dense_linear_system_full_output_stress"
        barrier = "comparison_lower_bound" if comparison else "loading_condition_readout"
        payload: dict[str, Any]
        if action is ActionType.MATCH_PRIMITIVES:
            payload = {"primitive_matches": [{"primitive_id": primitive, "strength": "PLAUSIBLE", "prerequisites": ["diagnostic match"]}]}
        elif action in {ActionType.BARRIER_PRECHECK, ActionType.REVIEW_SCHEME}:
            payload = {"barriers": [{"barrier_id": barrier, "description": "registered diagnostic", "applicable": "SUPPORTED"}]}
        elif action is ActionType.PRIOR_ART:
            payload = {"prior_art_status": "KNOWN_CASE_RECOVERY"}
        elif action is ActionType.GENERATE_SCHEME:
            payload = {
                "selected_candidate": primitive,
                "no_candidate_reason": None,
                "scheme_steps": ["incorrectly select a diagnostic entry"],
                "classical_baseline": "represented classical lower bound",
                "quantum_query_complexity": "no asymptotic improvement",
                "gate_complexity": None,
                "total_complexity": None,
                "claim_scope": "QUERY",
                "limitations": [],
                "expert_questions": [],
                "claim_flags": [],
                "self_assessment": "diagnostic entry incorrectly treated as a pathway",
            }
        else:
            return super().generate(role, action, prompt, inputs, output_model)
        output_model.model_validate(payload)
        return ProviderResult(payload, ProviderTrace(provider=self.provider_name, model=self.model_name))


def test_irrelevant_catalog_barriers_are_filtered_before_b7(tmp_path: Path) -> None:
    result = Orchestrator(provider=R3NoisyBarrierProvider()).run(load_public_case("QM-PB-001").model_dump(mode="json"), output_dir=tmp_path)
    assert result.state.candidate_card is not None
    assert {item.barrier_id for item in result.state.candidate_card.barriers} == {"oracle_construction", "query_only_scope"}
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


def test_unselected_alternative_barriers_do_not_block_selected_pathway(tmp_path: Path) -> None:
    result = Orchestrator(provider=R3AlternativePlausibleProvider()).run(
        load_public_case("QM-PB-004").model_dump(mode="json"), output_dir=tmp_path
    )
    assert result.state.candidate_card is not None
    assert result.state.candidate_card.selected_candidate == "quantum_linear_systems_state_output"
    barriers = {item.barrier_id: item.applicable.value for item in result.state.candidate_card.barriers}
    assert barriers == {"state_preparation": "NOT_APPLICABLE", "condition_number": "NOT_APPLICABLE", "readout": "NOT_APPLICABLE"}
    assert result.decision.authoritative_verdict is Verdict.POSITIVE


@pytest.mark.parametrize("case_id", ["QM-PB-006", "QM-PB-010"])
def test_diagnostic_registry_entries_cannot_be_selected(case_id: str, tmp_path: Path) -> None:
    result = Orchestrator(provider=R3DiagnosticSelectionProvider()).run(
        load_public_case(case_id).model_dump(mode="json"), output_dir=tmp_path
    )
    assert result.state.candidate_card is not None
    candidate = result.state.candidate_card
    assert candidate.selected_candidate is None
    assert candidate.no_candidate_reason
    assert all(match.strength.value != "PLAUSIBLE" for match in candidate.primitive_matches)
    assert candidate.prior_art_status.value == "UNKNOWN"
    assert result.decision.authoritative_verdict is Verdict.NEGATIVE
    assert result.decision.maximum_supported_claim_scope is ClaimScope.NONE

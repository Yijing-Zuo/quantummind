from __future__ import annotations

import itertools
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import scripts.score_open_discovery as scorer
from quantummindlite.ods import (
    DISPOSITION_PRIORS,
    ODSJudgeAssessment,
    calculate_ods_score,
    robust_dimension_estimate,
    stable_softplus,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def assessment(t: int, e: int, r: int) -> ODSJudgeAssessment:
    return ODSJudgeAssessment(
        technical_validity=t,
        epistemic_auditability=e,
        research_utility=r,
        technical_rationale="concise technical verdict",
        auditability_rationale="concise auditability verdict",
        utility_rationale="concise utility verdict",
    )


def score(scores: tuple[int, int, int], disposition: str, accepted: bool, graph_status: str) -> dict[str, float]:
    reviews = [assessment(*scores) for _ in range(3)]
    return calculate_ods_score(reviews, disposition, accepted, graph_status)


def test_judge_assessment_is_strict_bounded_and_concise() -> None:
    with pytest.raises(ValidationError):
        assessment(5, 2, 2)
    with pytest.raises(ValidationError):
        ODSJudgeAssessment.model_validate(
            {
                "technical_validity": 2,
                "epistemic_auditability": 2,
                "research_utility": 2,
                "technical_rationale": "x" * 1001,
                "auditability_rationale": "ok",
                "utility_rationale": "ok",
                "hidden_reasoning": "must be rejected",
            }
        )


def test_robust_dimension_clips_raw_extremes() -> None:
    assert robust_dimension_estimate([0, 0, 0]) == pytest.approx((0.02, 0.0))
    assert robust_dimension_estimate([4, 4, 4]) == pytest.approx((0.98, 0.0))


def test_robust_dimension_uses_median_mad_and_locked_penalty() -> None:
    adjusted, sigma = robust_dimension_estimate([0, 2, 4])
    assert sigma == pytest.approx(1.4826 * 0.48)
    assert adjusted == pytest.approx(0.5 - 0.5 * sigma)


def test_two_agreeing_reviewers_resist_one_extreme_outlier() -> None:
    assert robust_dimension_estimate([2, 2, 4]) == pytest.approx((0.5, 0.0))


def test_broad_disagreement_reduces_adjusted_quality() -> None:
    adjusted, _ = robust_dimension_estimate([0, 2, 4])
    assert adjusted < robust_dimension_estimate([2, 2, 2])[0]


def test_api_quality_uses_locked_weighted_geometric_mean() -> None:
    result = calculate_ods_score([assessment(1, 2, 3)] * 3, "REFORMULATE", True, "PASS")
    assert result["api_quality"] == pytest.approx(0.25**0.4 * 0.5**0.4 * 0.75**0.2)


def test_disposition_prior_table_is_exactly_frozen() -> None:
    assert DISPOSITION_PRIORS == {
        "INVALID_STATE": 0.04,
        "SOURCE_REPAIR_REQUIRED": 0.10,
        "REJECT_TASK_MISMATCH": 0.12,
        "DEMOTE_GENERIC": 0.36,
        "DEMOTE_TO_BENCHMARK": 0.45,
        "REFORMULATE": 0.70,
        "LITERATURE_SEARCH_FIRST": 0.84,
        "KEEP_FOR_EXPERT_REVIEW": 0.95,
    }


def test_deterministic_prior_uses_claim_and_graph_log_odds_adjustments() -> None:
    reviews = [assessment(2, 2, 2)] * 3
    base = calculate_ods_score(reviews, "REFORMULATE", False, "PASS")["deterministic_prior"]
    accepted = calculate_ods_score(reviews, "REFORMULATE", True, "PASS")["deterministic_prior"]
    assert accepted / (1 - accepted) == pytest.approx(math.exp(0.5) * base / (1 - base))
    assert calculate_ods_score(reviews, "REFORMULATE", True, "WARN")["deterministic_prior"] == pytest.approx(
        calculate_ods_score(reviews, "REFORMULATE", True, "FAIL")["deterministic_prior"]
    )


def test_fusion_uses_locked_log_odds_weights() -> None:
    result = calculate_ods_score([assessment(3, 3, 3)] * 3, "REFORMULATE", True, "PASS")
    api_quality, prior = result["api_quality"], result["deterministic_prior"]
    expected = 1 / (1 + math.exp(-(0.7 * math.log(api_quality / (1 - api_quality)) + 0.3 * math.log(prior / (1 - prior)))))
    assert result["fused_quality"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("disposition", "accepted", "graph_status", "expected"),
    [
        ("INVALID_STATE", False, "FAIL", 0.25),
        ("DEMOTE_GENERIC", True, "PASS", 0.58),
        ("DEMOTE_TO_BENCHMARK", True, "PASS", 0.65),
        ("REFORMULATE", False, "PASS", 0.68),
        ("REFORMULATE", True, "PASS", 1.0),
        ("DEMOTE_GENERIC", False, "FAIL", 0.25),
    ],
)
def test_semantic_caps_use_only_the_locked_minimum(disposition: str, accepted: bool, graph_status: str, expected: float) -> None:
    result = calculate_ods_score([assessment(2, 2, 2)] * 3, disposition, accepted, graph_status)
    assert result["semantic_cap"] == expected
    assert result["ods_score"] <= 100 * result["fused_quality"]


def test_stable_softplus_is_finite_at_large_magnitudes() -> None:
    assert stable_softplus(1_000.0) == pytest.approx(1_000.0)
    assert math.isfinite(stable_softplus(-1_000.0))


def test_calculation_is_reviewer_order_invariant_and_bounded() -> None:
    reviews = [assessment(0, 2, 4), assessment(2, 4, 1), assessment(4, 3, 3)]
    values = {calculate_ods_score(list(order), "REFORMULATE", True, "PASS")["ods_score"] for order in itertools.permutations(reviews)}
    assert len(values) == 1
    assert 0.0 <= values.pop() <= 100.0


@pytest.mark.parametrize(
    ("scores", "disposition", "accepted", "graph_status", "expected"),
    [
        ((1, 1, 1), "INVALID_STATE", False, "FAIL", 10.2),
        ((2, 2, 1), "DEMOTE_GENERIC", True, "PASS", 44.9),
        ((3, 4, 2), "REFORMULATE", False, "PASS", 67.9),
        ((3, 4, 3), "REFORMULATE", True, "PASS", 82.3),
        ((4, 4, 4), "KEEP_FOR_EXPERT_REVIEW", True, "PASS", 96.9),
    ],
)
def test_locked_numerical_regression_anchors(
    scores: tuple[int, int, int], disposition: str, accepted: bool, graph_status: str, expected: float
) -> None:
    assert score(scores, disposition, accepted, graph_status)["ods_score"] == pytest.approx(expected, abs=0.05)


def test_internal_score_retains_more_precision_than_csv_display() -> None:
    result = score((3, 4, 3), "REFORMULATE", True, "PASS")
    assert result["ods_score"] != round(result["ods_score"], 1)


def test_rationales_and_critical_issue_are_diagnostic_only() -> None:
    first = assessment(3, 2, 4)
    second = first.model_copy(
        update={
            "technical_rationale": "different technical diagnostic",
            "auditability_rationale": "different audit diagnostic",
            "utility_rationale": "different utility diagnostic",
            "critical_issue": "different critical issue",
        }
    )
    assert calculate_ods_score([first] * 3, "REFORMULATE", True, "PASS") == calculate_ods_score([second] * 3, "REFORMULATE", True, "PASS")


def test_judge_prompt_contains_locked_blindness_rubric_and_anchors() -> None:
    prompt = (PROJECT_ROOT / "src/quantummindlite/resources/prompts/open_discovery_judge.md").read_text(encoding="utf-8").lower()
    phrases = (
        "anonymized",
        "never infer",
        "do not reward verbosity",
        "oracle",
        "best known",
        "query-level subroutine",
        "well-supported negative",
        "technical validity",
        "epistemic auditability",
        "research utility",
        "0: unusable",
        "4: exceptional",
        "concise rationales",
    )
    assert all(phrase in prompt for phrase in phrases)


def test_substantive_packet_change_changes_cache_key() -> None:
    first = {"task": {"statement": "first task"}, "proposal": {"scheme_steps": ["first scheme"]}}
    second = {"task": {"statement": "different task"}, "proposal": {"scheme_steps": ["different scheme"]}}
    configuration = {
        "prompt_sha256": "a" * 64,
        "reviewer_profile": {"name": "TECHNICAL_SKEPTIC", "focus": "technical focus"},
        "provider": "openai",
        "requested_model": "judge-test-model",
        "reasoning_effort": "high",
    }
    assert scorer.judge_cache_key(first, **configuration) != scorer.judge_cache_key(second, **configuration)


def test_cache_identity_changes_only_for_locked_semantic_configuration() -> None:
    packet = {"task": {"statement": "public task"}}
    base: dict[str, Any] = {
        "prompt_sha256": "a" * 64,
        "reviewer_profile": {"name": "TECHNICAL_SKEPTIC", "focus": "technical focus"},
        "provider": "openai",
        "requested_model": "judge-test-model",
        "reasoning_effort": "high",
    }
    key = scorer.judge_cache_key(packet, **base)
    for field, value in (
        ("prompt_sha256", "b" * 64),
        ("reviewer_profile", {"name": "FEASIBILITY_SKEPTIC", "focus": "feasibility focus"}),
        ("provider", "other-provider"),
        ("requested_model", "different-model"),
        ("reasoning_effort", "low"),
    ):
        assert scorer.judge_cache_key(packet, **{**base, field: value}) != key
    assert scorer.judge_cache_key(packet, **{**base, "reviewer_profile": {"name": "TECHNICAL_SKEPTIC", "focus": "revised focus"}}) != key
    assert "created_at" not in scorer.judge_cache_identity(packet, **base)


def scored_row(system: str, task: str, value: float, *, status: str = "OK") -> dict[str, Any]:
    return {
        "system_id": system,
        "task_id": task,
        "score_status": status,
        "_ods_score": value,
        "_technical_validity": value / 25,
        "_epistemic_auditability": value / 25,
        "_research_utility": value / 25,
        "research_disposition": "REFORMULATE",
        "graph_status": "PASS",
        "claim_accepted": True,
    }


def test_aggregation_includes_failures_unrounded_scores_thresholds_and_pairing() -> None:
    rows = [
        scored_row("ref", "t1", 69.96),
        scored_row("ref", "t2", 0.0, status="STATE_MISSING"),
        scored_row("cmp", "t1", 60.0),
        scored_row("cmp", "t2", 0.0, status="STATE_MISSING"),
    ]
    aggregate = scorer.aggregate_systems(rows)
    assert aggregate["ref"]["mean_ods"] == pytest.approx(34.98)
    assert aggregate["ref"]["median_ods"] == pytest.approx(34.98)
    assert aggregate["ref"]["population_standard_deviation"] == pytest.approx(34.98)
    assert aggregate["ref"]["strong_lead_count"] == 0 and aggregate["ref"]["operational_failure_count"] == 1
    assert scorer.compare_to_reference(rows, "ref")["cmp"] == {
        "paired_task_count": 2,
        "reference_mean_ods": pytest.approx(34.98),
        "comparator_mean_ods": pytest.approx(30.0),
        "delta_mean_ods": pytest.approx(4.98),
        "reference_wins": 1,
        "comparator_wins": 0,
        "exact_ties": 1,
    }
    thresholds = scorer.aggregate_systems([scored_row("one", "at-70", 70.0), scored_row("one", "at-85", 85.0)])["one"]
    assert thresholds["strong_lead_count"] == 2 and thresholds["strong_lead_rate"] == 1.0
    assert thresholds["high_priority_count"] == 1 and thresholds["high_priority_rate"] == 0.5


def test_cli_help_succeeds() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/score_open_discovery.py", "--help"], cwd=PROJECT_ROOT, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0
    assert all(
        option in result.stdout
        for option in ("--manifest", "--summary", "--offline", "--validate-only", "--reference-system", "--output-dir")
    )

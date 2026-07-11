from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scripts.datasets.candidate_value_labeling import (
    GENERIC_GROVERIZATION,
    HIGH_PRIORITY_EXPERT_REVIEW,
    LOW_VALUE_FULL_OUTPUT,
    REGISTRY_GAP_INTERESTING,
    REJECT_OR_NO_SIGNAL,
    REVIEW_MANUALLY,
    USEFUL_SUBROUTINE_CANDIDATE,
    label_candidate_value,
)
from scripts.datasets.summarize_qml_discovery_runs import SUMMARY_FIELDS
from scripts.datasets.summarize_qml_discovery_runs import main as summarize_main


def base_record(**updates: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "algorithm_id": "AW-TEST",
        "probe_id": "AW-TEST-P0001",
        "algorithm_name": "Lawrence Gibbs Sampling",
        "parent_algorithm_name": "Lawrence Gibbs Sampling",
        "probe_type": "estimation_sampling_probe",
        "selected_candidate": "amplitude_estimation",
        "verdict": "POSITIVE",
        "scope": "QUERY",
        "route": "EXPERT_REVIEW",
        "input_model": "explicit_numerical_problem",
        "access_model": "coherent_estimation_oracle",
        "output_contract": "additive_estimate",
        "original_output_contract": "approximation_solution",
        "probe_output_contract": "additive_estimate",
        "statement": (
            "Lawrence Gibbs Sampling estimation-sampling probe. This is a subroutine/query-model probe, "
            "not an end-to-end claim. The source-specific bottleneck is precision, convergence, sample "
            "complexity, and estimator variance under coherent oracle access."
        ),
        "promises": ["bounded_random_variable", "coherent_access", "oracle_model_assumption"],
        "introduced_assumptions": "coherent_estimation_oracle; bounded_random_variable; coherent_sampler",
        "weak_analogy_opportunities": [],
        "limitations": [
            "Any positive result is query-level only, not an end-to-end speedup claim.",
            "Coherent oracle construction and variance bounds remain assumptions.",
        ],
        "expert_questions": [
            "What oracle prepares the Gibbs sampler coherently with bounded variance and precision cost?",
        ],
        "claim_flags": ["QUERY_ONLY_SCOPE_NOT_END_TO_END"],
        "barriers": [],
        "b_failures": [],
        "b_unknowns": [],
    }
    record.update(updates)
    return record


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def test_useful_amplitude_estimation_is_prioritized_for_expert_review() -> None:
    result = label_candidate_value(base_record())

    assert result.label in {HIGH_PRIORITY_EXPERT_REVIEW, USEFUL_SUBROUTINE_CANDIDATE}
    assert result.score >= 4


def test_generic_groverization_fixture() -> None:
    result = label_candidate_value(
        base_record(
            algorithm_name="Brute force",
            parent_algorithm_name="Brute force",
            probe_type="search_witness_probe",
            selected_candidate="amplitude_amplification",
            access_model="coherent_boolean_oracle",
            output_contract="one_witness",
            original_output_contract="full_solution",
            probe_output_contract="one_witness",
            statement="Brute force search-witness probe over a broad predicate over candidates to find a witness.",
            promises=["marked_item_exists"],
        )
    )

    assert result.label == GENERIC_GROVERIZATION
    assert result.score == 2


def test_registry_gap_graph_walk_fixture() -> None:
    result = label_candidate_value(
        base_record(
            algorithm_name="Specific Graph Algorithm",
            parent_algorithm_name="Specific Graph Algorithm",
            selected_candidate="",
            verdict="NEGATIVE",
            scope="NONE",
            route="STOP",
            probe_type="graph_walk_probe",
            output_contract="one_witness",
            original_output_contract="one_witness",
            statement="Graph walk probe over locally defined transitions and marked vertices.",
            weak_analogy_opportunities=[
                {
                    "primitive_id": "quantum_walk_marked_vertex_search",
                    "missing_access_or_output_or_promises": [],
                    "possible_reformulation_question": (
                        "Can this graph walk expose a reversible Markov chain with spectral gap and marked fraction bounds?"
                    ),
                }
            ],
            expert_questions=[
                "Can this graph walk expose a reversible Markov chain with spectral gap and marked fraction bounds?",
            ],
        )
    )

    assert result.label == REGISTRY_GAP_INTERESTING
    assert result.score == 4


def test_full_output_low_value_fixture() -> None:
    result = label_candidate_value(
        base_record(
            selected_candidate="",
            verdict="NEGATIVE",
            scope="NONE",
            route="STOP",
            output_contract="full_solution",
            original_output_contract="full_solution",
            probe_output_contract="",
            statement="Return the full classical solution sequence; no smaller subroutine payoff is identified.",
            weak_analogy_opportunities=[],
        )
    )

    assert result.label == LOW_VALUE_FULL_OUTPUT
    assert result.score == 1


def test_selected_candidate_without_expert_questions_needs_manual_review() -> None:
    result = label_candidate_value(
        base_record(
            selected_candidate="quantum_minimum_finding",
            algorithm_name="Specialized Selection Routine",
            statement="Query-level subroutine with coherent objective oracle assumptions.",
            expert_questions=[],
            promises=["finite_candidate_set", "total_ordered_objective", "coherent_objective_oracle"],
        )
    )

    assert result.label == REVIEW_MANUALLY
    assert result.score <= 2


def test_no_candidate_and_no_weak_signal_rejects() -> None:
    result = label_candidate_value(
        base_record(
            selected_candidate="",
            verdict="NEGATIVE",
            scope="NONE",
            route="STOP",
            statement="No registry primitive or weak analogy is identified.",
            weak_analogy_opportunities=[],
            expert_questions=["Is there anything useful here?"],
        )
    )

    assert result.label == REJECT_OR_NO_SIGNAL
    assert result.score == 0


def test_summarizer_output_includes_candidate_value_columns(tmp_path: Path) -> None:
    public_card = {
        "statement": "Useful estimation probe, not an end-to-end claim.",
        "input_model": "explicit_numerical_problem",
        "access_model": "coherent_estimation_oracle",
        "output_contract": "additive_estimate",
        "promises": ["bounded_random_variable", "coherent_access", "oracle_model_assumption"],
        "size_parameters": ["N: samples"],
        "ambiguities": ["subroutine only"],
    }
    public_path = tmp_path / "public_probe" / "AW-TEST-P0001.yaml"
    public_path.parent.mkdir(parents=True)
    public_path.write_text(
        "\n".join(
            [
                f"statement: {public_card['statement']!r}",
                f"input_model: {public_card['input_model']}",
                f"access_model: {public_card['access_model']}",
                f"output_contract: {public_card['output_contract']}",
                "promises:",
                "- bounded_random_variable",
                "- coherent_access",
                "- oracle_model_assumption",
                "size_parameters:",
                "- 'N: samples'",
                "ambiguities:",
                "- subroutine only",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "\n".join(
            [
                (
                    "probe_id,parent_algorithm_id,parent_algorithm_name,public_probe_path,probe_type,"
                    "introduced_assumptions,original_output_contract,probe_output_contract"
                ),
                (
                    "AW-TEST-P0001,AW-TEST,Lawrence Gibbs Sampling,"
                    f"{public_path},estimation_sampling_probe,"
                    "coherent_estimation_oracle; bounded_random_variable,approximation_solution,additive_estimate"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "qml-test"
    write_json(run_dir / "input.json", public_card)
    write_json(
        run_dir / "state.json",
        {
            "candidate_card": {
                "selected_candidate": "amplitude_estimation",
                "weak_analogy_opportunities": [],
                "limitations": ["query-level only; not an end-to-end claim; coherent oracle construction remains assumed"],
                "expert_questions": ["What coherent oracle bounds estimator variance and precision cost?"],
                "claim_flags": ["QUERY_ONLY_SCOPE_NOT_END_TO_END"],
                "barriers": [],
            }
        },
    )
    write_json(
        run_dir / "decision.json",
        {
            "authoritative_verdict": "POSITIVE",
            "maximum_supported_claim_scope": "QUERY",
            "d_route": "EXPERT_REVIEW",
            "b_check_results": [{"rule_id": "B1_SELECTED_MATCH_CONSISTENCY", "outcome": "PASS"}],
        },
    )
    out_csv = tmp_path / "summary.csv"
    out_md = tmp_path / "summary.md"

    assert (
        summarize_main(
            [
                "--kind",
                "probe",
                "--run-dir",
                str(tmp_path / "runs"),
                "--manifest",
                str(manifest),
                "--out-csv",
                str(out_csv),
                "--out-md",
                str(out_md),
            ]
        )
        == 0
    )

    with out_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for column in ("candidate_value_label", "candidate_value_score", "candidate_value_reason", "candidate_value_features"):
        assert column in SUMMARY_FIELDS
        assert column in rows[0]
        assert rows[0][column]
    assert "candidate_value_label" in out_md.read_text(encoding="utf-8")

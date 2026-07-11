from __future__ import annotations

from copy import deepcopy
from typing import Any

from quantummindlite._graph_screen import (
    AccessUpgradeStatus,
    BaselineStatus,
    OracleStatus,
    OutputAlignment,
    OutputType,
    ResearchDisposition,
    ScreeningReport,
)
from scripts.regraph_runs import _assign_families, _family_key, _screen_fields, _top_rows


def _row(**updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "shard": "batch001",
        "run": "run-a",
        "run_dir": "runs/batch001/run-a",
        "parent_algorithm_name": "HNSW: Walk",
        "selected": "quantum_walk_marked_vertex_search",
        "original_output_type": "FULL_RESULT",
        "access_provided": "explicit_graph",
        "candidate_universe": "graph|local neighbor transitions",
        "graph_status": "PASS",
        "claim_accepted": True,
        "research_disposition": ResearchDisposition.KEEP_FOR_EXPERT_REVIEW.value,
        "hard_blockers": "",
        "unknown_obligations": "",
        "nontrivial_structure_count": 2,
        "expert_questions_count": 1,
    }
    row.update(updates)
    return row


def test_family_key_and_id_are_stable_under_parent_formatting() -> None:
    first = _row()
    reformatted = _row(parent_algorithm_name="hnsw walk", run="run-b")

    assert _family_key(first) == _family_key(reformatted)
    first_id = _assign_families([first])[0]["candidate_family_id"]
    second_id = _assign_families([reformatted])[0]["candidate_family_id"]

    assert first_id == second_id == "qfam-19e9883bdbb4"


def test_input_order_does_not_change_canonical_run() -> None:
    preferred = _row(run="run-a")
    unresolved = _row(
        run="run-b",
        research_disposition=ResearchDisposition.REFORMULATE.value,
        unknown_obligations="S2_ACCESS_UPGRADE",
    )

    forward = deepcopy([preferred, unresolved])
    reverse = deepcopy([unresolved, preferred])
    _assign_families(forward)
    _assign_families(reverse)

    assert {row["canonical_run"] for row in forward} == {"run-a"}
    assert {row["canonical_run"] for row in reverse} == {"run-a"}
    assert next(row for row in forward if row["is_canonical_run"])["run"] == "run-a"
    assert next(row for row in reverse if row["is_canonical_run"])["run"] == "run-a"


def test_only_canonical_duplicate_can_enter_top_rows() -> None:
    rows = [_row(run="run-b"), _row(run="run-a")]
    _assign_families(rows)

    top = _top_rows(rows, top_k=9)

    assert [row["run"] for row in top] == ["run-a"]
    assert sum(bool(row["is_canonical_run"]) for row in rows) == 1


def test_missing_parent_names_do_not_merge_unrelated_runs() -> None:
    rows = [
        _row(parent_algorithm_name="", run="run-a", run_dir="runs/batch001/run-a"),
        _row(parent_algorithm_name="", run="run-b", run_dir="runs/batch001/run-b"),
    ]

    families = _assign_families(rows)

    assert len(families) == 2
    assert len({row["candidate_family_id"] for row in rows}) == 2
    assert all(row["is_canonical_run"] for row in rows)


def test_top_rows_exclude_generic_and_invalid_dispositions() -> None:
    rows = [
        _row(run="keep", parent_algorithm_name="kept family"),
        _row(
            run="generic",
            parent_algorithm_name="generic family",
            research_disposition=ResearchDisposition.DEMOTE_GENERIC.value,
        ),
        _row(
            run="invalid",
            parent_algorithm_name="invalid family",
            research_disposition=ResearchDisposition.INVALID_STATE.value,
        ),
    ]
    _assign_families(rows)

    assert [row["run"] for row in _top_rows(rows, top_k=9)] == ["keep"]


def test_screen_fields_flatten_lists_for_csv() -> None:
    report = ScreeningReport(
        graph_id="qgraph-test",
        run_id="run-a",
        research_disposition=ResearchDisposition.REFORMULATE,
        screening_reasons=["S7_UNRESOLVED_REFORMULATION", "S2_ACCESS_UNVERIFIED"],
        hard_blockers=["S0_B_CLAIM_NOT_ACCEPTED"],
        unknown_obligations=["S2_ACCESS_UPGRADE", "S3_ORACLE_CONSTRUCTION"],
        original_output_type=OutputType.FULL_RESULT,
        candidate_output_type=OutputType.WITNESS,
        output_alignment=OutputAlignment.DIAGNOSTIC_ONLY,
        access_provided="explicit_graph",
        access_required=["coherent_walk_access", "coherent_marking_oracle"],
        access_upgrade_status=AccessUpgradeStatus.UNVERIFIED,
        oracle_status=OracleStatus.BLACK_BOX_ASSUMPTION,
        baseline_status=BaselineStatus.BASELINE_UNVERIFIED,
        candidate_universe="local-neighbor graph",
    )

    fields = _screen_fields(report)

    assert fields["screening_reasons"] == "S7_UNRESOLVED_REFORMULATION;S2_ACCESS_UNVERIFIED"
    assert fields["hard_blockers"] == "S0_B_CLAIM_NOT_ACCEPTED"
    assert fields["unknown_obligations"] == "S2_ACCESS_UPGRADE;S3_ORACLE_CONSTRUCTION"
    assert fields["access_required"] == "coherent_walk_access;coherent_marking_oracle"
    assert "graph_id" not in fields
    assert "run_id" not in fields

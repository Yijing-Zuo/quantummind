from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from quantummindlite.evaluation import (
    load_evidence_case,
    load_gold_case,
    load_manifest,
    load_public_case,
    score_case,
    validate_paperbench,
)
from quantummindlite.workflow import Orchestrator


def test_paperbench_manifest_and_source_audit() -> None:
    result = validate_paperbench()
    assert result["ok"] or all(error.startswith("freeze ") for error in result["errors"]), result["errors"]
    manifest = load_manifest()
    assert len(manifest["ready_cases"]) == 10
    for case_id in manifest["ready_cases"]:
        evidence = load_evidence_case(case_id)
        assert evidence.official_url.startswith("https://")
        assert evidence.source_status == "PRIMARY_SOURCE_CHECKED"


def test_public_gold_evidence_separation() -> None:
    for case_id in load_manifest()["ready_cases"]:
        public = load_public_case(case_id)
        gold = load_gold_case(case_id)
        evidence = load_evidence_case(case_id)
        public_text = public.model_dump_json().lower()
        assert evidence.title.lower() not in public_text
        assert evidence.official_url.lower() not in public_text
        assert str(gold.expected_selected_primitive).lower() not in public_text
        assert public.access_model == gold.access_model == evidence.access_model
        assert public.output_contract == gold.output_contract == evidence.output_contract


def test_all_cases_score_deterministically(tmp_path: Path) -> None:
    raw_passes = 0
    system_passes = 0
    for case_id in load_manifest()["ready_cases"]:
        public = load_public_case(case_id)
        result = Orchestrator().run(public.model_dump(mode="json"), output_dir=tmp_path)
        state_before = deepcopy(result.state).model_dump(mode="json")
        score = score_case(case_id, result.state, result.decision)
        assert result.state.model_dump(mode="json") == state_before
        raw_passes += int(score.raw_reasoning_score["raw_pass"])
        system_passes += int(score.system_score["system_pass"])
    assert raw_passes == 10
    assert system_passes == 10

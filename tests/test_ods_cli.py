from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import scripts.score_open_discovery as scorer
from quantummindlite.llm import ProviderError, ProviderResult, ProviderTrace
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import (
    AnalysisCard,
    BarrierAssessment,
    CandidateCard,
    ClaimScope,
    DecisionCard,
    EvidenceState,
    MatchStrength,
    PrimitiveMatch,
    ProblemCard,
    Route,
    RunState,
    Verdict,
    WeakAnalogyOpportunity,
)
from quantummindlite.ods import ODSJudgeAssessment
from quantummindlite.registry import load_runtime_registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def public_registry() -> Any:
    return load_runtime_registry(PROJECT_ROOT)


def public_state(*, scheme_step: str = "Apply reflections around the prepared state and marked subspace.") -> RunState:
    return RunState(
        problem_card=ProblemCard(
            statement="Find one marked witness in a represented finite search space.",
            input_model="finite_candidate_set",
            access_model="coherent_oracle",
            output_contract="one_witness",
            promises=["marked_fraction_positive"],
            size_parameters=["N", "M"],
            ambiguities=["Oracle construction cost remains to be bounded."],
        ),
        analysis_card=AnalysisCard(
            formalized_problem="Return any x with f(x)=1.",
            canonical_structure_ids=["black_box_witness_search"],
            absent_or_weak_structures=["algebraic_structure"],
            classical_baseline="Theta(N/M) oracle queries",
            bottleneck="marked-item search",
            complexity_model="query complexity",
        ),
        candidate_card=CandidateCard(
            primitive_matches=[
                PrimitiveMatch(
                    primitive_id="amplitude_amplification",
                    strength=MatchStrength.PLAUSIBLE,
                    prerequisites=["State preparation", "coherent phase oracle", "Coherent phase oracle"],
                )
            ],
            weak_analogy_opportunities=[
                WeakAnalogyOpportunity(
                    primitive_id="quantum_walk",
                    missing_access_or_output_or_promises=["output contract", "access model"],
                    why_not_selected="The local transition structure is not explicit.",
                    possible_reformulation_question="Can the candidates be represented by a local walk?",
                )
            ],
            selected_candidate="amplitude_amplification",
            barriers=[
                BarrierAssessment(
                    barrier_id="oracle_construction",
                    description="The oracle construction cost needs an explicit bound.",
                    applicable=EvidenceState.UNKNOWN,
                    blocked_scopes=[ClaimScope.END_TO_END, ClaimScope.GATE],
                )
            ],
            scheme_steps=[scheme_step],
            classical_baseline="Theta(N/M) oracle queries",
            quantum_query_complexity="O(sqrt(N/M)) oracle queries",
            claim_scope=ClaimScope.QUERY,
            limitations=["No end-to-end advantage is claimed."],
            expert_questions=["Can the coherent predicate be implemented below the classical search cost?"],
            claim_flags=["ORACLE_CONSTRUCTION_PROVIDED", "output_reconstruction_proved"],
            self_assessment="system-specific self praise",
        ),
        messages=[{"system_id": "secret-system", "run_dir": "secret/run", "trace": "private"}],
    )


def assessment_payload(value: int = 3) -> dict[str, Any]:
    return {
        "technical_validity": value,
        "epistemic_auditability": value,
        "research_utility": value,
        "technical_rationale": "Technically coherent at the represented query scope.",
        "auditability_rationale": "Assumptions and limitations are explicit.",
        "utility_rationale": "The proposal identifies a concrete next question.",
        "critical_issue": None,
    }


class FakeProvider:
    provider_name = "openai"
    model_name = "judge-test-model"

    def __init__(self, *, fail_at: int | None = None, invalid_at: int | None = None, refusal: str = "policy refusal") -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_at = fail_at
        self.invalid_at = invalid_at
        self.refusal = refusal

    def generate(
        self,
        role: Role,
        action: ActionType,
        prompt: str,
        inputs: dict[str, Any],
        output_model: type[BaseModel],
    ) -> ProviderResult:
        self.calls.append({"role": role, "action": action, "prompt": prompt, "inputs": inputs, "output_model": output_model})
        call_number = len(self.calls)
        if self.fail_at == call_number:
            trace = ProviderTrace(provider="openai", model="actual-judge-model", status="refusal", refusal=self.refusal)
            raise ProviderError(f"judge refused: {self.refusal}", trace)
        trace = ProviderTrace(
            provider="openai",
            model="actual-judge-model",
            usage={"input_tokens": 10 + call_number, "output_tokens": 4},
            attempt_count=call_number,
        )
        if self.invalid_at == call_number:
            payload = assessment_payload(call_number)
            payload["technical_validity"] = "never-persist-this-secret"
            return ProviderResult(payload, trace)
        return ProviderResult(assessment_payload(call_number), trace)


def evaluate(tmp_path: Path, provider: FakeProvider | None, *, offline: bool = False) -> dict[str, Any]:
    registry, barriers = public_registry()
    submission = scorer.build_blind_submission(public_state(), registry, barriers)
    return scorer.evaluate_submission(
        submission,
        graph_status="PASS",
        claim_accepted=True,
        research_disposition="REFORMULATE",
        prompt="frozen judge prompt",
        cache_dir=tmp_path / "judge_cache",
        provider_name="openai",
        requested_model="judge-test-model",
        reasoning_effort="high",
        provider=provider,
        offline=offline,
    )


def test_blind_submission_excludes_metadata_cached_conclusions_and_magic_tokens() -> None:
    registry, barriers = public_registry()
    packet = scorer.build_blind_submission(public_state(scheme_step="output_reconstruction_proved must not leak"), registry, barriers)
    text = json.dumps(packet, sort_keys=True)
    forbidden_terms = (
        "system_id run_dir graph_status claim_accepted research_disposition hard_blockers unknown_obligations self_assessment "
        "claim_flags messages trace ORACLE_CONSTRUCTION_PROVIDED output_reconstruction_proved secret-system"
    )
    for forbidden in forbidden_terms.split():
        assert forbidden not in text


def test_blind_submission_is_deterministic_and_contains_public_registry_context() -> None:
    registry, barriers = public_registry()
    state_a = public_state()
    state_b = state_a.model_copy(deep=True)
    state_b.messages = [{"different": "system and path metadata"}]
    packet_a = scorer.build_blind_submission(state_a, registry, barriers)
    packet_b = scorer.build_blind_submission(state_b, registry, barriers)
    assert scorer.canonical_json_bytes(packet_a) == scorer.canonical_json_bytes(packet_b)
    context = packet_a["public_registry_context"]
    assert (
        context["selected_primitive"] == "amplitude_amplification"
        and context["relevant_barrier_specs"][0]["barrier_id"] == "oracle_construction"
    )


def test_blind_submission_normalizes_nested_set_like_lists() -> None:
    registry, barriers = public_registry()
    state_a = public_state()
    state_b = state_a.model_copy(deep=True)
    candidate = state_b.candidate_card
    assert candidate is not None
    candidate.primitive_matches[0].prerequisites.reverse()
    candidate.weak_analogy_opportunities[0].missing_access_or_output_or_promises.reverse()
    candidate.barriers[0].blocked_scopes.reverse()
    assert scorer.build_blind_submission(state_a, registry, barriers) == scorer.build_blind_submission(state_b, registry, barriers)


def test_three_reviewer_profiles_are_called_in_locked_order_with_blind_inputs(tmp_path: Path) -> None:
    provider = FakeProvider()
    outcome = evaluate(tmp_path, provider)
    assert outcome["score_status"] == "OK"
    assert [call["inputs"]["reviewer_profile"]["name"] for call in provider.calls] == list(scorer.REVIEWER_PROFILES)
    focuses = [call["inputs"]["reviewer_profile"]["focus"] for call in provider.calls]
    assert "hidden hardness" in focuses[1] and "post-processing" in focuses[1] and "explicit barriers" in focuses[1]
    assert "calibration of novelty and uncertainty" in focuses[2]
    assert all(call["role"] is Role.CONSISTENCY_REVIEWER for call in provider.calls)
    assert all(call["action"] is ActionType.CONSISTENCY_REVIEW for call in provider.calls)
    assert all(call["output_model"] is ODSJudgeAssessment for call in provider.calls)
    assert all(set(call["inputs"]) == {"reviewer_profile", "blind_submission"} for call in provider.calls)
    assert outcome["reviewer_results"][0]["technical_validity"] == 1
    assert outcome["reviewer_results"][2]["research_utility"] == 3


def test_valid_cache_hits_prevent_provider_calls_and_retain_trace_metadata(tmp_path: Path) -> None:
    first = evaluate(tmp_path, FakeProvider())
    refusing = FakeProvider(fail_at=1)
    second = evaluate(tmp_path, refusing)
    assert first["cache_hit_count"] == 0
    assert second["score_status"] == "OK"
    assert second["cache_hit_count"] == 3
    assert refusing.calls == []
    cache_entries = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((tmp_path / "judge_cache").glob("*.json"))]
    assert {entry["actual_model"] for entry in cache_entries} == {"actual-judge-model"}
    assert all(entry["usage"]["input_tokens"] > 0 for entry in cache_entries)


def test_offline_cache_miss_and_invalid_cache_never_call_provider(tmp_path: Path) -> None:
    missing = evaluate(tmp_path, None, offline=True)
    assert missing["score_status"] == "CACHE_MISS_OFFLINE"
    assert missing["ods_score"] == 0.0
    cache_dir = tmp_path / "judge_cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / f"{'0' * 64}.json").write_text("{not-json", encoding="utf-8")
    evaluate(tmp_path, FakeProvider())
    next(path for path in sorted(cache_dir.glob("*.json")) if path.stem != "0" * 64).write_text("{not-json", encoding="utf-8")
    invalid = evaluate(tmp_path, None, offline=True)
    assert invalid["score_status"] == "CACHE_INVALID"
    assert invalid["ods_score"] == 0.0


def test_malformed_cache_is_regenerated_live_and_provider_failure_scores_zero(tmp_path: Path) -> None:
    evaluate(tmp_path, FakeProvider())
    cache_file = next(iter(sorted((tmp_path / "judge_cache").glob("*.json"))))
    cache_file.write_text("{}", encoding="utf-8")
    regenerated_provider = FakeProvider()
    regenerated = evaluate(tmp_path, regenerated_provider)
    assert regenerated["score_status"] == "OK"
    assert len(regenerated_provider.calls) == 1
    failed = evaluate(tmp_path / "failed", FakeProvider(fail_at=2, refusal="never-persist-this-secret and rejected hidden reasoning"))
    assert failed["score_status"] == "JUDGE_FAILURE"
    assert failed["ods_score"] == 0.0
    assert failed["error"] == "FEASIBILITY_SKEPTIC: provider_refusal"
    assert "never-persist-this-secret" not in json.dumps(failed)
    invalid = evaluate(tmp_path / "invalid", FakeProvider(invalid_at=1))
    assert invalid["score_status"] == "JUDGE_FAILURE"
    assert invalid["error"] == "TECHNICAL_SKEPTIC: schema_error"
    assert "never-persist-this-secret" not in json.dumps(invalid)


@pytest.mark.parametrize(("field", "value"), [("provider_attempt_count", True), ("provider_attempt_count", 1.5), ("actual_model", "")])
def test_cache_validation_rejects_non_strict_required_fields(tmp_path: Path, field: str, value: Any) -> None:
    evaluate(tmp_path, FakeProvider())
    cache_file = next(iter(sorted((tmp_path / "judge_cache").glob("*.json"))))
    entry = json.loads(cache_file.read_text(encoding="utf-8"))
    entry[field] = value
    cache_file.write_text(json.dumps(entry), encoding="utf-8")
    assert evaluate(tmp_path, None, offline=True)["score_status"] == "CACHE_INVALID"


def test_cache_files_are_atomic_complete_and_contain_no_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def tracked_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", tracked_replace)
    monkeypatch.setenv("OPENAI_API_KEY", "never-persist-this-secret")
    evaluate(tmp_path, FakeProvider())
    assert len(replacements) == 3
    for source, destination in replacements:
        assert source.parent == destination.parent
        assert destination.suffix == ".json"
        text = destination.read_text(encoding="utf-8")
        assert "never-persist-this-secret" not in text
        entry = json.loads(text)
        assert set(scorer.CACHE_FIELDS) == set(entry)


def public_decision(*, verdict: Verdict = Verdict.POSITIVE, scope: ClaimScope = ClaimScope.QUERY) -> DecisionCard:
    return DecisionCard(
        authoritative_verdict=verdict,
        maximum_supported_claim_scope=scope,
        b_check_results=[],
        d_route=Route.EXPERT_REVIEW,
        concise_reasons=["synthetic public fixture"],
        claim_boundary_statement="diagnostic fixture only",
    )


def write_run(path: Path, *, malformed: str | None = None) -> None:
    path.mkdir(parents=True)
    state_text = public_state().model_dump_json()
    decision_text = public_decision().model_dump_json()
    (path / "state.json").write_text("{" if malformed == "state" else state_text, encoding="utf-8")
    (path / "decision.json").write_text("{" if malformed == "decision" else decision_text, encoding="utf-8")
    (path / "input.json").write_bytes(b"must never be read or changed")
    (path / "trace.jsonl").write_bytes(b"must never be read or changed")


def write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def screening_row(run_dir: Path, **updates: Any) -> dict[str, Any]:
    row = {
        "shard": run_dir.parent.name,
        "run": run_dir.name,
        "graph_status": "PASS",
        "claim_accepted": "True",
        "research_disposition": "REFORMULATE",
        "run_dir": run_dir.as_posix(),
        "verdict": "POSITIVE",
        "scope": "QUERY",
        "route": "EXPERT_REVIEW",
        "selected": "amplitude_amplification",
        "hard_blockers": "",
        "unknown_obligations": "S3_ORACLE_CONSTRUCTION",
        "output_alignment": "EXACT_OUTPUT_MATCH",
        "access_upgrade_status": "CONSISTENT",
        "oracle_status": "PARTIAL_CONSTRUCTION",
        "baseline_status": "BASELINE_UNVERIFIED",
        "generic_wrapper_motif": "False",
        "generic_estimation_motif": "False",
        "screening_version": "QAEG-screen-v0.1",
    }
    row.update(updates)
    return row


SUMMARY_FIELDS = tuple(screening_row(Path("shard/run")))


def make_manifest(path: Path, rows: Sequence[tuple[str, str, Path]]) -> None:
    write_csv(
        path,
        ("system_id", "task_id", "run_dir"),
        [{"system_id": system, "task_id": task, "run_dir": run.as_posix()} for system, task, run in rows],
    )


def test_manifest_is_exact_unique_and_balanced(tmp_path: Path) -> None:
    run = tmp_path / "shard" / "run"
    manifest = tmp_path / "manifest.csv"
    make_manifest(manifest, [("a", "case-1", run), ("b", "case-1", run)])
    rows = scorer.read_manifest(manifest, PROJECT_ROOT)
    scorer.validate_task_grid(rows)
    assert rows[0].run_dir == run.resolve()
    make_manifest(manifest, [("a", "case-1", run), ("a", "case-1", run)])
    with pytest.raises(ValueError, match="duplicate"):
        scorer.validate_task_grid(scorer.read_manifest(manifest, PROJECT_ROOT))
    make_manifest(manifest, [("a", "case-1", run), ("a", "case-2", tmp_path / "shard" / "run-2"), ("b", "case-1", run)])
    with pytest.raises(ValueError, match="task.*set|grid"):
        scorer.validate_task_grid(scorer.read_manifest(manifest, PROJECT_ROOT))
    manifest.write_text("system_id,task_id,run_dir,seed\na,t,r,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly"):
        scorer.read_manifest(manifest, PROJECT_ROOT)


def test_summary_mapping_join_keys_extra_rows_and_dispositions_are_strict(tmp_path: Path) -> None:
    run = tmp_path / "shard" / "run"
    manifest = tmp_path / "manifest.csv"
    summary = tmp_path / "summary.csv"
    make_manifest(manifest, [("a", "case-1", run)])
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run)])
    registry, barriers = public_registry()
    records = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)
    assert records[0].score_status == "STATE_MISSING"
    with pytest.raises(ValueError, match="summary.*system|missing.*summary"):
        scorer.load_run_records(manifest, [], PROJECT_ROOT, registry, barriers)
    with pytest.raises(ValueError, match="extra"):
        scorer.load_run_records(manifest, [f"a={summary}", f"unknown={summary}"], PROJECT_ROOT, registry, barriers)
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run), screening_row(tmp_path / "other" / "extra")])
    with pytest.raises(ValueError, match="extra"):
        scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run, research_disposition="UNKNOWN")])
    with pytest.raises(ValueError, match="disposition"):
        scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run), screening_row(run)])
    with pytest.raises(ValueError, match="duplicate"):
        scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)


def test_missing_summary_and_artifact_failures_remain_explicit_rows(tmp_path: Path) -> None:
    registry, barriers = public_registry()
    run = tmp_path / "shard" / "run"
    manifest = tmp_path / "manifest.csv"
    summary = tmp_path / "summary.csv"
    make_manifest(manifest, [("a", "case-1", run)])
    write_csv(summary, SUMMARY_FIELDS, [])
    assert scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0].score_status == "MISSING_SCREENING_ROW"
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run)])
    run.mkdir(parents=True)
    assert scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0].score_status == "STATE_MISSING"
    (run / "state.json").write_text(public_state().model_dump_json(), encoding="utf-8")
    assert scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0].score_status == "DECISION_MISSING"
    (run / "decision.json").write_text("{", encoding="utf-8")
    assert scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0].score_status == "DECISION_INVALID"
    (run / "decision.json").write_text(public_decision().model_dump_json(), encoding="utf-8")
    (run / "state.json").write_text("{", encoding="utf-8")
    malformed = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0]
    assert malformed.score_status == "STATE_INVALID" and malformed.decision is not None
    (run / "state.json").write_text(public_state().model_dump_json(), encoding="utf-8")
    write_csv(summary, SUMMARY_FIELDS, [])
    unmatched = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0]
    assert unmatched.score_status == "MISSING_SCREENING_ROW" and unmatched.state is not None and unmatched.decision is not None


def test_artifact_screening_mismatch_and_forbidden_files_are_not_read_or_modified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry, barriers = public_registry()
    run = tmp_path / "shard" / "run"
    write_run(run)
    manifest, summary = tmp_path / "manifest.csv", tmp_path / "summary.csv"
    make_manifest(manifest, [("a", "case-1", run)])
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run, verdict="NEGATIVE")])
    mismatch = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0]
    assert mismatch.score_status == "ARTIFACT_SCREENING_MISMATCH"
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run, scope="END_TO_END")])
    mismatch = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0]
    assert mismatch.score_status == "ARTIFACT_SCREENING_MISMATCH"
    write_csv(summary, SUMMARY_FIELDS, [screening_row(run)])
    before = {path.name: path.read_bytes() for path in run.iterdir()}
    real_open = Path.open

    def reject_forbidden_reads(path: Path, *args: Any, **kwargs: Any) -> Any:
        normalized = path.as_posix().casefold()
        if path.name in {"input.json", "trace.jsonl"} or "/paperbench/gold/" in normalized or "/paperbench/evidence/" in normalized:
            raise AssertionError(f"forbidden evaluator read: {path}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_forbidden_reads)
    ready = scorer.load_run_records(manifest, [f"a={summary}"], PROJECT_ROOT, registry, barriers)[0]
    monkeypatch.setattr(Path, "open", real_open)
    assert ready.score_status == "READY"
    assert ready.blind_submission is not None
    assert {path.name: path.read_bytes() for path in run.iterdir()} == before


def populate_real_prompt_cache(output_dir: Path, state: RunState) -> None:
    registry, barriers = load_runtime_registry(PROJECT_ROOT)
    scorer.evaluate_submission(
        scorer.build_blind_submission(state, registry, barriers),
        graph_status="PASS",
        claim_accepted=True,
        research_disposition="REFORMULATE",
        prompt=scorer.load_judge_prompt(PROJECT_ROOT),
        cache_dir=output_dir / "judge_cache",
        provider_name="openai",
        requested_model="judge-test-model",
        reasoning_effort="high",
        provider=FakeProvider(),
        offline=False,
    )


def test_cli_validate_only_offline_end_to_end_and_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = [tmp_path / "runs" / system / "run" for system in ("ref", "cmp")]
    for run in runs:
        write_run(run)
    manifest, ref_summary, cmp_summary = tmp_path / "manifest.csv", tmp_path / "ref.csv", tmp_path / "cmp.csv"
    make_manifest(manifest, [("ref", "case-1", runs[0]), ("cmp", "case-1", runs[1])])
    write_csv(ref_summary, SUMMARY_FIELDS, [screening_row(runs[0])])
    write_csv(cmp_summary, SUMMARY_FIELDS, [screening_row(runs[1])])
    output = tmp_path / "output"
    common = [
        "--manifest",
        str(manifest),
        "--summary",
        f"ref={ref_summary}",
        "--summary",
        f"cmp={cmp_summary}",
        "--output-dir",
        str(output),
    ]
    monkeypatch.setattr(scorer, "OpenAIStructuredProvider", pytest.fail)
    assert scorer.main([*common, "--validate-only"]) == 0
    counts = json.loads(capsys.readouterr().out)
    assert counts == {
        "blind_packet_count": 2,
        "matched_screening_rows": 2,
        "manifest_rows": 2,
        "planned_reviewer_calls": 6,
        "valid_decision_count": 2,
        "valid_state_count": 2,
    }
    assert not output.exists()
    populate_real_prompt_cache(output, public_state())
    assert (
        scorer.main([*common, "--offline", "--model", "judge-test-model", "--reasoning-effort", "high", "--reference-system", "ref"]) == 0
    )
    assert {path.name for path in output.iterdir()} == {"judge_cache", "per_run_scores.csv", "summary.json"}
    score_rows = list(csv.DictReader((output / "per_run_scores.csv").open(encoding="utf-8", newline="")))
    assert [(row["system_id"], row["task_id"]) for row in score_rows] == [("cmp", "case-1"), ("ref", "case-1")]
    summary_text = (output / "summary.json").read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert summary_text == json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert summary["corpus"]["task_count_per_system"] == {"cmp": 1, "ref": 1}
    assert summary["pairwise"]["cmp"]["exact_ties"] == 1
    missing_manifest = tmp_path / "missing.csv"
    make_manifest(missing_manifest, [("ref", "case-1", tmp_path / "missing" / "run")])
    missing_summary = tmp_path / "missing-summary.csv"
    write_csv(missing_summary, SUMMARY_FIELDS, [screening_row(tmp_path / "missing" / "run")])
    assert (
        scorer.main(
            [
                "--manifest",
                str(missing_manifest),
                "--summary",
                f"ref={missing_summary}",
                "--offline",
                "--model",
                "judge-test-model",
                "--output-dir",
                str(tmp_path / "failed-output"),
            ]
        )
        == 2
    )
    make_manifest(missing_manifest, [("ref", "case-1", runs[0]), ("ref", "case-1", runs[0])])
    assert (
        scorer.main(
            [
                "--manifest",
                str(missing_manifest),
                "--summary",
                f"ref={ref_summary}",
                "--validate-only",
                "--output-dir",
                str(tmp_path / "invalid-output"),
            ]
        )
        == 1
    )


def test_one_system_cli_succeeds_and_malformed_run_does_not_stop_valid_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good, bad = tmp_path / "runs" / "one" / "good", tmp_path / "runs" / "one" / "bad"
    write_run(good)
    write_run(bad, malformed="state")
    manifest, summary = tmp_path / "manifest.csv", tmp_path / "summary.csv"
    make_manifest(manifest, [("one", "case-good", good)])
    write_csv(summary, SUMMARY_FIELDS, [screening_row(good)])
    output = tmp_path / "successful-output"
    populate_real_prompt_cache(output, public_state())
    monkeypatch.setattr(scorer, "OpenAIStructuredProvider", pytest.fail)
    common = [
        "--manifest",
        str(manifest),
        "--summary",
        f"one={summary}",
        "--model",
        "judge-test-model",
        "--reasoning-effort",
        "high",
    ]
    assert scorer.main([*common, "--offline", "--output-dir", str(output)]) == 0
    assert list(csv.DictReader((output / "per_run_scores.csv").open(encoding="utf-8")))[0]["score_status"] == "OK"

    make_manifest(manifest, [("one", "case-bad", bad), ("one", "case-good", good)])
    write_csv(summary, SUMMARY_FIELDS, [screening_row(bad), screening_row(good)])
    mixed_output = tmp_path / "mixed-output"
    assert scorer.main([*common, "--validate-only", "--output-dir", str(mixed_output)]) == 2
    counts = json.loads(capsys.readouterr().out)
    assert counts["valid_state_count"] == 1 and counts["valid_decision_count"] == 2
    assert counts["blind_packet_count"] == 1 and counts["planned_reviewer_calls"] == 3
    populate_real_prompt_cache(mixed_output, public_state())
    assert scorer.main([*common, "--offline", "--output-dir", str(mixed_output)]) == 2
    statuses = {row["task_id"]: row["score_status"] for row in csv.DictReader((mixed_output / "per_run_scores.csv").open(encoding="utf-8"))}
    assert statuses == {"case-bad": "STATE_INVALID", "case-good": "OK"}

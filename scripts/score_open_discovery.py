from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from quantummindlite._graph_screen import ResearchDisposition
from quantummindlite.llm import LLMProvider, ProviderError, ProviderResult
from quantummindlite.messages import ActionType, Role
from quantummindlite.models import BarrierSpec, DecisionCard, PrimitiveSpec, RunState
from quantummindlite.ods import (
    DIMENSION_WEIGHTS,
    DISPOSITION_PRIORS,
    EPSILON,
    FUSION_WEIGHTS,
    KAPPA,
    MAD_MULTIPLIER,
    ODS_VERSION,
    UNCERTAINTY_PENALTY,
    ODSJudgeAssessment,
    calculate_ods_score,
)
from quantummindlite.openai_provider import OpenAIStructuredProvider
from quantummindlite.registry import load_runtime_registry, project_root, resource_root

REVIEWER_PROFILES = ("TECHNICAL_SKEPTIC", "FEASIBILITY_SKEPTIC", "RESEARCH_VALUE_SKEPTIC")
REVIEWER_FOCUS = {
    "TECHNICAL_SKEPTIC": (
        "task preservation; primitive mapping; output recovery; comparable complexity; claim scope; mathematical coherence"
    ),
    "FEASIBILITY_SKEPTIC": (
        "access assumptions; oracle construction; circularity or hidden hardness; state preparation; readout and "
        "post-processing; promises; unaccounted implementation costs; explicit barriers"
    ),
    "RESEARCH_VALUE_SKEPTIC": (
        "whether the idea is more than generic Groverization or generic estimation; use of problem-specific structure; "
        "concreteness of a reformulation; usefulness of a negative diagnosis; credible next research step; calibration of "
        "novelty and uncertainty"
    ),
}
CACHE_FIELDS = (
    "cache_key",
    "ods_version",
    "prompt_sha256",
    "reviewer_profile",
    "blind_submission_sha256",
    "provider",
    "requested_model",
    "actual_model",
    "reasoning_effort",
    "assessment",
    "usage",
    "provider_status",
    "provider_attempt_count",
    "created_at",
)
SCIENTIFIC_BOUNDARY = (
    "ODS is a rubric-calibrated research-utility score. It is not a probability that a proposed quantum algorithm is "
    "correct, novel, physically implementable, or asymptotically faster end to end."
)
SCORE_BANDS = {
    "0-24": "invalid or unusable",
    "25-44": "very weak",
    "45-59": "diagnostic but underdeveloped",
    "60-69": "high-quality negative or repair path",
    "70-84": "strong research lead",
    "85-100": "high-priority expert-review candidate",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _public_fields(model: Any, fields: str, sorted_lists: str = "") -> dict[str, Any]:
    data = {} if model is None else model.model_dump(mode="json", include=set(fields.split()))
    for field in sorted_lists.split():
        data[field] = sorted(dict.fromkeys(data.get(field, [])), key=lambda item: (str(item).casefold(), str(item)))
    return data


def _public_models(models: Sequence[Any], fields: str, sorted_lists: str = "") -> list[dict[str, Any]]:
    return sorted((_public_fields(model, fields, sorted_lists) for model in models), key=canonical_json_bytes)


def reviewer_profile(name: str) -> dict[str, str]:
    return {"name": name, "focus": REVIEWER_FOCUS[name]}


def _neutralize_markers(value: Any) -> Any:
    if isinstance(value, str):
        replacements = {
            "ORACLE_CONSTRUCTION_PROVIDED": "explicit oracle construction claim",
            "output_reconstruction_proved": "output reconstruction claim",
            "sufficient_subproblem_proved": "sufficient subproblem claim",
        }
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
    if isinstance(value, list):
        return [_neutralize_markers(item) for item in value]
    if isinstance(value, dict):
        return {key: _neutralize_markers(item) for key, item in value.items()}
    return value


def build_blind_submission(
    state: RunState,
    registry: Mapping[str, PrimitiveSpec],
    barriers: Mapping[str, BarrierSpec],
) -> dict[str, Any]:
    problem, analysis, candidate = state.problem_card, state.analysis_card, state.candidate_card
    matches = _public_models(candidate.primitive_matches, "primitive_id strength prerequisites", "prerequisites") if candidate else []
    analogies = (
        _public_models(
            candidate.weak_analogy_opportunities,
            "primitive_id missing_access_or_output_or_promises why_not_selected possible_reformulation_question",
            "missing_access_or_output_or_promises",
        )
        if candidate
        else []
    )
    findings = _public_models(candidate.barriers, "barrier_id description applicable blocked_scopes", "blocked_scopes") if candidate else []
    primitive_ids = {item["primitive_id"] for item in matches} | (
        {candidate.selected_candidate} if candidate and candidate.selected_candidate else set()
    )
    specs = [registry[item] for item in sorted(primitive_ids) if item in registry]
    barrier_ids = {item["barrier_id"] for item in findings} | {item for spec in specs for item in spec.common_barriers}
    proposal = _public_fields(candidate, "selected_candidate no_candidate_reason scheme_steps")
    proposal.update(
        primitive_matches=matches,
        weak_analogy_opportunities=analogies,
    )
    feasibility = _public_fields(candidate, "limitations expert_questions prior_art_status novelty_status", "limitations expert_questions")
    feasibility.update(
        barriers=findings,
        prior_art_status_claim=feasibility.pop("prior_art_status", None),
        novelty_status_claim=feasibility.pop("novelty_status", None),
    )
    primitive_fields = (
        "primitive_id required_structure_ids allowed_access_models allowed_output_contracts required_promises "
        "supported_claim_scope speedup_class classical_complexity quantum_complexity common_barriers source_ids"
    )
    primitive_lists = "required_structure_ids allowed_access_models allowed_output_contracts required_promises common_barriers source_ids"
    barrier_fields = "barrier_id description blocked_scopes satisfied_by_access_models satisfied_by_output_contracts satisfied_by_promises"
    barrier_lists = "blocked_scopes satisfied_by_access_models satisfied_by_output_contracts satisfied_by_promises"
    return cast(
        dict[str, Any],
        _neutralize_markers(
            {
                "task": _public_fields(
                    problem,
                    "statement input_model access_model output_contract promises size_parameters ambiguities",
                    "promises size_parameters ambiguities",
                ),
                "analysis": _public_fields(
                    analysis,
                    "formalized_problem canonical_structure_ids absent_or_weak_structures classical_baseline bottleneck complexity_model",
                    "canonical_structure_ids absent_or_weak_structures",
                ),
                "proposal": proposal,
                "complexity": _public_fields(
                    candidate, "classical_baseline quantum_query_complexity gate_complexity total_complexity claim_scope"
                ),
                "feasibility_and_calibration": feasibility,
                "public_registry_context": {
                    "selected_primitive": candidate.selected_candidate if candidate else None,
                    "matched_primitive_specs": [_public_fields(spec, primitive_fields, primitive_lists) for spec in specs],
                    "relevant_barrier_specs": [
                        _public_fields(barriers[item], barrier_fields, barrier_lists) for item in sorted(barrier_ids) if item in barriers
                    ],
                },
            }
        ),
    )


def judge_cache_identity(
    blind_submission: dict[str, Any],
    *,
    prompt_sha256: str,
    reviewer_profile: Mapping[str, str],
    provider: str,
    requested_model: str,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    return {
        "ods_version": ODS_VERSION,
        "judge_prompt_sha256": prompt_sha256,
        "reviewer_profile": dict(reviewer_profile),
        "blind_submission": blind_submission,
        "provider": provider,
        "requested_model": requested_model,
        "reasoning_effort": reasoning_effort,
    }


def judge_cache_key(blind_submission: dict[str, Any], **configuration: Any) -> str:
    return _sha256(canonical_json_bytes(judge_cache_identity(blind_submission, **configuration)))


def _cache_state(path: Path, expected: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if not path.is_file():
        return "missing", None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != set(CACHE_FIELDS):
            return "invalid", None
        if any(value[key] != expected[key] for key in expected):
            return "invalid", None
        attempts, actual_model = value["provider_attempt_count"], value["actual_model"]
        if value["cache_key"] != path.stem or type(attempts) is not int or attempts < 1:
            return "invalid", None
        if not isinstance(actual_model, str) or not actual_model.strip() or value["provider_status"] != "ok":
            return "invalid", None
        if value["usage"] is not None and not isinstance(value["usage"], dict):
            return "invalid", None
        if not isinstance(value["created_at"], str) or datetime.fromisoformat(value["created_at"]).utcoffset() != timedelta(0):
            return "invalid", None
        value["assessment"] = ODSJudgeAssessment.model_validate(value["assessment"]).model_dump(mode="json")
        return "hit", value
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError):
        return "invalid", None


def _write_cache(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, prefix=".ods-", suffix=".tmp", delete=False
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp = Path(handle.name)
        os.replace(temp, path)
        temp = None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _cache_entry(
    key: str,
    prompt_sha256: str,
    profile: Mapping[str, str],
    submission_sha256: str,
    provider_name: str,
    requested_model: str,
    reasoning_effort: str | None,
    assessment: ODSJudgeAssessment,
    result: ProviderResult,
) -> dict[str, Any]:
    return {
        "cache_key": key,
        "ods_version": ODS_VERSION,
        "prompt_sha256": prompt_sha256,
        "reviewer_profile": dict(profile),
        "blind_submission_sha256": submission_sha256,
        "provider": provider_name,
        "requested_model": requested_model,
        "actual_model": result.trace.model,
        "reasoning_effort": reasoning_effort,
        "assessment": assessment.model_dump(mode="json"),
        "usage": result.trace.usage,
        "provider_status": result.trace.status,
        "provider_attempt_count": result.trace.attempt_count,
        "created_at": datetime.now(UTC).isoformat(),
    }


def evaluate_submission(
    blind_submission: dict[str, Any],
    *,
    graph_status: str,
    claim_accepted: bool,
    research_disposition: str,
    prompt: str,
    cache_dir: Path,
    provider_name: str,
    requested_model: str,
    reasoning_effort: str | None,
    provider: LLMProvider | None,
    offline: bool,
) -> dict[str, Any]:
    prompt_sha, submission_sha = _sha256(prompt.encode()), _sha256(canonical_json_bytes(blind_submission))
    reviews: list[ODSJudgeAssessment] = []
    cache_hits, cache_states, failures = 0, [], []
    for profile in REVIEWER_PROFILES:
        profile_input = reviewer_profile(profile)
        configuration = {
            "prompt_sha256": prompt_sha,
            "reviewer_profile": profile_input,
            "provider": provider_name,
            "requested_model": requested_model,
            "reasoning_effort": reasoning_effort,
        }
        key = judge_cache_key(blind_submission, **configuration)
        expected = {
            "cache_key": key,
            "ods_version": ODS_VERSION,
            "prompt_sha256": prompt_sha,
            "reviewer_profile": profile_input,
            "blind_submission_sha256": submission_sha,
            "provider": provider_name,
            "requested_model": requested_model,
            "reasoning_effort": reasoning_effort,
        }
        state, cached = _cache_state(cache_dir / f"{key}.json", expected)
        cache_states.append(state)
        if state == "hit" and cached is not None:
            reviews.append(ODSJudgeAssessment.model_validate(cached["assessment"]))
            cache_hits += 1
            continue
        if offline:
            continue
        if provider is None:
            raise ValueError("live evaluation requires an injected or resolved provider")
        try:
            result = provider.generate(
                Role.CONSISTENCY_REVIEWER,
                ActionType.CONSISTENCY_REVIEW,
                prompt,
                {"reviewer_profile": profile_input, "blind_submission": blind_submission},
                ODSJudgeAssessment,
            )
            assessment = ODSJudgeAssessment.model_validate(result.payload)
        except ProviderError as exc:
            kind = (
                "provider_refusal"
                if exc.trace.refusal is not None
                else "provider_incomplete"
                if exc.trace.incomplete_reason is not None
                else "provider_error"
            )
            failures.append(f"{profile}: {kind}")
            continue
        except ValidationError:
            failures.append(f"{profile}: schema_error")
            continue
        _write_cache(
            cache_dir / f"{key}.json",
            _cache_entry(
                key, prompt_sha, profile_input, submission_sha, provider_name, requested_model, reasoning_effort, assessment, result
            ),
        )
        reviews.append(assessment)
    if offline and len(reviews) != 3:
        status = "CACHE_INVALID" if "invalid" in cache_states else "CACHE_MISS_OFFLINE"
        return {
            "score_status": status,
            "error": status,
            "ods_score": 0.0,
            "cache_hit_count": cache_hits,
            "reviewer_results": [],
            "judge_model": requested_model,
        }
    if failures or len(reviews) != 3:
        return {
            "score_status": "JUDGE_FAILURE",
            "error": "; ".join(failures) or "incomplete judge evaluation",
            "ods_score": 0.0,
            "cache_hit_count": cache_hits,
            "reviewer_results": [],
            "judge_model": requested_model,
        }
    breakdown = calculate_ods_score(reviews, research_disposition, claim_accepted, graph_status)
    return {
        "score_status": "OK",
        "error": "",
        **breakdown,
        "cache_hit_count": cache_hits,
        "reviewer_results": [item.model_dump(mode="json") for item in reviews],
        "judge_model": requested_model,
    }


_MANIFEST_FIELDS = ("system_id", "task_id", "run_dir")
_REQUIRED_SUMMARY_FIELDS = ("shard", "run", "graph_status", "claim_accepted", "research_disposition")
_SUMMARY_OUTPUT_FIELDS = (
    "graph_status",
    "claim_accepted",
    "verdict",
    "scope",
    "research_disposition",
    "screening_version",
    "route",
    "selected",
    "hard_blockers",
    "unknown_obligations",
    "output_alignment",
    "access_upgrade_status",
    "oracle_status",
    "baseline_status",
    "generic_wrapper_motif",
    "generic_estimation_motif",
)
PER_RUN_FIELDS = (
    "system_id",
    "task_id",
    "run_dir",
    "score_status",
    "error",
    *_SUMMARY_OUTPUT_FIELDS,
    "ods_score",
    "technical_validity_0_4",
    "epistemic_auditability_0_4",
    "research_utility_0_4",
    "api_quality_0_100",
    "deterministic_prior_0_100",
    "fused_quality_0_100",
    "semantic_cap_0_100",
    "judge_disagreement_0_100",
    "reviewer_1_profile",
    "reviewer_1_t",
    "reviewer_1_e",
    "reviewer_1_r",
    "reviewer_2_profile",
    "reviewer_2_t",
    "reviewer_2_e",
    "reviewer_2_r",
    "reviewer_3_profile",
    "reviewer_3_t",
    "reviewer_3_e",
    "reviewer_3_r",
    "cache_hit_count",
    "judge_model",
)


@dataclass(frozen=True, slots=True)
class ManifestRow:
    system_id: str
    task_id: str
    run_dir_text: str
    run_dir: Path

    @property
    def join_key(self) -> tuple[str, str]:
        return self.run_dir.parent.name, self.run_dir.name


@dataclass(frozen=True, slots=True)
class ODSRunRecord:
    manifest: ManifestRow
    screening: dict[str, Any] | None = None
    state: RunState | None = None
    decision: DecisionCard | None = None
    blind_submission: dict[str, Any] | None = None
    score_status: str = "READY"
    error: str = ""


def read_manifest(path: Path, repository_root: Path) -> list[ManifestRow]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != _MANIFEST_FIELDS:
                raise ValueError("manifest columns must be exactly: system_id,task_id,run_dir")
            rows = []
            for raw in reader:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError(f"manifest row {reader.line_num} has a malformed field count")
                system, task, run_text = (raw[field].strip() for field in _MANIFEST_FIELDS)
                if not system or not task or not run_text:
                    raise ValueError(f"manifest row {reader.line_num} contains an empty field")
                run = Path(run_text)
                run = (run if run.is_absolute() else repository_root / run).resolve()
                rows.append(ManifestRow(system, task, run_text.replace("\\", "/"), run))
    except csv.Error as exc:
        raise ValueError(f"malformed manifest CSV: {exc}") from exc
    if not rows:
        raise ValueError("manifest must contain at least one row")
    return rows


def validate_task_grid(rows: Sequence[ManifestRow]) -> None:
    seen: set[tuple[str, str]] = set()
    tasks: dict[str, set[str]] = defaultdict(set)
    joins: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        key = row.system_id, row.task_id
        if key in seen:
            raise ValueError(f"duplicate manifest key: {key!r}")
        if row.join_key in joins[row.system_id]:
            raise ValueError(f"duplicate manifest summary join key for {row.system_id}: {row.join_key!r}")
        seen.add(key)
        tasks[row.system_id].add(row.task_id)
        joins[row.system_id].add(row.join_key)
    expected = next(iter(tasks.values()))
    if any(values != expected for values in tasks.values()):
        raise ValueError("system task set/grid mismatch")


def parse_summary_argument(value: str, repository_root: Path) -> tuple[str, Path]:
    system, separator, path_text = value.partition("=")
    if not separator or not system.strip() or not path_text.strip():
        raise ValueError("--summary must use SYSTEM_ID=PATH")
    path = Path(path_text.strip())
    return system.strip(), (path if path.is_absolute() else repository_root / path).resolve()


def read_screening_summary(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fields = tuple(reader.fieldnames or ())
            if len(fields) != len(set(fields)) or any(not field.strip() for field in fields):
                raise ValueError("screening summary has duplicate or blank columns")
            missing = set(_REQUIRED_SUMMARY_FIELDS) - set(fields)
            if missing:
                raise ValueError("screening summary missing required fields: " + ", ".join(sorted(missing)))
            rows: dict[tuple[str, str], dict[str, Any]] = {}
            for raw in reader:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError(f"screening summary row {reader.line_num} has a malformed field count")
                row = {key: value.strip() for key, value in raw.items()}
                key = row["shard"], row["run"]
                if not all(key) or key in rows:
                    raise ValueError(f"duplicate or blank screening summary key: {key!r}")
                if row["graph_status"] not in {"PASS", "WARN", "FAIL"}:
                    raise ValueError(f"unknown graph status on summary row {reader.line_num}")
                if row["claim_accepted"].casefold() not in {"true", "false"}:
                    raise ValueError(f"claim_accepted must be True or False on summary row {reader.line_num}")
                if row["research_disposition"] not in {item.value for item in ResearchDisposition}:
                    raise ValueError(f"unknown research disposition on summary row {reader.line_num}")
                row["claim_accepted"] = row["claim_accepted"].casefold() == "true"
                rows[key] = row
            return rows
    except csv.Error as exc:
        raise ValueError(f"malformed screening summary CSV: {exc}") from exc


def _failed(
    row: ManifestRow,
    screening: dict[str, Any] | None,
    status: str,
    error: str,
    *,
    state: RunState | None = None,
    decision: DecisionCard | None = None,
) -> ODSRunRecord:
    return ODSRunRecord(row, screening=screening, state=state, decision=decision, score_status=status, error=error)


def _prepare_run(
    row: ManifestRow,
    screening: dict[str, Any] | None,
    registry: Mapping[str, PrimitiveSpec],
    barriers: Mapping[str, BarrierSpec],
) -> ODSRunRecord:
    state_path, decision_path = row.run_dir / "state.json", row.run_dir / "decision.json"
    state, decision = None, None
    state_failure: tuple[str, str] | None = None
    decision_failure: tuple[str, str] | None = None
    if not state_path.is_file():
        state_failure = "STATE_MISSING", "state.json missing"
    else:
        try:
            state = RunState.model_validate_json(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            state_failure = "STATE_INVALID", "state.json failed RunState validation"
    if not decision_path.is_file():
        decision_failure = "DECISION_MISSING", "decision.json missing"
    else:
        try:
            decision = DecisionCard.model_validate_json(decision_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            decision_failure = "DECISION_INVALID", "decision.json failed DecisionCard validation"
    if screening is None:
        return _failed(row, None, "MISSING_SCREENING_ROW", "no matching (shard, run) screening row", state=state, decision=decision)
    if state_failure is not None:
        return _failed(row, screening, *state_failure, state=state, decision=decision)
    if decision_failure is not None:
        return _failed(row, screening, *decision_failure, state=state, decision=decision)
    assert state is not None and decision is not None
    if screening.get("verdict") and screening["verdict"] != decision.authoritative_verdict.value:
        return _failed(
            row,
            screening,
            "ARTIFACT_SCREENING_MISMATCH",
            "summary verdict disagrees with decision.json",
            state=state,
            decision=decision,
        )
    if screening.get("scope") and screening["scope"] != decision.maximum_supported_claim_scope.value:
        return _failed(
            row,
            screening,
            "ARTIFACT_SCREENING_MISMATCH",
            "summary scope disagrees with decision.json",
            state=state,
            decision=decision,
        )
    packet = build_blind_submission(state, registry, barriers)
    return ODSRunRecord(row, screening, state, decision, packet)


def load_run_records(
    manifest_path: Path,
    summary_arguments: Sequence[str],
    repository_root: Path,
    registry: Mapping[str, PrimitiveSpec],
    barriers: Mapping[str, BarrierSpec],
) -> list[ODSRunRecord]:
    rows = read_manifest(manifest_path, repository_root)
    validate_task_grid(rows)
    systems = {row.system_id for row in rows}
    summary_paths: dict[str, Path] = {}
    for argument in summary_arguments:
        system, path = parse_summary_argument(argument, repository_root)
        if system in summary_paths:
            raise ValueError(f"duplicate summary mapping for system {system}")
        summary_paths[system] = path
    if set(summary_paths) != systems:
        missing, extra_systems = systems - set(summary_paths), set(summary_paths) - systems
        raise ValueError(f"summary system mapping mismatch; missing={sorted(missing)}, extra={sorted(extra_systems)}")
    summaries = {system: read_screening_summary(path) for system, path in summary_paths.items()}
    expected = {system: {row.join_key for row in rows if row.system_id == system} for system in systems}
    for system, summary in summaries.items():
        extra_rows = set(summary) - expected[system]
        if extra_rows:
            raise ValueError(f"extra screening summary rows for {system}: {sorted(extra_rows)!r}")
    return [
        _prepare_run(row, summaries[row.system_id].get(row.join_key), registry, barriers)
        for row in sorted(rows, key=lambda item: (item.system_id, item.task_id))
    ]


def aggregate_systems(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["system_id"])].append(row)
    result = {}
    for system in sorted(grouped):
        items, scores = grouped[system], [float(item["_ods_score"]) for item in grouped[system]]
        successful = sum(item["score_status"] == "OK" for item in items)
        judge_failures = sum(item["score_status"] in {"JUDGE_FAILURE", "CACHE_INVALID", "CACHE_MISS_OFFLINE"} for item in items)
        result[system] = {
            "result_count": len(items),
            "successful_score_count": successful,
            "operational_failure_count": len(items) - successful - judge_failures,
            "judge_failure_count": judge_failures,
            "mean_ods": statistics.fmean(scores),
            "median_ods": statistics.median(scores),
            "population_standard_deviation": statistics.pstdev(scores),
            "minimum_ods": min(scores),
            "maximum_ods": max(scores),
            "mean_technical_validity_0_4": statistics.fmean(float(item["_technical_validity"]) for item in items),
            "mean_epistemic_auditability_0_4": statistics.fmean(float(item["_epistemic_auditability"]) for item in items),
            "mean_research_utility_0_4": statistics.fmean(float(item["_research_utility"]) for item in items),
            "strong_lead_count": sum(score >= 70 for score in scores),
            "strong_lead_rate": sum(score >= 70 for score in scores) / len(scores),
            "high_priority_count": sum(score >= 85 for score in scores),
            "high_priority_rate": sum(score >= 85 for score in scores) / len(scores),
            "disposition_counts": dict(sorted(Counter(str(item.get("research_disposition", "")) for item in items).items())),
            "graph_status_counts": dict(sorted(Counter(str(item.get("graph_status", "")) for item in items).items())),
            "claim_accepted_counts": dict(sorted(Counter(str(item.get("claim_accepted", "")) for item in items).items())),
        }
    return result


def compare_to_reference(rows: Sequence[dict[str, Any]], reference: str) -> dict[str, dict[str, Any]]:
    paired: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        paired[str(row["system_id"])][str(row["task_id"])] = float(row["_ods_score"])
    if reference not in paired:
        raise ValueError(f"reference system is absent: {reference}")
    output = {}
    for comparator in sorted(set(paired) - {reference}):
        tasks = sorted(paired[reference].keys() & paired[comparator].keys())
        ref_scores, comp_scores = [paired[reference][task] for task in tasks], [paired[comparator][task] for task in tasks]
        output[comparator] = {
            "paired_task_count": len(tasks),
            "reference_mean_ods": statistics.fmean(ref_scores),
            "comparator_mean_ods": statistics.fmean(comp_scores),
            "delta_mean_ods": statistics.fmean(a - b for a, b in zip(ref_scores, comp_scores, strict=True)),
            "reference_wins": sum(a > b for a, b in zip(ref_scores, comp_scores, strict=True)),
            "comparator_wins": sum(b > a for a, b in zip(ref_scores, comp_scores, strict=True)),
            "exact_ties": sum(a == b for a, b in zip(ref_scores, comp_scores, strict=True)),
        }
    return output


def load_judge_prompt(root: Path) -> str:
    return (resource_root(root) / "prompts" / "open_discovery_judge.md").read_text(encoding="utf-8")


def _validate_output_dir(output_dir: Path, records: Sequence[ODSRunRecord], inputs: Sequence[Path]) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("output directory path is not a directory")
    if any(output_dir == record.manifest.run_dir or output_dir.is_relative_to(record.manifest.run_dir) for record in records):
        raise ValueError("output directory must not be inside a run directory")
    targets = {(output_dir / name).resolve() for name in ("per_run_scores.csv", "summary.json")}
    if targets & {path.resolve() for path in inputs}:
        raise ValueError("output file conflicts with an input manifest or screening summary")


def _output_row(record: ODSRunRecord, outcome: dict[str, Any], model: str) -> dict[str, Any]:
    screening = record.screening or {}
    row = {
        "system_id": record.manifest.system_id,
        "task_id": record.manifest.task_id,
        "run_dir": record.manifest.run_dir_text,
        "score_status": outcome["score_status"],
        "error": outcome["error"],
    }
    row.update({field: screening.get(field, "") for field in _SUMMARY_OUTPUT_FIELDS})
    score = float(outcome.get("ods_score", 0.0))
    reviews = outcome.get("reviewer_results", [])
    row.update(
        {
            "ods_score": round(score, 1),
            "technical_validity_0_4": round(4 * outcome.get("technical_validity", 0.0), 4),
            "epistemic_auditability_0_4": round(4 * outcome.get("epistemic_auditability", 0.0), 4),
            "research_utility_0_4": round(4 * outcome.get("research_utility", 0.0), 4),
            "api_quality_0_100": round(100 * outcome.get("api_quality", 0.0), 4),
            "deterministic_prior_0_100": round(100 * outcome.get("deterministic_prior", 0.0), 4),
            "fused_quality_0_100": round(100 * outcome.get("fused_quality", 0.0), 4),
            "semantic_cap_0_100": round(100 * outcome.get("semantic_cap", 0.0), 4),
            "judge_disagreement_0_100": round(100 * outcome.get("judge_disagreement", 0.0), 4),
            "cache_hit_count": outcome.get("cache_hit_count", 0),
            "judge_model": model,
            "_ods_score": score,
            "_technical_validity": 4 * outcome.get("technical_validity", 0.0),
            "_epistemic_auditability": 4 * outcome.get("epistemic_auditability", 0.0),
            "_research_utility": 4 * outcome.get("research_utility", 0.0),
        }
    )
    for index, profile in enumerate(REVIEWER_PROFILES, 1):
        review = reviews[index - 1] if len(reviews) >= index else {}
        row.update(
            {
                f"reviewer_{index}_profile": profile,
                f"reviewer_{index}_t": review.get("technical_validity", ""),
                f"reviewer_{index}_e": review.get("epistemic_auditability", ""),
                f"reviewer_{index}_r": review.get("research_utility", ""),
            }
        )
    return row


def _git_state(root: Path) -> dict[str, Any]:
    options: dict[str, Any] = {"cwd": root, "text": True, "capture_output": True, "check": True}
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], **options).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], **options).stdout)
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _write_outputs(
    output_dir: Path,
    rows: list[dict[str, Any]],
    records: Sequence[ODSRunRecord],
    args: argparse.Namespace,
    root: Path,
    prompt: str,
    summary_paths: Mapping[str, Path],
    manifest_path: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "per_run_scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PER_RUN_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in PER_RUN_FIELDS} for row in rows)
    systems = sorted({record.manifest.system_id for record in records})
    tasks = sorted({record.manifest.task_id for record in records})
    summary = {
        "evaluator_name": "quantummind-open-discovery-score",
        "evaluator_version": ODS_VERSION,
        "scientific_boundary": SCIENTIFIC_BOUNDARY,
        "generated_at": datetime.now(UTC).isoformat(),
        "git": _git_state(root),
        "resolved_configuration": {
            "provider": args.provider,
            "requested_model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "timeout": args.timeout,
            "offline": args.offline,
            "reference_system": args.reference_system,
        },
        "locked_constants": {
            "epsilon": EPSILON,
            "mad_multiplier": MAD_MULTIPLIER,
            "uncertainty_penalty": UNCERTAINTY_PENALTY,
            "dimension_weights": DIMENSION_WEIGHTS,
            "fusion_weights": FUSION_WEIGHTS,
            "disposition_priors": DISPOSITION_PRIORS,
            "cap_table": {"fatal": 0.25, "generic": 0.58, "benchmark_only": 0.65, "not_claim_accepted": 0.68},
            "kappa": KAPPA,
            "score_bands": SCORE_BANDS,
        },
        "hashes": {
            "manifest_sha256": _sha256(manifest_path.read_bytes()),
            "screening_summary_sha256": {system: _sha256(path.read_bytes()) for system, path in sorted(summary_paths.items())},
            "judge_prompt_sha256": _sha256(prompt.encode()),
        },
        "corpus": {
            "system_ids": systems,
            "task_ids": tasks,
            "task_count_per_system": {system: len(tasks) for system in systems},
            "matched_row_count": sum(record.screening is not None for record in records),
            "operational_failure_count": sum(
                row["score_status"] not in {"OK", "JUDGE_FAILURE", "CACHE_INVALID", "CACHE_MISS_OFFLINE"} for row in rows
            ),
            "api_cache_failure_count": sum(row["score_status"] in {"JUDGE_FAILURE", "CACHE_INVALID", "CACHE_MISS_OFFLINE"} for row in rows),
            "successful_score_count": sum(row["score_status"] == "OK" for row in rows),
        },
        "per_system": aggregate_systems(rows),
        "pairwise": compare_to_reference(rows, args.reference_system) if args.reference_system else {},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score completed public open-discovery run artifacts with ODS-v1.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--summary", action="append", required=True)
    parser.add_argument("--provider", choices=("openai",), default="openai")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--reference-system")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = project_root(Path(__file__).resolve())
    manifest_path = Path(args.manifest).resolve()
    try:
        if args.offline and args.validate_only:
            raise ValueError("--offline and --validate-only are mutually exclusive")
        args.model = args.model or os.environ.get("QUANTUMMINDLITE_OPENAI_MODEL", "")
        args.reasoning_effort = args.reasoning_effort or os.environ.get("QUANTUMMINDLITE_REASONING_EFFORT")
        if not args.validate_only and not args.model:
            raise ValueError("live or offline scoring requires --model or QUANTUMMINDLITE_OPENAI_MODEL")
        registry, barriers = load_runtime_registry(root)
        records = load_run_records(manifest_path, args.summary, root, registry, barriers)
        systems = {record.manifest.system_id for record in records}
        if args.reference_system and args.reference_system not in systems:
            raise ValueError(f"reference system is absent: {args.reference_system}")
        summary_paths = dict(parse_summary_argument(value, root) for value in args.summary)
        output_dir = Path(args.output_dir).resolve()
        _validate_output_dir(output_dir, records, [manifest_path, *summary_paths.values()])
        prompt = load_judge_prompt(root)
    except (OSError, ValueError) as exc:
        print(f"ODS configuration error: {exc}", file=sys.stderr)
        return 1
    if args.validate_only:
        prompt_sha = _sha256(prompt.encode())
        for record in records:
            for profile in REVIEWER_PROFILES:
                if record.blind_submission is not None:
                    judge_cache_key(
                        record.blind_submission,
                        prompt_sha256=prompt_sha,
                        reviewer_profile=reviewer_profile(profile),
                        provider=args.provider,
                        requested_model=args.model or "<validate-only-unresolved>",
                        reasoning_effort=args.reasoning_effort,
                    )
        counts = {
            "manifest_rows": len(records),
            "matched_screening_rows": sum(record.screening is not None for record in records),
            "valid_state_count": sum(record.state is not None for record in records),
            "valid_decision_count": sum(record.decision is not None for record in records),
            "blind_packet_count": sum(record.blind_submission is not None for record in records),
            "planned_reviewer_calls": 3 * sum(record.blind_submission is not None for record in records),
        }
        print(json.dumps(counts, sort_keys=True))
        return 0 if all(record.score_status == "READY" for record in records) else 2
    try:
        provider: LLMProvider | None = (
            None
            if args.offline
            else OpenAIStructuredProvider(model=args.model, reasoning_effort=args.reasoning_effort, timeout=args.timeout)
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        print(f"ODS configuration error: {exc}", file=sys.stderr)
        return 1
    rows = []
    for record in records:
        if record.score_status == "READY" and record.blind_submission is not None and record.screening is not None:
            outcome = evaluate_submission(
                record.blind_submission,
                graph_status=str(record.screening["graph_status"]),
                claim_accepted=bool(record.screening["claim_accepted"]),
                research_disposition=str(record.screening["research_disposition"]),
                prompt=prompt,
                cache_dir=output_dir / "judge_cache",
                provider_name=args.provider,
                requested_model=args.model,
                reasoning_effort=args.reasoning_effort,
                provider=provider,
                offline=args.offline,
            )
        else:
            outcome = {
                "score_status": record.score_status,
                "error": record.error,
                "ods_score": 0.0,
                "cache_hit_count": 0,
                "reviewer_results": [],
            }
        rows.append(_output_row(record, outcome, args.model))
    _write_outputs(output_dir, rows, records, args, root, prompt, summary_paths, manifest_path)
    return 2 if any(row["score_status"] != "OK" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())

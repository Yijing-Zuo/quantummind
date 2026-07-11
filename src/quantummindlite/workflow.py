from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from .agent import Agent
from .llm import LLMProvider, MockLLMProvider, ProviderError, ProviderTrace, has_public_source_support
from .messages import ACTION_SPECS, ActionSpec, ActionType, Message
from .models import (
    AnalysisCard,
    BarrierAssessment,
    BarrierFinding,
    CandidateCard,
    ClaimScope,
    DecisionCard,
    EvidenceState,
    MatchStrength,
    NoveltyStatus,
    PriorArtStatus,
    ProblemCard,
    RunState,
    problem_prerequisite_mismatches,
    problem_satisfies_barrier,
    stable_union,
    weak_analogy_opportunity,
)
from .registry import (
    barrier_catalog_public_view,
    is_selectable_pathway,
    load_barrier_catalog,
    load_registry,
    load_source_catalog,
    registry_public_view,
    resource_root,
    source_catalog_public_view,
    structure_vocabulary,
)
from .storage import RunStore, digest_json
from .validation import build_decision

_EVIDENCE_RANK = {
    EvidenceState.NOT_APPLICABLE: 0,
    EvidenceState.CONTRADICTED: 0,
    EvidenceState.UNKNOWN: 1,
    EvidenceState.SUPPORTED: 2,
}

_PROBLEM_FIELDS = ("statement", "input_model", "access_model", "output_contract", "promises", "size_parameters", "ambiguities")


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    run_dir: Path
    state: RunState
    decision: DecisionCard
    stage_order: list[str]


class Orchestrator:
    def __init__(
        self,
        provider: LLMProvider | None = None,
        root: Path | None = None,
    ) -> None:
        self.resource_root = resource_root(root)
        self.provider = provider or MockLLMProvider()
        self.registry = load_registry(self.resource_root)
        self.barrier_catalog = load_barrier_catalog(self.resource_root)
        self.registry_public_view = registry_public_view(self.registry, selectable_only=True)
        self.structure_vocabulary = structure_vocabulary(self.registry)
        self.source_catalog_public_view = source_catalog_public_view(load_source_catalog(self.resource_root))
        self.agents = {
            spec.action: Agent(spec, self.provider, self.resource_root / "prompts" / spec.prompt_filename) for spec in ACTION_SPECS
        }

    def run(
        self,
        public_input: dict[str, Any],
        output_dir: Path | None = None,
        run_id: str | None = None,
    ) -> WorkflowResult:
        state = RunState(problem_card=_problem_from_public(public_input))
        store = RunStore.create(output_dir or Path.cwd() / "runs", run_id=run_id)
        store.write_json("input.json", public_input)
        stage_order: list[str] = []
        current_stage = ""
        try:
            for spec in ACTION_SPECS:
                current_stage = spec.action.value
                message = self._call_agent(spec, state, store)
                stage_order.append(spec.action.value)
                self._merge(state, spec, message)
            decision = build_decision(state, self.registry)
            store.write_json("state.json", state.model_dump(mode="json"))
            store.write_json("decision.json", decision.model_dump(mode="json"))
            return WorkflowResult(store.run_id, store.run_dir, state, decision, stage_order)
        except Exception as exc:
            store.write_json("partial_state.json", state.model_dump(mode="json"))
            store.write_json("error.json", {"stage": current_stage, "error": str(exc), "stage_order": stage_order})
            raise

    def _call_agent(
        self,
        spec: ActionSpec,
        state: RunState,
        store: RunStore,
    ) -> Message:
        agent = self.agents[spec.action]
        inputs = self._context(spec, state)
        prompt = agent.prompt_path.read_text(encoding="utf-8")
        started = perf_counter()
        error = ""
        message: Message | None = None
        provider_trace: ProviderTrace | None = None
        try:
            message = agent.run(inputs)
            self._enforce_source_support(spec, inputs, message)
            provider_trace = agent.last_provider_trace
        except ProviderError as exc:
            error = str(exc)
            provider_trace = exc.trace
            raise
        except Exception as exc:
            error = repr(exc)
            provider_trace = ProviderTrace(
                provider=getattr(self.provider, "provider_name", "unknown"),
                model=getattr(self.provider, "model_name", "unknown"),
                status="error",
                parse_status="schema_error",
            )
            raise
        finally:
            elapsed = perf_counter() - started
            trace = provider_trace or ProviderTrace(
                provider=getattr(self.provider, "provider_name", "unknown"),
                model=getattr(self.provider, "model_name", "unknown"),
                status="error" if error else "ok",
            )
            store.append_trace(
                {
                    "action_schema": spec.output_model.__name__,
                    "attempt_count": trace.attempt_count,
                    "error": error,
                    "incomplete_reason": trace.incomplete_reason,
                    "input_digest": digest_json(inputs),
                    "latency": round(elapsed, 6),
                    "model": trace.model,
                    "output_digest": digest_json(message.model_dump(mode="json")) if message else "",
                    "parse_status": trace.parse_status,
                    "prompt_digest": digest_json(prompt),
                    "provider": trace.provider,
                    "refusal": trace.refusal,
                    "role": spec.role.value,
                    "stage": spec.action.value,
                    "status": "error" if error and trace.status == "ok" else trace.status,
                    "usage": trace.usage,
                }
            )
        if message is None:
            raise AssertionError("agent call failed without raising")
        return message

    def _context(
        self,
        spec: ActionSpec,
        state: RunState,
    ) -> dict[str, Any]:
        readable: dict[str, Any] = {
            "public_case": state.problem_card.model_dump(mode="json") if state.problem_card else {},
            "structure_vocabulary": self.structure_vocabulary,
            "barrier_catalog_public_view": self._barrier_public_view(state),
        }
        if state.problem_card:
            readable["problem_card"] = state.problem_card.model_dump(mode="json")
        if state.analysis_card:
            readable["analysis_card"] = state.analysis_card.model_dump(mode="json")
        if state.candidate_card:
            candidate = state.candidate_card
            readable["primitive_matches"] = [item.model_dump(mode="json") for item in candidate.primitive_matches]
            readable["barriers"] = [item.model_dump(mode="json") for item in candidate.barriers]
            readable["candidate_selection"] = {
                "selected_candidate": candidate.selected_candidate,
                "no_candidate_reason": candidate.no_candidate_reason,
                "claim_scope": candidate.claim_scope.value,
            }
            readable["scheme_summary"] = {
                "scheme_steps": candidate.scheme_steps,
                "classical_baseline": candidate.classical_baseline,
                "quantum_query_complexity": candidate.quantum_query_complexity,
                "gate_complexity": candidate.gate_complexity,
                "total_complexity": candidate.total_complexity,
                "limitations": candidate.limitations,
                "expert_questions": candidate.expert_questions,
                "claim_flags": candidate.claim_flags,
                "self_assessment": candidate.self_assessment,
            }
            readable["prior_art_status"] = candidate.prior_art_status.value
            readable["novelty_status"] = candidate.novelty_status.value
        readable["registry_public_view"] = self.registry_public_view
        readable["source_catalog_public_view"] = self.source_catalog_public_view
        return {key: readable[key] for key in spec.allowed_context_keys if key in readable}

    def _enforce_source_support(self, spec: ActionSpec, inputs: dict[str, Any], message: Message) -> None:
        if spec.action is ActionType.PRIOR_ART:
            status = message.payload.get("prior_art_status")
            known = status in {PriorArtStatus.KNOWN_CASE_RECOVERY.value, PriorArtStatus.DIRECT_PRIOR_ART.value}
            if known and not has_public_source_support(inputs):
                message.payload["prior_art_status"] = PriorArtStatus.UNKNOWN.value
        if spec.action is ActionType.NOVELTY_AUDIT:
            status = message.payload.get("novelty_status")
            if status == NoveltyStatus.NOT_GLOBALLY_NOVEL.value and not has_public_source_support(inputs):
                message.payload["novelty_status"] = NoveltyStatus.UNASSESSED.value

    def _merge(self, state: RunState, spec: ActionSpec, message: Message) -> None:
        output = spec.output_model.model_validate(message.payload)
        if spec.merge_policy == "merge_formalization":
            if state.problem_card is None:
                raise ValueError("formalization requires a public ProblemCard")
            state.problem_card.ambiguities = stable_union(state.problem_card.ambiguities, output.model_dump(mode="json")["ambiguities"])
        elif spec.merge_policy == "replace_analysis_card":
            analysis = AnalysisCard.model_validate(output.model_dump(mode="json"))
            unknown = sorted(set(analysis.canonical_structure_ids) - set(self.structure_vocabulary))
            if unknown:
                raise ValueError("unknown canonical_structure_ids: " + ", ".join(unknown))
            state.analysis_card = analysis
        else:
            state.candidate_card = self._merge_candidate(state, spec, output)
        state.messages.append(message.model_dump(mode="json"))

    def _merge_candidate(self, state: RunState, spec: ActionSpec, output: BaseModel) -> CandidateCard:
        current = state.candidate_card or CandidateCard()
        merged = current.model_dump(mode="json")
        payload = output.model_dump(mode="json")
        if spec.merge_policy == "replace_primitive_matches":
            unknown = sorted(
                {str(match["primitive_id"]) for match in payload["primitive_matches"] if match["primitive_id"] not in self.registry}
            )
            if unknown:
                raise ValueError("unknown primitive_ids: " + ", ".join(unknown))
            merged["primitive_matches"], merged["weak_analogy_opportunities"] = self._normalize_primitive_matches(
                state.problem_card, payload["primitive_matches"]
            )
        elif spec.merge_policy == "merge_barriers":
            allowed_ids = self._relevant_barrier_ids(state, merged)
            merged["barriers"] = [
                item.model_dump(mode="json") for item in _merge_barriers(current.barriers, self._resolve_barriers(payload, allowed_ids))
            ]
            self._ensure_common_barriers(state, merged)
            self._reconcile_barriers(state, merged)
        elif spec.merge_policy == "set_prior_art":
            merged["prior_art_status"] = payload["prior_art_status"]
        elif spec.merge_policy == "merge_scheme":
            for key in (
                "selected_candidate",
                "no_candidate_reason",
                "scheme_steps",
                "classical_baseline",
                "quantum_query_complexity",
                "gate_complexity",
                "total_complexity",
                "claim_scope",
                "expert_questions",
                "claim_flags",
                "self_assessment",
            ):
                merged[key] = payload[key]
            merged["limitations"] = stable_union(current.limitations, payload["limitations"])
            self._normalize_selected_pathway(state, merged)
            _normalize_legitimate_no_candidate(merged)
            allowed = set(self._relevant_barrier_ids(state, {**merged, "barriers": []}))
            merged["barriers"] = [item for item in merged["barriers"] if item["barrier_id"] in allowed]
            self._ensure_common_barriers(state, merged)
            self._reconcile_barriers(state, merged)
        elif spec.merge_policy == "set_novelty":
            merged["novelty_status"] = payload["novelty_status"]
        elif spec.merge_policy == "append_consistency_review":
            merged["consistency_review_notes"] = stable_union(current.consistency_review_notes, payload["consistency_review_notes"])
        else:
            raise ValueError(f"unknown merge policy {spec.merge_policy!r}")
        return CandidateCard.model_validate(merged)

    def _normalize_primitive_matches(
        self, problem: ProblemCard | None, matches: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized: list[dict[str, Any]] = []
        opportunities: list[dict[str, Any]] = []
        for item in matches:
            match = dict(item)
            spec = self.registry[match["primitive_id"]]
            missing = problem_prerequisite_mismatches(problem, spec)
            if match["strength"] == MatchStrength.PLAUSIBLE.value and not is_selectable_pathway(spec):
                match["strength"] = MatchStrength.NOT_SUPPORTED.value
                match["prerequisites"] = stable_union(
                    list(match.get("prerequisites", [])),
                    ["registry entry is diagnostic and is not a selectable quantum pathway"],
                )
            elif match["strength"] == MatchStrength.PLAUSIBLE.value and missing:
                match["strength"] = MatchStrength.WEAK_ANALOGY.value
                match["prerequisites"] = stable_union(list(match.get("prerequisites", [])), missing)
                opportunities.append(weak_analogy_opportunity(match["primitive_id"], missing))
            elif match["strength"] == MatchStrength.WEAK_ANALOGY.value:
                opportunities.append(weak_analogy_opportunity(match["primitive_id"], missing or match.get("prerequisites", [])))
            normalized.append(match)
        return normalized, opportunities

    def _normalize_selected_pathway(self, state: RunState, merged: dict[str, Any]) -> None:
        selected = merged.get("selected_candidate")
        spec = self.registry.get(selected) if selected else None
        plausible = any(
            match.get("primitive_id") == selected and match.get("strength") == MatchStrength.PLAUSIBLE.value
            for match in merged.get("primitive_matches", [])
        )
        missing = problem_prerequisite_mismatches(state.problem_card, spec) if spec else []
        if spec is not None and is_selectable_pathway(spec) and plausible and not missing:
            return
        merged["selected_candidate"] = None
        merged["no_candidate_reason"] = merged.get("no_candidate_reason") or "No normalized PLAUSIBLE primitive satisfies the ProblemCard."

    def _barrier_public_view(self, state: RunState) -> list[dict[str, Any]]:
        return barrier_catalog_public_view({key: self.barrier_catalog[key] for key in self._relevant_barrier_ids(state)})

    def _relevant_primitive_ids(self, state: RunState, merged: dict[str, Any] | None = None) -> list[str]:
        candidate = merged or (state.candidate_card.model_dump(mode="json") if state.candidate_card else {})
        result: list[str] = []
        selected = candidate.get("selected_candidate")
        selected_spec = self.registry.get(selected) if selected else None
        if selected_spec and is_selectable_pathway(selected_spec):
            result.append(str(selected))
        else:
            for match in candidate.get("primitive_matches", []):
                primitive_id = str(match.get("primitive_id", ""))
                spec = self.registry.get(primitive_id)
                if match.get("strength") == MatchStrength.PLAUSIBLE.value and spec and is_selectable_pathway(spec):
                    result.append(primitive_id)
        if result:
            return stable_union([], result)
        analysis = state.analysis_card
        if analysis:
            structures = set(analysis.canonical_structure_ids)
            for primitive_id, spec in self.registry.items():
                if not is_selectable_pathway(spec) and set(spec.required_structure_ids) <= structures:
                    result.append(primitive_id)
        return stable_union([], result)

    def _relevant_barrier_ids(self, state: RunState, merged: dict[str, Any] | None = None) -> list[str]:
        result: list[str] = []
        for primitive_id in self._relevant_primitive_ids(state, merged):
            result.extend(self.registry[primitive_id].common_barriers)
        candidate = merged or (state.candidate_card.model_dump(mode="json") if state.candidate_card else {})
        result.extend(str(item["barrier_id"]) for item in candidate.get("barriers", []) if item.get("barrier_id") in self.barrier_catalog)
        return stable_union([], result)

    def _resolve_barriers(self, payload: dict[str, Any], allowed_ids: list[str]) -> list[BarrierAssessment]:
        allowed = set(allowed_ids)
        result: list[BarrierAssessment] = []
        for item in payload["barriers"]:
            finding = BarrierFinding.model_validate(item)
            spec = self.barrier_catalog.get(finding.barrier_id)
            if spec is None:
                raise ValueError(f"unknown barrier_id: {finding.barrier_id}")
            if finding.barrier_id not in allowed:
                continue
            result.append(
                BarrierAssessment(
                    barrier_id=finding.barrier_id,
                    description=spec.description,
                    applicable=finding.applicable,
                    blocked_scopes=spec.blocked_scopes,
                )
            )
        return result

    def _ensure_common_barriers(self, state: RunState, merged: dict[str, Any]) -> None:
        present = {item["barrier_id"] for item in merged["barriers"]}
        for primitive_id in self._relevant_primitive_ids(state, merged):
            for barrier_id in self.registry[primitive_id].common_barriers:
                if barrier_id in present:
                    continue
                spec = self.barrier_catalog[barrier_id]
                merged["barriers"].append(
                    BarrierAssessment(
                        barrier_id=barrier_id,
                        description=spec.description,
                        applicable=EvidenceState.UNKNOWN,
                        blocked_scopes=spec.blocked_scopes,
                    ).model_dump(mode="json")
                )
                present.add(barrier_id)

    def _reconcile_barriers(self, state: RunState, merged: dict[str, Any]) -> None:
        if state.problem_card is None:
            return
        reconciled: list[dict[str, Any]] = []
        for item in merged["barriers"]:
            catalog = self.barrier_catalog[item["barrier_id"]]
            satisfied = problem_satisfies_barrier(state.problem_card, catalog)
            applicability = EvidenceState.NOT_APPLICABLE.value if satisfied else item["applicable"]
            reconciled.append(
                BarrierAssessment(
                    barrier_id=catalog.barrier_id,
                    description=catalog.description,
                    applicable=applicability,
                    blocked_scopes=catalog.blocked_scopes,
                ).model_dump(mode="json")
            )
        merged["barriers"] = reconciled


def _problem_from_public(public_input: dict[str, Any]) -> ProblemCard:
    return ProblemCard.model_validate({key: public_input[key] for key in _PROBLEM_FIELDS if key in public_input})


def _normalize_legitimate_no_candidate(merged: dict[str, Any]) -> None:
    if merged.get("selected_candidate") is not None or not merged.get("no_candidate_reason"):
        return
    if any(match.get("strength") == MatchStrength.PLAUSIBLE.value for match in merged.get("primitive_matches", [])):
        return
    merged["scheme_steps"] = []
    merged["quantum_query_complexity"] = None
    merged["gate_complexity"] = None
    merged["total_complexity"] = None
    merged["claim_scope"] = ClaimScope.NONE.value


def _merge_barriers(existing: list[BarrierAssessment], incoming: list[BarrierAssessment]) -> list[BarrierAssessment]:
    by_id = {item.barrier_id: item for item in existing}
    order = [item.barrier_id for item in existing]
    for item in incoming:
        if item.barrier_id not in by_id:
            by_id[item.barrier_id] = item
            order.append(item.barrier_id)
            continue
        by_id[item.barrier_id] = _merge_duplicate_barrier(by_id[item.barrier_id], item)
    return [by_id[barrier_id] for barrier_id in order]


def _merge_duplicate_barrier(current: BarrierAssessment, incoming: BarrierAssessment) -> BarrierAssessment:
    stronger = incoming if _EVIDENCE_RANK[incoming.applicable] > _EVIDENCE_RANK[current.applicable] else current
    return BarrierAssessment(
        barrier_id=current.barrier_id,
        description=stronger.description or current.description,
        applicable=stronger.applicable,
        blocked_scopes=incoming.blocked_scopes or current.blocked_scopes,
    )

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import Field

from quantummindlite.models import ClaimScope, EvidenceState, NoveltyStatus, PrimitiveMatch, PriorArtStatus, StrictModel

# Literature-derived single-system baselines. Each strategy reproduces the
# method of a published system using the same base model and the same public
# knowledge as the QuantumMind agents, then emits one BaselineOutput that the
# runner normalizes into standard artifacts. Method citations:
#   self_consistency      Wang et al., "Self-Consistency Improves Chain of
#                         Thought Reasoning in Language Models", ICLR 2023.
#   react                 Yao et al., "ReAct: Synergizing Reasoning and Acting
#                         in Language Models", arXiv:2210.03629.
#   multi_agent_dialogue  Wu et al., "AutoGen: Enabling Next-Gen LLM
#                         Applications via Multi-Agent Conversation",
#                         arXiv:2308.08155 (conversational proposer/critic).
#   ideate_review         Lu et al., "The AI Scientist", arXiv:2408.06292
#                         (ideation followed by bounded self-review).
#   sciagents_style       Ghafarollahi and Buehler, "SciAgents", Advanced
#                         Materials 2025 (ontological-graph-grounded dialogue).
# Agent agreement never assigns the verdict; build_decision remains the sole
# authority for every baseline, matching docs/ODS_V1.md.

_SHARED_RULES = """
Output exactly one object of the requested schema.
Use primitive_id values only from the represented registry and barrier_id
values only from the represented barrier catalog; if nothing fits, report no
match rather than inventing an identifier.
Select a candidate only when the represented access model, output contract,
and promises support an asymptotic quantum-speedup claim at the stated scope.
Otherwise set selected_candidate to null and give a concrete no_candidate_reason.
Report barriers honestly, including ones that block your own proposal.
Do not overstate prior-art or novelty status: without a supporting public
source, use UNKNOWN / UNASSESSED.
"""

ZERO_SHOT_PROMPT = (
    "You are a single-call assessor. Given one public problem card plus public "
    "registries of quantum primitives, barriers, and sources, decide in one shot "
    "whether the problem supports an asymptotic quantum-speedup hypothesis, and "
    "fill every BaselineOutput field." + _SHARED_RULES
)

COT_PROMPT = (
    "You are a single-call assessor. Work through the problem step by step before "
    "answering: formalize the task; identify canonical structures and the "
    "classical baseline and bottleneck; compare each plausible primitive's "
    "prerequisites against the represented access model, output contract, and "
    "promises; assess applicable barriers; check prior art in the public source "
    "catalog; only then commit to a scheme or a no-candidate verdict. After "
    "reasoning, fill every BaselineOutput field." + _SHARED_RULES
)

REACT_STEP_PROMPT = (
    "You are assessing whether a problem supports an asymptotic quantum-speedup "
    "hypothesis, following a ReAct loop: think, then take one action. You start "
    "from identifier vocabularies only; use lookup actions to read full public "
    "registry or barrier entries before relying on them. Choose finish once you "
    "have enough evidence, or when nothing fits."
)

REACT_FINAL_PROMPT = (
    "The trajectory contains your prior thoughts, actions, and observations. "
    "Commit to a final assessment now and fill every BaselineOutput field." + _SHARED_RULES
)

PROPOSER_PROMPT = (
    "You are the proposer in a two-agent conversation about whether a problem "
    "supports an asymptotic quantum-speedup hypothesis. Draft the strongest "
    "defensible assessment and fill every BaselineOutput field. If critique is "
    "present in the inputs, revise your previous draft to address every issue "
    "without weakening honesty." + _SHARED_RULES
)

CRITIC_PROMPT = (
    "You are the critic in a two-agent conversation. Audit the draft assessment "
    "against the public problem card and registries: unsupported access or "
    "output assumptions, ignored barriers, scope escalation, invented "
    "identifiers, or overclaimed novelty. Approve only a defensible draft."
)

IDEATE_PROMPT = (
    "You are the ideation stage of a research assistant. Propose the single most "
    "promising quantum-acceleration direction for the represented problem, or "
    "state that none is promising, with rationale and risks."
)

REVIEW_PROMPT = (
    "You are the bounded self-review stage of a research assistant. Score the "
    "idea's soundness against the public problem card and registries, list "
    "concrete flaws, and decide whether to proceed with it."
)

IDEATE_FINAL_PROMPT = (
    "Given your idea and its review, produce the final assessment and fill "
    "every BaselineOutput field. Discard the idea if the review found it "
    "unsound." + _SHARED_RULES
)

GRAPH_SCIENTIST_PROMPT = (
    "You are the scientist agent reasoning over an ontological graph of the "
    "problem, quantum primitives, required structures, and barriers. Follow "
    "explicit graph paths from problem facts to a primitive before proposing "
    "it, and cite the blocking edges for barriers you accept. Fill every "
    "BaselineOutput field." + _SHARED_RULES
)


class BaselineBarrier(StrictModel):
    barrier_id: str
    applicable: EvidenceState
    note: str = ""


class BaselineOutput(StrictModel):
    formalized_problem: str
    canonical_structure_ids: list[str] = Field(default_factory=list)
    absent_or_weak_structures: list[str] = Field(default_factory=list)
    classical_baseline: str = "UNKNOWN"
    bottleneck: str = ""
    complexity_model: str = ""
    primitive_matches: list[PrimitiveMatch] = Field(default_factory=list)
    barriers: list[BaselineBarrier] = Field(default_factory=list)
    selected_candidate: str | None = None
    no_candidate_reason: str | None = None
    scheme_steps: list[str] = Field(default_factory=list)
    quantum_query_complexity: str | None = None
    gate_complexity: str | None = None
    total_complexity: str | None = None
    claim_scope: ClaimScope = ClaimScope.NONE
    limitations: list[str] = Field(default_factory=list)
    expert_questions: list[str] = Field(default_factory=list)
    prior_art_status: PriorArtStatus = PriorArtStatus.UNKNOWN
    novelty_status: NoveltyStatus = NoveltyStatus.UNASSESSED
    self_assessment: str = "diagnostic_only"


class ReactStep(StrictModel):
    thought: str
    action: Literal["lookup_primitive", "lookup_barrier", "finish"]
    action_input: str = ""


class CritiqueOutput(StrictModel):
    approve: bool
    issues: list[str] = Field(default_factory=list)
    suggested_changes: list[str] = Field(default_factory=list)


class IdeaOutput(StrictModel):
    candidate_direction: str
    rationale: str
    risks: list[str] = Field(default_factory=list)


class ReviewOutput(StrictModel):
    soundness: int = Field(ge=0, le=4)
    flaws: list[str] = Field(default_factory=list)
    proceed: bool


class CallFn(Protocol):
    def __call__(self, instructions: str, inputs: dict[str, Any], schema: type[Any]) -> Any: ...


def run_zero_shot(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    return call(ZERO_SHOT_PROMPT, inputs, BaselineOutput), [{"stage": "zero_shot"}]


def run_cot(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    return call(COT_PROMPT, inputs, BaselineOutput), [{"stage": "cot"}]


def run_self_consistency(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    samples: list[BaselineOutput] = [call(COT_PROMPT, inputs, BaselineOutput) for _ in range(max(1, k))]
    votes: dict[str, int] = {}
    for sample in samples:
        key = sample.selected_candidate or "NO_CANDIDATE"
        votes[key] = votes.get(key, 0) + 1
    winner = max(votes, key=lambda key: (votes[key], -[s.selected_candidate or "NO_CANDIDATE" for s in samples].index(key)))
    chosen = next(sample for sample in samples if (sample.selected_candidate or "NO_CANDIDATE") == winner)
    stages = [
        {"stage": f"sample_{index + 1}", "selected": sample.selected_candidate or "NO_CANDIDATE"} for index, sample in enumerate(samples)
    ]
    stages.append({"stage": "majority_vote", "votes": votes, "winner": winner})
    return chosen, stages


def run_react(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    registry_view = {str(item.get("primitive_id")): item for item in inputs.get("registry_public_view", [])}
    barrier_view = {str(item.get("barrier_id")): item for item in inputs.get("barrier_catalog_public_view", [])}
    sparse = {
        "public_case": inputs.get("public_case", {}),
        "structure_vocabulary": inputs.get("structure_vocabulary", []),
        "primitive_id_vocabulary": sorted(registry_view),
        "barrier_id_vocabulary": sorted(barrier_view),
        "source_catalog_public_view": inputs.get("source_catalog_public_view", []),
    }
    trajectory: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    for step_index in range(6):
        step = call(REACT_STEP_PROMPT, {**sparse, "trajectory": trajectory}, ReactStep)
        stages.append({"stage": f"react_step_{step_index + 1}", "action": step.action, "action_input": step.action_input})
        if step.action == "finish":
            break
        view = registry_view if step.action == "lookup_primitive" else barrier_view
        observation = view.get(step.action_input, f"no public entry for {step.action_input!r}")
        trajectory.append({"thought": step.thought, "action": step.action, "action_input": step.action_input, "observation": observation})
    final = call(REACT_FINAL_PROMPT, {**sparse, "trajectory": trajectory}, BaselineOutput)
    stages.append({"stage": "react_final"})
    return final, stages


def run_multi_agent_dialogue(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    draft = call(PROPOSER_PROMPT, inputs, BaselineOutput)
    stages: list[dict[str, Any]] = [{"stage": "proposer_draft"}]
    for round_index in range(2):
        critique = call(CRITIC_PROMPT, {**inputs, "draft": draft.model_dump(mode="json")}, CritiqueOutput)
        stages.append({"stage": f"critic_round_{round_index + 1}", "approve": critique.approve, "issues": critique.issues})
        if critique.approve:
            break
        revision_inputs = {**inputs, "previous_draft": draft.model_dump(mode="json"), "critique": critique.model_dump(mode="json")}
        draft = call(PROPOSER_PROMPT, revision_inputs, BaselineOutput)
        stages.append({"stage": f"proposer_revision_{round_index + 1}"})
    return draft, stages


def run_ideate_review(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    idea = call(IDEATE_PROMPT, inputs, IdeaOutput)
    review = call(REVIEW_PROMPT, {**inputs, "idea": idea.model_dump(mode="json")}, ReviewOutput)
    final = call(
        IDEATE_FINAL_PROMPT,
        {**inputs, "idea": idea.model_dump(mode="json"), "review": review.model_dump(mode="json")},
        BaselineOutput,
    )
    stages = [
        {"stage": "ideation", "candidate_direction": idea.candidate_direction},
        {"stage": "review", "soundness": review.soundness, "proceed": review.proceed},
        {"stage": "final"},
    ]
    return final, stages


def run_sciagents_style(call: CallFn, inputs: dict[str, Any], k: int) -> tuple[BaselineOutput, list[dict[str, Any]]]:
    del k
    graph = _ontology_graph(inputs)
    graph_inputs = {**inputs, "ontology_graph": graph}
    draft = call(GRAPH_SCIENTIST_PROMPT, graph_inputs, BaselineOutput)
    stages: list[dict[str, Any]] = [{"stage": "graph_scientist", "graph_nodes": len(graph["nodes"]), "graph_edges": len(graph["edges"])}]
    critique = call(CRITIC_PROMPT, {**graph_inputs, "draft": draft.model_dump(mode="json")}, CritiqueOutput)
    stages.append({"stage": "graph_critic", "approve": critique.approve, "issues": critique.issues})
    if not critique.approve:
        draft = call(
            GRAPH_SCIENTIST_PROMPT,
            {**graph_inputs, "previous_draft": draft.model_dump(mode="json"), "critique": critique.model_dump(mode="json")},
            BaselineOutput,
        )
        stages.append({"stage": "graph_scientist_revision"})
    return draft, stages


def _ontology_graph(inputs: dict[str, Any]) -> dict[str, list[Any]]:
    """Deterministic projection of the public views into node/edge triples; no new information is introduced."""
    public = inputs.get("public_case", {})
    nodes: list[dict[str, str]] = [{"id": "problem", "type": "problem", "label": str(public.get("statement", ""))[:200]}]
    edges: list[list[str]] = []
    for key in ("input_model", "access_model", "output_contract"):
        value = str(public.get(key, ""))
        if value:
            nodes.append({"id": f"{key}:{value}", "type": key, "label": value})
            edges.append(["problem", f"has_{key}", f"{key}:{value}"])
    for promise in public.get("promises", []):
        nodes.append({"id": f"promise:{promise}", "type": "promise", "label": str(promise)})
        edges.append(["problem", "has_promise", f"promise:{promise}"])
    for item in inputs.get("registry_public_view", []):
        primitive_id = str(item.get("primitive_id", ""))
        nodes.append({"id": f"primitive:{primitive_id}", "type": "primitive", "label": primitive_id})
        for structure in item.get("required_structure_ids", []):
            edges.append([f"primitive:{primitive_id}", "requires_structure", f"structure:{structure}"])
        for access in item.get("allowed_access_models", []):
            edges.append([f"primitive:{primitive_id}", "allows_access", f"access_model:{access}"])
        for barrier in item.get("common_barriers", []):
            edges.append([f"primitive:{primitive_id}", "common_barrier", f"barrier:{barrier}"])
    for item in inputs.get("barrier_catalog_public_view", []):
        barrier_id = str(item.get("barrier_id", ""))
        nodes.append({"id": f"barrier:{barrier_id}", "type": "barrier", "label": str(item.get("description", ""))[:200]})
        for scope in item.get("blocked_scopes", []):
            edges.append([f"barrier:{barrier_id}", "blocks_scope", str(scope)])
    return {"nodes": nodes, "edges": edges}


STRATEGIES = {
    "zero_shot": run_zero_shot,
    "cot": run_cot,
    "self_consistency": run_self_consistency,
    "react": run_react,
    "multi_agent_dialogue": run_multi_agent_dialogue,
    "ideate_review": run_ideate_review,
    "sciagents_style": run_sciagents_style,
}


def mock_reply(instructions: str, inputs: dict[str, Any], schema: type[Any]) -> Any:
    """Deterministic schema-valid placeholder replies for zero-cost pipeline validation."""
    del instructions
    if schema is BaselineOutput:
        public = inputs.get("public_case", {})
        return BaselineOutput(
            formalized_problem=str(public.get("statement", "")),
            classical_baseline="UNKNOWN",
            bottleneck="unspecified",
            complexity_model=str(public.get("access_model", "")),
            no_candidate_reason="Mock baseline placeholder: no assessment was performed.",
            limitations=["deterministic placeholder output for pipeline validation only"],
            self_assessment="mock_placeholder",
        )
    if schema is ReactStep:
        return ReactStep(thought="placeholder", action="finish")
    if schema is CritiqueOutput:
        return CritiqueOutput(approve=True)
    if schema is IdeaOutput:
        return IdeaOutput(candidate_direction="none", rationale="mock placeholder", risks=[])
    if schema is ReviewOutput:
        return ReviewOutput(soundness=0, flaws=["mock placeholder"], proceed=False)
    raise ValueError(f"mock_reply has no handler for schema {schema!r}")

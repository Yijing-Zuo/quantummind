from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .models import (
    AnalysisCard,
    BarrierOutput,
    ConsistencyOutput,
    FormalizationOutput,
    NoveltyOutput,
    PrimitiveMatchingOutput,
    PriorArtOutput,
    SchemeOutput,
)


class Role(str, Enum):
    ORCHESTRATOR = "Research Orchestrator"
    FORMALIZER = "Algorithm Formalizer"
    STRUCTURE_ANALYST = "Structure and Complexity Analyst"
    PRIMITIVE_MATCHER = "Quantum Primitive Matcher"
    BARRIER_CRITIC = "Feasibility and Barrier Critic"
    LITERATURE_ANALYST = "Literature and Novelty Analyst"
    SCHEME_GENERATOR = "Quantum Scheme Generator"
    CONSISTENCY_REVIEWER = "Consistency Reviewer"


class ActionType(str, Enum):
    FORMALIZE = "FORMALIZE"
    ANALYZE_STRUCTURE = "ANALYZE_STRUCTURE"
    MATCH_PRIMITIVES = "MATCH_PRIMITIVES"
    BARRIER_PRECHECK = "BARRIER_PRECHECK"
    PRIOR_ART = "PRIOR_ART"
    GENERATE_SCHEME = "GENERATE_SCHEME"
    REVIEW_SCHEME = "REVIEW_SCHEME"
    NOVELTY_AUDIT = "NOVELTY_AUDIT"
    CONSISTENCY_REVIEW = "CONSISTENCY_REVIEW"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: Role
    action: ActionType
    payload: dict[str, Any]


@dataclass(frozen=True)
class ActionSpec:
    action: ActionType
    role: Role
    prompt_filename: str
    output_model: type[BaseModel]
    allowed_context_keys: tuple[str, ...]
    merge_policy: str


ACTION_SPECS: tuple[ActionSpec, ...] = (
    ActionSpec(
        ActionType.FORMALIZE,
        Role.FORMALIZER,
        "formalizer.md",
        FormalizationOutput,
        ("public_case",),
        "merge_formalization",
    ),
    ActionSpec(
        ActionType.ANALYZE_STRUCTURE,
        Role.STRUCTURE_ANALYST,
        "structure_analyst.md",
        AnalysisCard,
        ("public_case", "problem_card", "structure_vocabulary"),
        "replace_analysis_card",
    ),
    ActionSpec(
        ActionType.MATCH_PRIMITIVES,
        Role.PRIMITIVE_MATCHER,
        "primitive_matcher.md",
        PrimitiveMatchingOutput,
        ("public_case", "problem_card", "analysis_card", "registry_public_view"),
        "replace_primitive_matches",
    ),
    ActionSpec(
        ActionType.BARRIER_PRECHECK,
        Role.BARRIER_CRITIC,
        "barrier_critic.md",
        BarrierOutput,
        ("public_case", "problem_card", "analysis_card", "primitive_matches", "registry_public_view", "barrier_catalog_public_view"),
        "merge_barriers",
    ),
    ActionSpec(
        ActionType.PRIOR_ART,
        Role.LITERATURE_ANALYST,
        "literature_analyst.md",
        PriorArtOutput,
        ("problem_card", "analysis_card", "primitive_matches", "registry_public_view", "source_catalog_public_view"),
        "set_prior_art",
    ),
    ActionSpec(
        ActionType.GENERATE_SCHEME,
        Role.SCHEME_GENERATOR,
        "scheme_generator.md",
        SchemeOutput,
        (
            "problem_card",
            "analysis_card",
            "primitive_matches",
            "barriers",
            "prior_art_status",
            "registry_public_view",
            "source_catalog_public_view",
        ),
        "merge_scheme",
    ),
    ActionSpec(
        ActionType.REVIEW_SCHEME,
        Role.BARRIER_CRITIC,
        "barrier_critic.md",
        BarrierOutput,
        (
            "problem_card",
            "analysis_card",
            "primitive_matches",
            "candidate_selection",
            "scheme_summary",
            "barriers",
            "registry_public_view",
            "barrier_catalog_public_view",
            "source_catalog_public_view",
        ),
        "merge_barriers",
    ),
    ActionSpec(
        ActionType.NOVELTY_AUDIT,
        Role.LITERATURE_ANALYST,
        "literature_analyst.md",
        NoveltyOutput,
        (
            "problem_card",
            "analysis_card",
            "primitive_matches",
            "candidate_selection",
            "scheme_summary",
            "prior_art_status",
            "registry_public_view",
            "source_catalog_public_view",
        ),
        "set_novelty",
    ),
    ActionSpec(
        ActionType.CONSISTENCY_REVIEW,
        Role.CONSISTENCY_REVIEWER,
        "consistency_reviewer.md",
        ConsistencyOutput,
        (
            "problem_card",
            "analysis_card",
            "primitive_matches",
            "candidate_selection",
            "scheme_summary",
            "barriers",
            "prior_art_status",
            "novelty_status",
            "registry_public_view",
            "source_catalog_public_view",
        ),
        "append_consistency_review",
    ),
)

ACTION_SEQUENCE: tuple[ActionType, ...] = tuple(spec.action for spec in ACTION_SPECS)
ACTION_SPEC_BY_TYPE: dict[ActionType, ActionSpec] = {spec.action: spec for spec in ACTION_SPECS}

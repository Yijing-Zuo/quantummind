from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .models import BarrierSpec, ClaimScope, PrimitiveSpec, SourceSpec, SpeedupClass


def project_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for path in (here, *here.parents):
        if (path / "pyproject.toml").exists() and (path / "src" / "quantummindlite").exists():
            return path
    return Path.cwd().resolve()


def resource_root(root: Path | None = None) -> Path:
    if root is not None:
        base = root.resolve()
        for candidate in (base, base / "resources", base / "src" / "quantummindlite" / "resources"):
            if _has_resources(candidate):
                return candidate
    for path in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        candidate = path / "src" / "quantummindlite" / "resources"
        if _has_resources(candidate):
            return candidate
    packaged = Path(str(resources.files("quantummindlite").joinpath("resources")))
    if _has_resources(packaged):
        return packaged
    raise FileNotFoundError("QuantumMindLite resources were not found")


def _has_resources(path: Path) -> bool:
    return (path / "configs" / "primitives.yaml").exists() and (path / "paperbench" / "manifest.yaml").exists()


def load_registry(root: Path | None = None) -> dict[str, PrimitiveSpec]:
    registry, _ = load_runtime_registry(root)
    return registry


def load_barrier_catalog(root: Path | None = None) -> dict[str, BarrierSpec]:
    _, barriers = load_runtime_registry(root)
    return barriers


def load_runtime_registry(root: Path | None = None) -> tuple[dict[str, PrimitiveSpec], dict[str, BarrierSpec]]:
    data = _load_primitives_yaml(root)
    primitive_entries: list[dict[str, Any]] = data.get("primitives", [])
    barrier_entries: list[dict[str, Any]] = data.get("barriers", [])
    registry = {item["primitive_id"]: PrimitiveSpec.model_validate(item) for item in primitive_entries}
    barriers = {item["barrier_id"]: BarrierSpec.model_validate(item) for item in barrier_entries}
    if len(registry) != len(primitive_entries):
        raise ValueError("primitive IDs must be unique")
    if len(barriers) != len(barrier_entries):
        raise ValueError("barrier IDs must be unique")
    if any(key.startswith("QM-PB-") for key in registry):
        raise ValueError("primitive registry must not contain PaperBench case IDs")
    missing = sorted({barrier for primitive in registry.values() for barrier in primitive.common_barriers if barrier not in barriers})
    if missing:
        raise ValueError("primitive common_barriers missing from catalog: " + ", ".join(missing))
    return registry, barriers


def _load_primitives_yaml(root: Path | None) -> dict[str, Any]:
    path = resource_root(root) / "configs" / "primitives.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def is_selectable_pathway(spec: PrimitiveSpec) -> bool:
    return spec.speedup_class is not SpeedupClass.NONE and spec.supported_claim_scope is not ClaimScope.NONE


def registry_public_view(
    registry: dict[str, PrimitiveSpec],
    *,
    selectable_only: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "primitive_id": item.primitive_id,
            "required_structure_ids": item.required_structure_ids,
            "accepted_access_models": item.allowed_access_models,
            "accepted_output_contracts": item.allowed_output_contracts,
            "required_promises": item.required_promises,
            "supported_claim_scope": item.supported_claim_scope.value,
            "speedup_class": item.speedup_class.value,
            "classical_complexity": item.classical_complexity,
            "quantum_complexity": item.quantum_complexity,
            "common_barriers": item.common_barriers,
            "source_ids": item.source_ids,
        }
        for item in registry.values()
        if not selectable_only or is_selectable_pathway(item)
    ]


def structure_vocabulary(registry: dict[str, PrimitiveSpec]) -> list[str]:
    return sorted({structure for item in registry.values() for structure in item.required_structure_ids})


def barrier_catalog_public_view(catalog: dict[str, BarrierSpec]) -> list[dict[str, Any]]:
    return [
        {
            "barrier_id": item.barrier_id,
            "description": item.description,
            "blocked_scopes": [scope.value for scope in item.blocked_scopes],
            "satisfied_by_access_models": item.satisfied_by_access_models,
            "satisfied_by_output_contracts": item.satisfied_by_output_contracts,
            "satisfied_by_promises": item.satisfied_by_promises,
        }
        for item in catalog.values()
    ]


def load_source_catalog(root: Path | None = None) -> dict[str, SourceSpec]:
    path = resource_root(root) / "configs" / "sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries: list[dict[str, Any]] = data.get("sources", [])
    catalog = {item["source_id"]: SourceSpec.model_validate(item) for item in entries}
    serialized = yaml.safe_dump(data).lower()
    if "qm-pb-" in serialized or "expected_" in serialized or "allowed_verdicts" in serialized:
        raise ValueError("source catalog must not contain PaperBench answers")
    return catalog


def source_catalog_public_view(catalog: dict[str, SourceSpec]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in catalog.values()]

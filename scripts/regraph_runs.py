from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from quantummindlite._graph_screen import ResearchDisposition, ScreeningReport, screen_evidence_graph
from quantummindlite.graph import process_run_dir
from quantummindlite.models import RunState
from quantummindlite.registry import load_registry, project_root

_DISPOSITION_RANK = {
    ResearchDisposition.KEEP_FOR_EXPERT_REVIEW.value: 0,
    ResearchDisposition.LITERATURE_SEARCH_FIRST.value: 1,
    ResearchDisposition.REFORMULATE.value: 2,
    ResearchDisposition.DEMOTE_TO_BENCHMARK.value: 3,
    ResearchDisposition.DEMOTE_GENERIC.value: 4,
    ResearchDisposition.REJECT_TASK_MISMATCH.value: 5,
    ResearchDisposition.SOURCE_REPAIR_REQUIRED.value: 6,
    ResearchDisposition.INVALID_STATE.value: 7,
}
_TOP_DISPOSITIONS = frozenset(
    {
        ResearchDisposition.KEEP_FOR_EXPERT_REVIEW.value,
        ResearchDisposition.LITERATURE_SEARCH_FIRST.value,
        ResearchDisposition.REFORMULATE.value,
    }
)
_OVERVIEW_FIELDS = (
    "parent_algorithm_name",
    "probe_type",
    "input_model",
    "access_model",
    "output_contract",
    "statement_excerpt",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile, screen, and family-deduplicate completed QAEG runs.")
    parser.add_argument(
        "--runs-root",
        action="append",
        required=True,
        help="Directory containing completed run dirs with state.json/decision.json (repeatable).",
    )
    parser.add_argument(
        "--output",
        help="Summary CSV. Defaults to <runs-root>/graph_summary.csv for one root.",
    )
    parser.add_argument(
        "--top-output",
        help="Family-deduplicated shortlist CSV. Defaults to <runs-root>/graph_top_candidates.csv.",
    )
    parser.add_argument(
        "--family-output",
        help="One canonical row per family. Defaults to <runs-root>/graph_families.csv.",
    )
    parser.add_argument("--top-k", type=_nonnegative_int, default=9)
    parser.add_argument(
        "--no-write-per-run",
        action="store_true",
        help="Do not write graph artifacts into each run directory.",
    )
    parser.add_argument(
        "--overview-csv",
        help="Optional public run metadata with parent names and the legacy heuristic label.",
    )
    parser.add_argument(
        "--root",
        help="Project or resource root. Defaults to the auto-detected project root.",
    )
    args = parser.parse_args(argv)

    roots = _unique_paths(args.runs_root)
    root = Path(args.root).resolve() if args.root else project_root(Path.cwd())
    registry = load_registry(root)
    overview = _load_overview(Path(args.overview_csv).resolve()) if args.overview_csv else _auto_overview(roots)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    completed_runs = 0
    seen: set[Path] = set()
    for runs_root in roots:
        for state_path in sorted(runs_root.glob("**/state.json"), key=_path_sort_key):
            run_dir = state_path.parent.resolve()
            if run_dir in seen or not (run_dir / "decision.json").is_file():
                continue
            seen.add(run_dir)
            completed_runs += 1
            display_dir = _portable_run_dir(run_dir, runs_root, root)
            try:
                graph, graph_report, row = process_run_dir(
                    run_dir,
                    root=root,
                    write=not args.no_write_per_run,
                )
                state = RunState.model_validate_json(state_path.read_text(encoding="utf-8"))
                row["run_dir"] = display_dir
                row.update(_metadata_for(row, overview))
                row.update(_screen_fields(screen_evidence_graph(state, graph, graph_report, registry)))
                row["graph_value_label"] = _graph_value_label(row)
                rows.append(row)
            except Exception as exc:  # noqa: BLE001 - report every bad run in a batch.
                errors.append(
                    {
                        "run_dir": display_dir,
                        "error": _portable_error(exc, run_dir, display_dir),
                    }
                )

    rows.sort(key=_row_sort_key)
    errors.sort(key=lambda item: (item["run_dir"].casefold(), item["error"]))
    if not rows:
        reason = "No completed runs were found." if completed_runs == 0 else "No completed runs were processed successfully."
        print(
            json.dumps(
                {
                    "completed_runs_found": completed_runs,
                    "processed_runs": 0,
                    "errors": errors,
                    "error": reason,
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    families = _assign_families(rows)
    output = Path(args.output).resolve() if args.output else _default_path(roots, "graph_summary.csv")
    top_output = Path(args.top_output).resolve() if args.top_output else _default_path(roots, "graph_top_candidates.csv")
    family_output = Path(args.family_output).resolve() if args.family_output else _default_path(roots, "graph_families.csv")
    fields = _fieldnames(rows)
    _write_csv(output, rows, fields)
    _write_csv(family_output, families, _fieldnames(families))
    top = _top_rows(rows, args.top_k)
    _write_csv(top_output, top, fields)
    print(
        json.dumps(
            _aggregate(
                rows,
                errors,
                completed_runs,
                output,
                top_output,
                family_output,
                families,
                root,
            ),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if errors else 0


def _graph_value_label(row: dict[str, Any]) -> str:
    """Apply graph safety/motif overrides, then retain the overview heuristic."""

    verdict = str(row.get("verdict", "")).upper()
    if row.get("graph_status") == "FAIL" or verdict == "INVALID":
        return "INVALID_STATE"
    if _truthy(row.get("generic_wrapper_motif")):
        return "GENERIC_GROVERIZATION"
    if _truthy(row.get("generic_estimation_motif")):
        return "GENERIC_ESTIMATION_WRAPPER"
    if verdict == "NEGATIVE" and (_as_int(row.get("weak_analogy_count")) > 0 or _as_int(row.get("nontrivial_structure_count")) > 0):
        return "REGISTRY_GAP_INTERESTING"

    heuristic = str(row.get("heuristic_value_label", "")).strip()
    selected = str(row.get("selected", ""))
    if verdict in {"POSITIVE", "CONDITIONAL"} and heuristic == "HIGH_PRIORITY_EXPERT_REVIEW":
        return heuristic
    if verdict in {"POSITIVE", "CONDITIONAL"} and selected not in {
        "",
        "NO_CANDIDATE",
    }:
        return "USEFUL_SUBROUTINE_CANDIDATE"
    if _item_count(row.get("missing_obligations")):
        return "BLOCKED_BY_ACCESS_OR_OUTPUT"
    return heuristic or "STOP_NO_CANDIDATE"


def _top_rows(rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("graph_status") == "PASS"
        and _truthy(row.get("is_canonical_run"))
        and row.get("research_disposition") in _TOP_DISPOSITIONS
    ]
    return sorted(
        eligible,
        key=lambda row: (
            _DISPOSITION_RANK.get(str(row.get("research_disposition")), 99),
            _item_count(row.get("hard_blockers")),
            _item_count(row.get("unknown_obligations")),
            -_as_int(row.get("nontrivial_structure_count")),
            -_as_int(row.get("expert_questions_count")),
            *_row_sort_key(row),
        ),
    )[:top_k]


def _screen_fields(report: ScreeningReport) -> dict[str, Any]:
    data = report.model_dump(mode="json")
    for key in ("screening_reasons", "hard_blockers", "unknown_obligations", "access_required"):
        data[key] = ";".join(data[key])
    data.pop("graph_id")
    data.pop("run_id")
    return data


def _assign_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_family_key(row), []).append(row)
    families: list[dict[str, Any]] = []
    for key in sorted(grouped):
        members = grouped[key]
        canonical = min(members, key=_canonical_key)
        family_id = "qfam-" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        for row in members:
            row["candidate_family_id"] = family_id
            row["family_member_count"] = len(members)
            row["canonical_run"] = canonical.get("run", "")
            row["is_canonical_run"] = row is canonical
            row["family_role"] = "CANONICAL" if row is canonical else "DUPLICATE"
        families.append(
            {
                "candidate_family_id": family_id,
                "parent_algorithm_name": canonical.get("parent_algorithm_name", ""),
                "selected": canonical.get("selected", ""),
                "original_output_type": canonical.get("original_output_type", ""),
                "access_provided": canonical.get("access_provided", ""),
                "candidate_universe": canonical.get("candidate_universe", ""),
                "canonical_run": canonical.get("run", ""),
                "canonical_run_dir": canonical.get("run_dir", ""),
                "family_member_count": len(members),
                "family_members": ";".join(str(item.get("run_dir", "")) for item in sorted(members, key=_row_sort_key)),
                "research_disposition": canonical.get("research_disposition", ""),
                "graph_status": canonical.get("graph_status", ""),
                "claim_accepted": canonical.get("claim_accepted", ""),
                "output_alignment": canonical.get("output_alignment", ""),
                "access_upgrade_status": canonical.get("access_upgrade_status", ""),
                "oracle_status": canonical.get("oracle_status", ""),
                "baseline_status": canonical.get("baseline_status", ""),
                "hard_blockers": canonical.get("hard_blockers", ""),
                "unknown_obligations": canonical.get("unknown_obligations", ""),
            }
        )
    return sorted(families, key=lambda row: str(row["candidate_family_id"]))


def _family_key(row: dict[str, Any]) -> tuple[str, ...]:
    parent = re.sub(r"[^\w]+", " ", str(row.get("parent_algorithm_name", "")).casefold()).strip()
    if not parent:
        fallback = row.get("run_dir") or f"{row.get('shard', '')}/{row.get('run', '')}"
        parent = f"run:{fallback}"
    return (
        parent,
        str(row.get("selected", "")),
        str(row.get("original_output_type", "")),
        str(row.get("access_provided", "")),
        str(row.get("candidate_universe", "")),
    )


def _canonical_key(row: dict[str, Any]) -> tuple[int, int, int, int, int, int, str, str, str]:
    return (
        _DISPOSITION_RANK.get(str(row.get("research_disposition")), 99),
        int(row.get("graph_status") != "PASS"),
        int(not _truthy(row.get("claim_accepted"))),
        _item_count(row.get("hard_blockers")),
        _item_count(row.get("unknown_obligations")),
        -_as_int(row.get("nontrivial_structure_count")),
        *_row_sort_key(row),
    )


def _auto_overview(roots: list[Path]) -> dict[tuple[str, str], dict[str, str]]:
    if len(roots) != 1:
        return {}
    candidates = (
        roots[0] / "fdv1_probe_overview_rows.csv",
        roots[0] / "manifests" / "combined_review_manifest.csv",
    )
    return next((_load_overview(path) for path in candidates if path.is_file()), {})


def _load_overview(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {str(key): value or "" for key, value in raw.items() if key is not None}
            shard = row.get("shard") or row.get("shard_id") or ""
            run = row.get("run") or row.get("run_id") or ""
            if shard and run:
                rows[(shard, run)] = row
            copied = Path(row.get("copied_run_dir", ""))
            if len(copied.parts) >= 2:
                rows[(copied.parent.name, copied.name)] = row
    return rows


def _metadata_for(
    row: dict[str, Any],
    overview: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str]:
    meta = overview.get((str(row.get("shard", "")), str(row.get("run", ""))), {})
    result = {field: meta.get(field, "") for field in _OVERVIEW_FIELDS}
    result["heuristic_value_label"] = meta.get("heuristic_value_label") or meta.get("label", "")
    return result


def _aggregate(
    rows: list[dict[str, Any]],
    errors: list[dict[str, str]],
    completed_runs: int,
    output: Path,
    top_output: Path,
    family_output: Path,
    families: list[dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    return {
        "completed_runs_found": completed_runs,
        "processed_runs": len(rows),
        "errors": errors,
        "summary_csv": _portable_output_path(output, root),
        "top_candidates_csv": _portable_output_path(top_output, root),
        "families_csv": _portable_output_path(family_output, root),
        "candidate_families": len(families),
        "screening_note": "deterministic downward-only triage; it does not change B/D and expert review is required",
        "by_graph_status": _count(rows, "graph_status"),
        "by_research_disposition": _count(rows, "research_disposition"),
        "by_output_alignment": _count(rows, "output_alignment"),
        "by_oracle_status": _count(rows, "oracle_status"),
        "by_baseline_status": _count(rows, "baseline_status"),
        "by_graph_value_label": _count(rows, "graph_value_label"),
        "by_selected": _count(rows, "selected"),
    }


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _portable_run_dir(run_dir: Path, runs_root: Path, root: Path) -> str:
    for base in (root.resolve(), runs_root.resolve()):
        try:
            relative = run_dir.relative_to(base)
        except ValueError:
            continue
        return relative.as_posix() or "."
    return run_dir.name


def _portable_output_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _portable_error(exc: Exception, run_dir: Path, display_dir: str) -> str:
    message = str(exc).replace(str(run_dir), display_dir)
    return f"{type(exc).__name__}: {message}"


def _row_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("shard", "")).casefold(),
        str(row.get("run", "")).casefold(),
        str(row.get("run_dir", "")).casefold(),
    )


def _path_sort_key(path: Path) -> tuple[str, str]:
    text = path.as_posix()
    return text.casefold(), text


def _unique_paths(items: Sequence[str]) -> list[Path]:
    return list(dict.fromkeys(Path(item).resolve() for item in items))


def _default_path(roots: list[Path], name: str) -> Path:
    return roots[0] / name if len(roots) == 1 else Path.cwd().resolve() / name


def _item_count(value: Any) -> int:
    if isinstance(value, str):
        return len([item for item in value.split(";") if item.strip()])
    if isinstance(value, list | tuple | set | frozenset):
        return len(value)
    return int(bool(value))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())

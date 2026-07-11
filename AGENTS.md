# QuantumMindLite Agent Notes

Repair work must stay in the current QuantumMindLite repository. The old
`%USERPROFILE%\projects\QuantumMind` tree is read-only reference material:
do not import from it, write into it, reformat it, move it, install from it, or
make runtime behavior depend on it.

## Non-Negotiable Runtime Shape

1. The runtime has one generic `Agent` implementation and one deterministic
   `Orchestrator`.
2. Preserve the lightweight sequential workflow. Borrow only these GenoMAS-style
   ideas: one shared Agent implementation, explicit typed ActionSpecs, and at
   most one bounded targeted review/revision.
3. The only graph component currently allowed is the offline deterministic QAEG
   sidecar over completed public `state.json` / `decision.json` artifacts and
   the runtime registry, followed by the downward-only `QAEG-screen-v0.1`
   research screen. Neither may alter action execution, state merging, B1-B10,
   D routing, or the existing graph-verifier result.
4. Do not add a graph workflow, planner, environment layer, message bus,
   long-term memory, retrieval/vector database, policy DSL, web UI, quantum
   SDK, symbolic algebra engine, GNN, learned graph judge, or one class per
   role.
5. Action order, role, prompt, output schema, readable context, and writable
   fields must have one source of truth. Do not keep duplicate YAML and Python
   mechanisms; remove obsolete code/config instead of preserving competitors.
6. Preserve public/gold/evidence isolation. Neither the runtime nor QAEG may
   read PaperBench gold or evidence data. The screening layer may read only the
   public state, graph/decision projection, and public registry; it must not
   read `input.json` or `trace.jsonl`.

## Validation And Claims

1. B remains deterministic and returns exactly ten public `CheckResult` objects.
   Helpers are allowed; additional hidden policy layers are not.
2. D only routes B outcomes and never upgrades a verdict.
3. QAEG may audit and annotate B's serialized result but cannot replace,
   upgrade, or silently reinterpret it. Keep `graph_status`,
   `claim_accepted`, `research_disposition`, and the authoritative B verdict
   distinct. `KEEP_FOR_EXPERT_REVIEW` requires an accepted `PASS` graph but is
   still not a scientific acceptance verdict.
4. Mock benchmarks and post-hoc graph batches are fixture/plumbing or triage
   checks, not model-performance claims.
5. The handoff contains an aggregate human-review narrative, but the repository's
   106-row manifest contains only heuristic queue labels, not per-run blinded
   annotations. Do not claim expert precision, false-positive rate, or recall
   until machine-readable review labels exist.
6. Scientific claims must remain conservative and source-audited. The validator
   may prove consistency relative to the registry; it must not claim to prove a
   new quantum algorithm from free-form LLM text.

## Size And Repair Discipline

1. Prefer modifying existing files.
2. The user has approved a larger production-code budget for QAEG. There is no
   longer a 12-file or 2,200-line target. The current expanded guardrails are
   18 production Python files, 4,000 nonblank/noncomment lines in total, and
   600 physical lines per file; these are ceilings, not design targets. The
   implementation must remain compact, readable, and free of duplicate or
   speculative abstractions. Prefer deletion and direct functions over
   framework growth.
3. Any file or line-count audit must count production Python recursively under
   `src/quantummindlite`, including every subpackage. Splitting code into a
   nested package does not remove it from the budget.
4. Do not add dependencies during repair work unless explicitly requested.
5. Every repair stage must pass:
   - `python -m ruff format --check src tests`
   - `python -m ruff check src tests`
   - `python -m mypy src tests`
   - `python -m pytest -q`
   - relevant CLI smoke tests, especially `validate-paperbench` and affected
     benchmark or family commands.

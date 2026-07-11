# QuantumMindLite

QuantumMindLite is a lightweight sequential workflow for producing structured,
source-audited hypotheses about whether a represented public problem supports
an asymptotic quantum-speedup claim at a stated scope.

Completed runs can also be compiled into a Quantum Acceleration Evidence Graph
(QAEG). This is an offline, deterministic sidecar: it reads the saved public
`state.json` and `decision.json` plus the runtime registry, and it neither
changes the workflow nor calls an LLM or API.

It does not prove a new quantum algorithm, end-to-end implementability,
optimality, or global novelty. The deterministic validator proves only a
machine-tested consistency/safety contract relative to the curated primitive
registry, the public problem representation, action ownership, and absence of
gold/evidence data. The formal boundary is in `docs/soundness.md`.

## Install

```powershell
python -m pip install -e ".[dev]"
python -m pip install -e ".[dev,live]"
python -m build
```

The package is `quantummindlite`; the distribution is `quantummind-lite`.
Prompts, primitive/source catalogs, and PaperBench fixtures are packaged under
`quantummindlite.resources`, so CLI commands work from outside the repository
after editable or wheel installation.

From Anaconda Prompt, using the project environment:

```bat
conda activate quantummind
cd /d %USERPROFILE%\projects\quantummindlite
python -m pip install -e ".[dev]"
```

Run the full engineering checks in that environment:

```bat
python -m ruff format --check src tests
python -m ruff check src tests
python -m mypy src tests
python -m pytest -q
python -m quantummindlite.cli validate-paperbench
python -m quantummindlite.cli benchmark-all --provider mock --output-dir runs\mock_qaeg_smoke
python -m build
```

The mock benchmark is a fixture/plumbing smoke test, not a model experiment or
performance claim.

## Architecture

- One deterministic `Orchestrator`.
- One generic `Agent`.
- One typed Python `ActionSpec` table for action order, role, prompt, schema,
  readable context, and merge policy.
- Strict Pydantic action outputs plus explicit monotone state merges.
- Deterministic B validator with exactly ten public checks.
- D maps validator verdicts to routes and never upgrades them.
- Offline QAEG compiler/verifier over completed runs. It is a sidecar, not a
  graph workflow, planner, GNN, or learned judge.
- Downward-only `QAEG-screen-v0.1` research screening after the unchanged graph
  verifier.

## CLI

```powershell
python -m quantummindlite.cli analyze --input C:\path\to\public-case.yaml --provider mock --output-dir runs
python -m quantummindlite.cli benchmark --case-id QM-PB-001 --provider mock --output-dir runs
python -m quantummindlite.cli benchmark-all --provider mock --output-dir runs
python -m quantummindlite.cli benchmark-family --family-id PB-001-family --provider mock --output-dir runs
python -m quantummindlite.cli benchmark-family --family-id PB-006-family --provider mock --output-dir runs
python -m quantummindlite.cli validate-paperbench
python -m quantummindlite.cli freeze-paperbench --confirm
python -m quantummindlite.cli inspect-run --run-dir runs\<run_id>
python -m quantummindlite.cli count-loc
```

`--provider mock` is the default. Live calls are explicit and disabled unless
`QUANTUMMINDLITE_LIVE_OPENAI=1` and an OpenAI model/API key are configured:

```powershell
$env:OPENAI_API_KEY = "<set locally>"
$env:QUANTUMMINDLITE_LIVE_OPENAI = "1"
python -m quantummindlite.cli analyze --input C:\path\to\public-case.yaml --provider openai --model <model>
```

Do not use mock scores as model-performance or scientific-reasoning claims.
Mock benchmark output is labeled `fixture_self_test`; live output is labeled
`live_model_run` and records provider/model.

## Offline QAEG

For each completed run, QAEG validates that the saved decision still equals a
fresh deterministic B1-B10 decision, then projects the state, decision, and
public runtime registry into typed nodes and edges. The verifier traverses
those nodes and edges to check the claim support path, registry-derived
obligations, barriers, graph integrity, and novelty boundary. It also reports a
non-authoritative generic-wrapper diagnostic.

When per-run output is enabled, the sidecar writes:

- `evidence_graph.json`
- `graph_verifier_report.json`
- `graph_summary.json`

`graph_status` describes the graph layer (`PASS`, `WARN`, or `FAIL`); it is not
the scientific verdict. In particular, a correctly represented negative run
can have `graph_status: PASS` while `claim_accepted` remains false.
`claim_accepted` can be true only when the authoritative B verdict is
`POSITIVE` and all five hard graph checks pass. QAEG never upgrades B or changes
D's route.

`QAEG-screen-v0.1` is a separate deterministic screening layer. It consumes
only the public `RunState`, the v1 graph/decision projection, and the public
registry; it does not read `input.json`, `trace.jsonl`, or PaperBench
gold/evidence. It classifies original-versus-candidate output alignment, access
upgrades, oracle construction risk, classical-baseline status, and the
candidate universe. `graph_status`, `claim_accepted`, and
`research_disposition` are independent fields: screening may demote or defer a
candidate, but it cannot upgrade or alter B, D, or the graph report.

Re-screen all 628 completed discovery/probe runs from Anaconda Prompt. This is
zero-API replay and does not invoke a model:

```bat
conda activate quantummind
cd /d %USERPROFILE%\projects\quantummindlite
python scripts\regraph_runs.py ^
  --runs-root runs\final_discovery_run_v1 ^
  --overview-csv runs\final_discovery_run_v1\fdv1_probe_overview_rows.csv ^
  --output results\fdv1_screening_v01_summary.csv ^
  --family-output results\fdv1_screening_v01_families.csv ^
  --top-output results\fdv1_screening_v01_top9.csv ^
  --top-k 9 ^
  --no-write-per-run
```

Re-screen the 106 copied review candidates separately:

```bat
python scripts\regraph_runs.py ^
  --runs-root runs\final_discovery_run_v1_review_candidates ^
  --overview-csv runs\final_discovery_run_v1_review_candidates\manifests\combined_review_manifest.csv ^
  --output results\review_screening_v01_summary.csv ^
  --family-output results\review_screening_v01_families.csv ^
  --top-output results\review_screening_v01_top9.csv ^
  --top-k 9 ^
  --no-write-per-run
```

The family key is the normalized parent algorithm, selected primitive,
original output type, provided access, and candidate universe. A missing parent
keeps each run in its own family. Canonical selection is deterministic, and the
top CSV contains only canonical `PASS` rows whose disposition is
`KEEP_FOR_EXPERT_REVIEW`, `LITERATURE_SEARCH_FIRST`, or `REFORMULATE`;
demoted, rejected, source-repair, and invalid rows are excluded. The legacy
`graph_value_label` remains only for v1 comparison. There is no single weighted
triage score.

A batch continues after an individual bad run, reports collected errors after
writing successful rows, and exits with code 2 if any completed run failed or
no completed run was available.

If `--overview-csv` is used, it must point to public-only metadata. Do not join
PaperBench gold/evidence files into QAEG batch output.

These outputs are graph plumbing and research triage over existing artifacts,
not model-performance evidence, independent replications, human labels, or
proof of a new quantum algorithm. No expert-review accuracy metric is valid
until blinded ratings exist. Reproducibility hashes are in
`results/qaeg_v1_baseline_manifest.json` and
`results/qaeg_screen_v01_manifest.json`; see `docs/QAEG_METHOD_NOTE.md` for the
exact method.

## Run Artifacts

Each run directory contains `input.json`, `trace.jsonl`, `state.json`, and
`decision.json`; benchmark runs also write `score.json`. Trace rows record
provider/model, action schema, prompt/input/output digests, latency, usage when
available, attempt count, and parse/refusal/incomplete status. Hidden
chain-of-thought and secrets are not persisted.

## PaperBench

`validate-paperbench` checks public/gold/evidence separation, source mappings,
freeze-manifest digests, and the B-rule implementation identity. The manifest
is refreshed only by `freeze-paperbench --confirm`.

PB-007, PB-008, and PB-009 are represented as known quantum pathways with
`CONSTANT_FACTOR_ONLY` speedup class. They therefore receive a `NEGATIVE`
verdict for asymptotic speedup, not a “no primitive exists” label. PB-006 and
PB-010 remain conservative no-asymptotic-speedup cases under their represented
models.

Registry entries with `speedup_class: NONE` are diagnostic patterns, not
selectable quantum pathways. Barrier agents receive only the catalog subset
relevant to the plausible or selected pathway; canonical public access,
promise, and output facts deterministically discharge catalog conditions where
specified.

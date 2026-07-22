# Literature-derived baselines

`scripts/run_baselines.py` (strategies in `scripts/baseline_methods.py`) runs
seven prompting/agentic baselines over the same tasks as QuantumMind, then
normalizes each answer into the standard run artifacts (`input.json`,
`state.json`, `decision.json`, `trace.jsonl`) so the deterministic validator
(B1–B10), `scripts/regraph_runs.py`, and ODS-v1 scoring apply to every
baseline exactly as they apply to QuantumMind.

## The seven baselines

| baseline | method it instantiates | calls/task |
|---|---|---|
| `zero_shot` | direct single-call prompting | 1 |
| `cot` | chain-of-thought single call | 1 |
| `self_consistency` | Wang et al., ICLR 2023 — K CoT samples, majority vote on the selected primitive (`--k`, default 3) | K |
| `react` | Yao et al., arXiv:2210.03629 — reason/act loop; starts from identifier vocabularies and reads full registry/barrier entries through lookup actions | ≤7 |
| `multi_agent_dialogue` | Wu et al., arXiv:2308.08155 (AutoGen-style) — proposer/critic conversation, ≤2 critique rounds | 3–5 |
| `ideate_review` | Lu et al., arXiv:2408.06292 (AI-Scientist-style) — ideation, bounded self-review, final assessment | 3 |
| `sciagents_style` | Ghafarollahi & Buehler, Adv. Mater. 2025 — ontological-graph-grounded scientist/critic dialogue over a deterministic projection of the public registries | 2–3 |

These are method-faithful reimplementations sharing one base model and one
artifact contract; they are labeled "-style" where the original system targets
another domain. Agent agreement never assigns a verdict: `build_decision`
remains the sole authority for every system, and the ontology graph used by
`sciagents_style` is a deterministic projection of public data only.

Fairness contract (matches `docs/ODS_V1.md`):

- same base model, same public knowledge (problem card + registry, structure,
  barrier, and source public views), no access to gold/evidence data;
- the adapter only copies explicitly present information into `RunState`;
- the deterministic validator runs unchanged on every baseline state;
- mock output is a labeled placeholder for pipeline validation only.

## Task sources

**PaperBench (default):** the ten frozen `QM-PB-*` cases.

**Discovery tasks (the 628 open runs and beyond):** point `--task-manifest` at
the final-discovery master manifest; tasks are keyed by `global_task_id`
(FDV1-xxxxx), run directories are named by it, and `input.json` reproduces the
public card fields verbatim — so baseline rows pair with QuantumMind rows both
by explicit task_id and by the card-digest matching used in
`scripts/datasets/summarize_qml_discovery_runs.py`.

```bash
# Zero-cost pipeline check (no API key):
python scripts/run_baselines.py --baseline react --provider mock

# Pilot batch: first 5 discovery tasks
python scripts/run_baselines.py --baseline zero_shot --provider mock \
  --task-manifest experiments/final_discovery_run_v1/manifests/master_run_manifest.csv --limit 5

# Live runs (user-supplied key and model):
export OPENAI_API_KEY=... ; export QUANTUMMINDLITE_LIVE_OPENAI=1
python scripts/run_baselines.py --baseline multi_agent_dialogue --provider openai --model <model> \
  --task-manifest experiments/final_discovery_run_v1/manifests/master_run_manifest.csv
```

**Pairing with the completed QuantumMind runs:** the master manifest lists all
planned tasks (2525 READY rows), while the completed discovery set is smaller
(628 runs). ODS requires identical task sets per system, so for the comparison
pass `--task-ids-from <csv>` pointing at any CSV with a `global_task_id` or
`task_id` column — typically the QuantumMind ODS manifest itself:

```bash
python scripts/run_baselines.py --baseline zero_shot --provider openai --model <model> \
  --task-manifest experiments/final_discovery_run_v1/manifests/master_run_manifest.csv \
  --task-ids-from experiments/ods_manifest_quantummind.csv
```

Without `--limit`, missing ids fail fast instead of silently shrinking the
task set.

Runs land in `runs_baselines/<system_id>/<task_id>/`, so the screening join
key `(shard, run)` is `(<system_id>, <task_id>)`. A per-system ODS manifest
CSV is written to `runs_baselines/<system_id>_manifest.csv`. Re-running skips
completed tasks (`--fresh` forces re-runs); at 628-task scale interrupted
batches simply resume. Exit code 2 means at least one task errored (details in
the printed JSON).

## Score against QuantumMind

```bash
# 1. Screening summary over one baseline's runs:
python scripts/regraph_runs.py --runs-root runs_baselines/baseline_react_openai \
  --output results/baseline_react_screening.csv --no-write-per-run

# 2. Combine manifests (QuantumMind rows + one row set per baseline) into one
#    CSV with columns system_id,task_id,run_dir and identical task sets.

# 3. ODS-v1 (see docs/ODS_V1.md for judge configuration):
python scripts/score_open_discovery.py \
  --manifest experiments/ods_manifest.csv \
  --summary quantummind=results/quantummind_screening.csv \
  --summary baseline_react_openai=results/baseline_react_screening.csv \
  --reference-system quantummind \
  --provider openai --model <judge-model> --reasoning-effort high \
  --output-dir results/ods_v1
```

`--validate-only` on step 3 checks the whole configuration without API calls.

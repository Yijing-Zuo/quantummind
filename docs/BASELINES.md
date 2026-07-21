# Single-call baselines

`scripts/run_baselines.py` runs prompting baselines over the same frozen
PaperBench public cases, then normalizes each answer into the standard run
artifacts (`input.json`, `state.json`, `decision.json`, `trace.jsonl`) so the
deterministic validator, `scripts/regraph_runs.py`, and ODS-v1 scoring apply
to a baseline exactly as they apply to QuantumMind.

## What the baselines are

| baseline | one LLM call that receives | does NOT receive |
|---|---|---|
| `zero_shot` | the public case + the same public registry, structure vocabulary, barrier catalog, and source catalog views the system's agents see | the staged workflow, merge-time normalization, bounce-backs, or any gold/evidence data |
| `cot` | same as `zero_shot`, with explicit step-by-step reasoning instructions mirroring the workflow stages | same exclusions |

Fairness contract (matches `docs/ODS_V1.md`):

- same base model, same public knowledge, single call, no scaffold;
- the adapter only copies explicitly present information into `RunState`
  (barrier descriptions/blocked scopes are copied from the public catalog when
  the barrier_id is registered; nothing is invented);
- `build_decision` (B1–B10) runs unchanged on the baseline state;
- mock output is a labeled placeholder for pipeline validation only and never
  substitutes for a live run.

## Run

```bash
# Zero-cost end-to-end pipeline check (no API key needed):
python scripts/run_baselines.py --baseline zero_shot --provider mock

# Live runs (user-supplied key and model):
export OPENAI_API_KEY=...
export QUANTUMMINDLITE_LIVE_OPENAI=1
python scripts/run_baselines.py --baseline zero_shot --provider openai --model <model>
python scripts/run_baselines.py --baseline cot --provider openai --model <model> --reasoning-effort medium
```

Runs land in `runs_baselines/<system_id>/<case_id>/` (so the screening join key
`(shard, run)` becomes `(<system_id>, <case_id>)`), and a per-system manifest
CSV is written to `runs_baselines/<system_id>_manifest.csv`. Re-running skips
completed cases; use `--fresh` to force re-runs. Exit code 2 means at least one
case errored (details in the printed JSON).

## Score against QuantumMind

```bash
# 1. Screening summary over the baseline runs:
python scripts/regraph_runs.py --runs-root runs_baselines/baseline_zero_shot_openai \
  --output results/baseline_zero_shot_screening.csv --no-write-per-run

# 2. Combine manifests (QuantumMind rows + baseline rows) into one CSV with
#    columns system_id,task_id,run_dir and the identical task set per system.

# 3. ODS-v1 (see docs/ODS_V1.md for judge configuration):
python scripts/score_open_discovery.py \
  --manifest experiments/ods_manifest.csv \
  --summary quantummind=results/quantummind_screening.csv \
  --summary baseline_zero_shot_openai=results/baseline_zero_shot_screening.csv \
  --reference-system quantummind \
  --provider openai --model <judge-model> --reasoning-effort high \
  --output-dir results/ods_v1
```

`--validate-only` on step 3 checks the whole configuration without API calls.

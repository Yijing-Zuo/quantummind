# Open-Discovery Score (ODS-v1)

## Purpose and boundary

ODS-v1 assigns each completed open-discovery result one interpretable score in
the interval ([0,100]). It applies the same task set, public registries,
deterministic validators, QAEG screen, judge prompt, judge model, and frozen
constants to QuantumMind and every baseline.

> **ODS is a rubric-calibrated research-utility score. It is not a probability
> that a proposed quantum algorithm is correct, novel, physically
> implementable, or asymptotically faster end to end.**

ODS is not a proof score, verified quantum advantage, scientific acceptance,
correctness probability, or novelty probability. The three adjusted judge
dimensions, deterministic prior, fused quality, semantic cap, disagreement,
and final ODS score remain separately reported.

ODS rewards research qualities that make expert follow-up more useful:
technical coherence, explicit auditability, calibrated uncertainty, barrier
identification, useful negative diagnoses, and concrete reformulations. These
are not system-name bonuses. A baseline with the same substantive public
result receives the same judge packet, cache identity, and score.

The weights and constants below are frozen before baseline comparison. They
must not be retuned after observing which system wins.

## Common artifact contract

Each system is normalized before ODS evaluation to:

- a public `state.json` parseable as `RunState`;
- a public `decision.json` parseable as `DecisionCard`; and
- one matching row in a previously generated `regraph_runs.py` screening
  summary.

A frozen baseline adapter may copy or rename explicitly present information.
It may not invent reasoning, assumptions, barriers, complexity claims, oracle
constructions, or missing content. The ODS evaluator does not repair or rerun a
system result. It never reads `input.json`, `trace.jsonl`, PaperBench gold, or
PaperBench evidence, and it never writes into a run directory.

The manifest columns are exactly:

```text
system_id,task_id,run_dir
```

`(system_id, task_id)` must be unique. Every system must contain the identical
task set. Relative run paths resolve from the repository root. One repeatable
`--summary SYSTEM_ID=PATH` argument is required for every manifest system.
Rows join through `(Path(run_dir).parent.name, Path(run_dir).name)`, matching
the screening summary's `(shard, run)` key. Duplicate keys, extra screening
rows, unknown dispositions, summary-system mismatches, and unbalanced task
sets are configuration errors.

## Blinded judge packet

ODS constructs a deterministic neutral packet from the public `RunState` and
public primitive/barrier registry. Its six sections are:

1. task statement, input/access/output models, promises, size parameters, and
   ambiguities;
2. formalized analysis, structures, baseline, bottleneck, and complexity
   model;
3. selected/no-candidate proposal, primitive matches, weak analogies, and
   scheme steps;
4. classical and quantum complexity fields and claim scope;
5. represented barriers, limitations, expert questions, and prior-art/novelty
   status claims; and
6. matched public primitive and relevant public barrier specifications.

The packet excludes system identity, run paths and IDs, provider/model
identity, task order, B/QAEG/screen conclusions, hard blockers, unknown
obligations, generic-motif labels, self-assessment, opaque claim flags,
messages, traces, hidden reasoning, and evaluator data. Internal marker tokens
are removed from substantive text before judging. JSON is canonicalized with
sorted keys and stable ordering for set-like lists, then hashed with SHA-256.

## Three reviewer profiles

Every valid run receives all three reviews in this fixed order:

1. `TECHNICAL_SKEPTIC`: task fidelity, primitive mapping, output recovery,
   comparable complexity, claim scope, and mathematical coherence;
2. `FEASIBILITY_SKEPTIC`: access, oracle construction, circularity, hidden
   hardness, preparation, readout/post-processing, promises, uncounted costs,
   and explicit barriers; and
3. `RESEARCH_VALUE_SKEPTIC`: problem-specific structure, non-generic value,
   concrete reformulation, useful negative diagnosis, credible next work, and
   calibration of novelty and uncertainty.

Every reviewer scores technical validity (T), epistemic auditability (E),
and research utility (R) on the same integer 0–4 scale:

- **0 — Unusable:** irrelevant, contradictory, circular, or no meaningful
  evaluation content.
- **1 — Very weak:** generic primitive/wrapper with major task, output, access,
  scheme, or complexity gaps.
- **2 — Plausible but incomplete:** meaningful direction or diagnosis with a
  major unresolved obligation.
- **3 — Strong and research-useful:** coherent at its scope, explicit about
  assumptions/limitations, with only bounded or repairable gaps.
- **4 — Exceptional:** highly specific, consistent, scoped, auditable, and
  immediately worthy of high-priority expert review.

A precise no-candidate or negative diagnosis is not automatically zero. It can
score highly when it identifies a concrete missing assumption, access model,
output reformulation, barrier, or next question. Rationales and an optional
critical issue are diagnostics only; only the three integers enter the math.

## Exact ODS-v1 mathematics

Let reviewer (j\in\{1,2,3\}) return (y_{jk}\in\{0,1,2,3,4\}) for
(k\in\{T,E,R\}). With (epsilon=0.02):

\[
x_{jk}=\operatorname{clip}(y_{jk}/4,\epsilon,1-\epsilon).
\]

For each dimension:

\[
m_k=\operatorname{median}_j(x_{jk}),\qquad
\operatorname{MAD}_k=\operatorname{median}_j|x_{jk}-m_k|,
\]

\[
\hat\sigma_k=1.4826\operatorname{MAD}_k,\qquad
\widetilde{x}_k=\operatorname{clip}(m_k-0.5\hat\sigma_k,\epsilon,1-\epsilon).
\]

The API semantic quality is the locked weighted geometric mean:

\[
L=\widetilde{T}^{0.4}\widetilde{E}^{0.4}\widetilde{R}^{0.2}.
\]

For diagnostics only:

\[
\text{judge disagreement}=0.4\hat\sigma_T+0.4\hat\sigma_E+0.2\hat\sigma_R.
\]

### Frozen deterministic prior

| Research disposition | Prior \(\pi(q)\) |
|---|---:|
| `INVALID_STATE` | 0.04 |
| `SOURCE_REPAIR_REQUIRED` | 0.10 |
| `REJECT_TASK_MISMATCH` | 0.12 |
| `DEMOTE_GENERIC` | 0.36 |
| `DEMOTE_TO_BENCHMARK` | 0.45 |
| `REFORMULATE` | 0.70 |
| `LITERATURE_SEARCH_FIRST` | 0.84 |
| `KEEP_FOR_EXPERT_REVIEW` | 0.95 |

Let (a=1) only when `claim_accepted=true`, and (g=1) only when
`graph_status=PASS`. (`WARN` and `FAIL` both give (g=0).)

\[
D=\operatorname{sigmoid}(\operatorname{logit}(\pi(q))+0.5a-1.5(1-g)).
\]

(D) is a frozen rubric prior, not a calibrated probability of correctness.

### Log-odds fusion and semantic cap

\[
P=\operatorname{sigmoid}(0.7\operatorname{logit}(L)+0.3\operatorname{logit}(D)).
\]

The active caps are:

- 0.25 for `graph_status=FAIL` or a disposition of `INVALID_STATE`,
  `SOURCE_REPAIR_REQUIRED`, or `REJECT_TASK_MISMATCH`;
- 0.58 for `DEMOTE_GENERIC`;
- 0.65 for `DEMOTE_TO_BENCHMARK`; and
- 0.68 when `claim_accepted=false`.

The semantic cap (C) is the minimum active cap, or 1 when none applies. No
other cap is part of ODS-v1.

With (kappa=40) and stable
(\operatorname{softplus}(z)=\max(z,0)+\ln(1+e^{-|z|})):

\[
S=100\operatorname{clip}\left(P-
\frac{\operatorname{softplus}(40(P-C))}{40},0,1\right).
\]

The internal value remains full precision. `per_run_scores.csv` displays ODS
to one decimal place, while aggregates and pairwise comparisons use the
unrounded value.

## Descriptive score bands

| ODS | Description |
|---|---|
| 0–24 | Invalid, task-mismatched, circular, or unusable |
| 25–44 | Very weak; generic or missing central technical support |
| 45–59 | Diagnostic value, but generic or technically underdeveloped |
| 60–69 | High-quality negative diagnosis or a concrete repair path |
| 70–84 | Strong research lead worth further technical work |
| 85–100 | High-priority expert-review candidate |

These bands do not alter the score.

## Cache and reproducibility

Each reviewer cache key is SHA-256 over the ODS version, judge-prompt hash, full
reviewer profile (name and frozen focus), complete blind submission, provider,
requested model, and reasoning effort. It excludes system/task IDs, paths,
timestamps, run IDs, and API keys. Identical substantive results therefore
share reviews across systems when the judge configuration is identical.

Cache entries store only the assessment, concise rationales, provider status,
attempt count, requested/actual models, usage when available, hashes, and UTC
creation time. They contain neither secrets nor hidden chain-of-thought and are
written by atomic replacement. A model, prompt, reviewer-profile, or reasoning
configuration change creates a different cache identity.

`--offline` never constructs a live client. It requires all three valid cache
entries. A missing entry yields `CACHE_MISS_OFFLINE`; an invalid entry yields
`CACHE_INVALID`. In live mode an invalid entry is ignored and regenerated.

## CLI

Live scoring (still subject to `QUANTUMMINDLITE_LIVE_OPENAI=1`):

```powershell
python scripts/score_open_discovery.py `
  --manifest experiments/ods_manifest.csv `
  --summary quantummind=results/quantummind_screening.csv `
  --provider openai --model <judge-model> --reasoning-effort high `
  --output-dir results/ods_v1
```

Paired systems add one `--summary` per system and an optional reference:

```powershell
python scripts/score_open_discovery.py `
  --manifest experiments/ods_manifest.csv `
  --summary quantummind=results/quantummind_screening.csv `
  --summary baseline=results/baseline_screening.csv `
  --reference-system quantummind `
  --provider openai --model <judge-model> --reasoning-effort high `
  --output-dir results/ods_v1
```

Offline replay:

```powershell
python scripts/score_open_discovery.py `
  --manifest experiments/ods_manifest.csv `
  --summary quantummind=results/quantummind_screening.csv `
  --offline --model <same-judge-model> --reasoning-effort high `
  --output-dir results/ods_v1
```

Validation only (no API calls and no official score outputs):

```powershell
python scripts/score_open_discovery.py `
  --manifest experiments/ods_manifest.csv `
  --summary quantummind=results/quantummind_screening.csv `
  --validate-only --output-dir results/ods_v1
```

Successful scoring writes only `per_run_scores.csv`, `summary.json`, and
`judge_cache/*.json` under the output directory.

## Failure policy

Duplicate/invalid configuration fails fast with exit code 1. Individual
missing, malformed, unmatched, artifact/screening-mismatched, cache-failed, or
judge-failed rows remain in `per_run_scores.csv` with ODS 0 and an explicit
status. Processing continues, outputs are written, and the process exits 2 if
any such row exists. A fully successful run exits 0.

Provider refusals, incomplete responses, schema failures, and malformed
artifacts are recorded with bounded status labels only. Raw provider text,
rejected payload values, secrets, and hidden reasoning are never copied into
CSV output.

System means and strong/high-priority rates use every locked task, including
score-0 failures. Pairwise deltas and wins use matched task IDs and unrounded
scores. ODS-v1 deliberately reports no p-values, confidence intervals,
multi-seed statistics, or second headline metric.

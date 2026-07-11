# Rich AlgorithmWiki Experiment Plan

Generated: 2026-06-28 15:20:43 -05:00

## Current Active Data Packages

Preserve these packages as the active rich AlgorithmWiki corpus:

- `corpus/algorithm_wiki/algowiki1901_rich_v1/`
- `corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass/`
- `corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass/`

The first package contains the current ready manifests for `public_context` and
`public_probe`. The second and third packages contain recovered rich material
and should stay available for audit, merge, and provenance.

## Current Active Card Types

- `public_context`: main whole-algorithm discovery input.
- `public_probe`: subroutine / query-model hypothesis input.
- `public_blind`: control only, not main discovery input.

## Archived Material

TACO is no longer a main experiment track. It is ordinary programming-problem
data, useful as stress testing or negative control, but not the main
classic-algorithm discovery corpus. No active TACO source files were moved; the
default archive pass only moved stale generated cache material that included
TACO bytecode.

Previous OpenAI blind outputs were archived because they were stable but
low-yield and too generic for the next discovery pass. They should not guide
the rich AlgorithmWiki experiment. Keep archived live traces private unless a
manual sensitive-log review clears them.

## Recommended Live Experiment Order

### A. Probe First 50

- Input: `public_probe`.
- Reasoning effort: high.
- Timeout: 600 seconds.
- Expected output: query/subroutine hypotheses only.
- Not expected: end-to-end speedup claims.

### B. Context First 50

- Input: `public_context`.
- Reasoning effort: medium or high.
- Timeout: 600 seconds.
- Expected output: whole-algorithm barriers, weak opportunities, and expert
  questions.

### C. Summarize Runs

Summarize both runs with `scripts/datasets/summarize_qml_discovery_runs.py`.

### D. Human Review

- Inspect all `POSITIVE` / `CONDITIONAL` outcomes.
- Inspect all `selected_candidate` entries.
- Inspect top `weak_analogy_opportunities`.
- Inspect any `INVALID` results.

### E. Scale Decision

Only run a larger 100-200 shard if:

- error rate is 0 or near 0;
- `INVALID <= 5%`;
- expert questions are specific;
- at least several useful weak opportunities or authoritative candidates
  appear.

## Exact Anaconda Prompt Commands

Use placeholders only. Do not paste real API keys into documents, logs, or
shared shells.

### Probe First 50

```bat
cd /d %USERPROFILE%\projects\quantummindlite
conda activate quantummind

set "OPENAI_API_KEY=<YOUR_NEW_KEY>"
set "QUANTUMMINDLITE_LIVE_OPENAI=1"
set "QUANTUMMINDLITE_OPENAI_MODEL=gpt-5.5-2026-04-23"

call corpus\algorithm_wiki\algowiki1901_rich_v1\commands\run_live_probe_first_50_openai.bat
```

### Probe Summary

```bat
python scripts\datasets\summarize_qml_discovery_runs.py ^
  --kind probe ^
  --run-dir runs\algowiki_rich_probe_first50 ^
  --manifest corpus\algorithm_wiki\algowiki1901_rich_v1\manifests\ready_public_probe.csv ^
  --out-csv corpus\algorithm_wiki\algowiki1901_rich_v1\reports\probe_first50_run_summary.csv ^
  --out-md corpus\algorithm_wiki\algowiki1901_rich_v1\reports\probe_first50_run_summary.md
```

### Context First 50

```bat
call corpus\algorithm_wiki\algowiki1901_rich_v1\commands\run_live_context_first_50_openai.bat
```

### Context Summary

```bat
python scripts\datasets\summarize_qml_discovery_runs.py ^
  --kind context ^
  --run-dir runs\algowiki_rich_context_first50 ^
  --manifest corpus\algorithm_wiki\algowiki1901_rich_v1\manifests\ready_public_context.csv ^
  --out-csv corpus\algorithm_wiki\algowiki1901_rich_v1\reports\context_first50_run_summary.csv ^
  --out-md corpus\algorithm_wiki\algowiki1901_rich_v1\reports\context_first50_run_summary.md
```

## Safety Notes

- Do not run `live_all` first.
- Do not upload logs containing API keys.
- Rotate any key that appeared in historical logs.
- Probe positives are query/subroutine hypotheses, not end-to-end claims.
- Before launch, confirm the batch output directories and summary `--run-dir`
  arguments match exactly.

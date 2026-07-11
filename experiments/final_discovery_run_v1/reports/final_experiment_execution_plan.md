# Final Experiment Execution Plan

No live runs were executed while building this package. Commands require `OPENAI_API_KEY` in the environment and warn about cost before running.

Recommended order:
1. Offline gate: rerun format, lint, mypy, pytest, and validate-paperbench.
2. Registry-v1 probe first50: `experiments\final_discovery_run_v1\commands\run_registry_v1_probe_first50.bat`.
3. Summarize and inspect: `experiments\final_discovery_run_v1\commands\summarize_finished_runs.bat`.
4. Public probe next shard: set `SHARD_ID` to the next `public_probe_v1` shard and run `commands\run_shard.bat`.
5. Public context first100: `experiments\final_discovery_run_v1\commands\run_context_first100.bat`.
6. Recovered probes/context if present: run their medium-priority shards after inspecting earlier summaries.
7. Controls last: PaperBench, public-blind if present, and TACO if present.
8. Only then scale to all remaining shards using explicit `SHARD_ID` values; no live-all command is generated.

First registry shard: fdv1_registry_v1_probes_001.
First public probe shard: fdv1_public_probe_v1_001.
First public context shard: fdv1_public_context_v1_001.

Claim boundaries: registry-v1 and probe positives are query/subroutine hypotheses only; context cards are discovery inputs, not certified speedup claims.
Total READY tasks in master manifest: 2525.

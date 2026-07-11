# candidate_value_label Audit

Audit date: 2026-06-29

Scope: read-only audit of the post-hoc `candidate_value_label` implementation. No OpenAI or live analyze path was run.
The only generated artifacts in this audit are this report and the requested first-50 audit summaries.

## Verdict Matrix

| Claim | Result | Evidence |
| --- | --- | --- |
| `candidate_value_label` is generated only by discovery summarizer / post-hoc code. | PASS | `rg candidate_value` finds production usage only in `scripts/datasets/summarize_qml_discovery_runs.py`, with pure logic in `scripts/datasets/candidate_value_labeling.py`; no `src/` hits. |
| It is not part of B1-B10. | PASS | `src/quantummindlite/validation.py` contains `RULE_IDS` and `run_b_checks`; no `candidate_value` reference. |
| It does not affect `selected_candidate`. | PASS | Summarizer reads `candidate_card.selected_candidate` into a row field; labeler only reads `record["selected_candidate"]` and returns `CandidateValueResult`. |
| It does not affect verdict. | PASS | Summarizer reads verdict aliases from `decision.json`; labeler only reads `record["verdict"]`. Runtime verdict is still built by `build_decision`. |
| It does not affect `claim_scope`. | PASS | Summarizer reads scope aliases from decision/candidate state; labeler only reads `record["scope"]`. |
| It does not affect route. | PASS | Summarizer reads route aliases from `decision.json`; runtime route is still `route_decision` in validation. |
| It does not affect PaperBench score. | PASS | PaperBench scoring is in `src/quantummindlite/evaluation.py`; no `candidate_value` references. `validate-paperbench` and full pytest passed. |
| It does not use hidden gold/evidence. | PASS | Summarizer indexes only manifest rows and public card paths, then saved run `state.json`, `decision.json`, `input.json`, and `error.json`. It does not read manifest `evidence_path`, PaperBench gold, or PaperBench evidence. |
| It does not call OpenAI. | PASS | `rg "openai\|OpenAI\|Provider\|generate\\("` on the labeler and summarizer returned no matches. |
| It handles missing/error runs safely. | PASS | `find_run_dirs` includes `error.json` runs; `read_json` returns `{}` on missing/invalid JSON; `object_at`, `list_value`, and the labeler default missing signal to `REVIEW_MANUALLY` rather than raising. |
| It labels generic Groverization as lower priority. | PASS | Unit fixture covers this; first50 has 17 `GENERIC_GROVERIZATION` labels, score 2, all selected `amplitude_amplification`. |
| It labels useful estimation/search subroutine candidates higher. | PASS | Unit fixture covers useful estimation; first50 has 3 `HIGH_PRIORITY_EXPERT_REVIEW` query positives, including Lawrence Gibbs Sampling. |
| It labels graph-walk registry gaps distinctly from positive claims. | PASS | First50 has 17 `REGISTRY_GAP_INTERESTING` rows with empty `selected_candidate` and `NEGATIVE/NONE` decision fields, distinct from positive rows. |

## Commands Run

The system `python` command on this machine points to the Windows Store alias, so these were run with the bundled Python directory prepended to `PATH` while preserving the requested `python -m ...` command shape.

| Command | Result |
| --- | --- |
| `python -m ruff format --check src tests scripts` | PASS: 51 files already formatted |
| `python -m ruff check src tests scripts` | PASS |
| `python -m mypy src tests scripts` | PASS: no issues in 51 source files |
| `python -m pytest -q` | PASS: 159 passed |
| `python -m quantummindlite.cli validate-paperbench` | PASS: `ok: true`, `ready_count: 10` |

## First50 Audit Summary

The first50 fixture existed and was regenerated to:

- `corpus/algorithm_wiki/algowiki1901_rich_v1/reports/probe_first50_run_summary_labeled_audit.csv`
- `corpus/algorithm_wiki/algowiki1901_rich_v1/reports/probe_first50_run_summary_labeled_audit.md`

Label distribution:

| Label | Count |
| --- | ---: |
| `REGISTRY_GAP_INTERESTING` | 17 |
| `GENERIC_GROVERIZATION` | 17 |
| `LOW_VALUE_DUPLICATE_OR_VARIANT` | 10 |
| `BLOCKED_BY_ACCESS_OR_OUTPUT` | 3 |
| `HIGH_PRIORITY_EXPERT_REVIEW` | 3 |

Examples:

| Label | Example |
| --- | --- |
| `HIGH_PRIORITY_EXPERT_REVIEW` | `AW-000016-P0012` Lawrence Gibbs Sampling, selected `amplitude_estimation`, `POSITIVE/QUERY`. |
| `GENERIC_GROVERIZATION` | `AW-000047-P0025` Brute force, selected `amplitude_amplification`, `POSITIVE/QUERY`. |
| `REGISTRY_GAP_INTERESTING` | `AW-000069-P0042` Fringe Saving A*, no selected candidate, `NEGATIVE/NONE`. |
| `BLOCKED_BY_ACCESS_OR_OUTPUT` | `AW-000017-P0014` MotifSampler, selected `amplitude_estimation`, `POSITIVE/QUERY`, blocked by prerequisite/access/output concerns. |
| `LOW_VALUE_DUPLICATE_OR_VARIANT` | `AW-000060-P0031` Kruskal's algorithm with demand-sorting, selected `amplitude_amplification`, `POSITIVE/QUERY`. |

No first50 rows were `REJECT_OR_NO_SIGNAL`, `LOW_VALUE_FULL_OUTPUT`, `USEFUL_SUBROUTINE_CANDIDATE`, or `REVIEW_MANUALLY`. The audit CSV also had zero rows with both no selected candidate and no weak analogy, so absence of `REJECT_OR_NO_SIGNAL` is expected for this fixture rather than evidence that the rule is unreachable.

## Surprising Labels

- `MotifSampler` estimation (`AW-000017-P0014`) is `BLOCKED_BY_ACCESS_OR_OUTPUT`, not high priority. This is conservative and traceable to access/output/prerequisite barrier features; it is not rejected.
- Several negative graph-walk or search variants for brute force, Kruskal, and A* families are `REGISTRY_GAP_INTERESTING`. This is acceptable for human review triage because the label is distinct from positive claims and the selected candidate remains empty.
- No `USEFUL_SUBROUTINE_CANDIDATE` appeared in first50; the higher-priority estimation positives met the stricter high-priority rule, while generic or blocked cases fell into lower labels.

## Conclusion

PASS: `candidate_value_label` is safe to use for prioritizing human review. It is a deterministic post-hoc reporting label only. It does not alter selected candidates, B-rule results, verdicts, scopes, routes, PaperBench scoring, or runtime behavior.
